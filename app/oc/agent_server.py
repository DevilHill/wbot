"""独立设备通信端口；不提供管理会话、静态页面或跨域浏览器访问。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import socket
import ssl
from urllib.parse import urlsplit

from .agent_service import AgentDenied
from .server import _reject_constant, _unique_object


MAX_REPORT_BYTES = 6 * 1024 * 1024
MAX_CONTROL_BYTES = 8192


class AgentServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, service, host, port, certfile=None, keyfile=None):
        if bool(certfile) != bool(keyfile):
            raise ValueError('agent TLS 证书与私钥必须同时提供')
        context = None
        if certfile:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(certfile, keyfile, password='')
        self.service = service
        self.host = host
        self.scheme = 'https' if context else 'http'
        if ':' in host:
            self.address_family = socket.AF_INET6
        super().__init__((host, port), AgentHandler)
        if context:
            try:
                self.socket = context.wrap_socket(self.socket, server_side=True, do_handshake_on_connect=False)
            except Exception:
                self.server_close()
                raise

    @property
    def origin(self):
        hostname = f'[{self.host}]' if ':' in self.host else self.host
        return f'{self.scheme}://{hostname}:{self.server_port}'

    def connection_info(self):
        return {'host': self.host, 'port': self.server_port, 'scheme': self.scheme,
                'url': self.origin, 'public_host_required': self.host in ('0.0.0.0', '::')}


class AgentHandler(BaseHTTPRequestHandler):
    server: AgentServer

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, *_args):
        pass

    def handle(self):
        try:
            super().handle()
        except (ssl.SSLError, BrokenPipeError, ConnectionResetError):
            # TLS 校验失败或客户端中途断开时，尚无可返回的 HTTP 会话。
            return

    def _headers(self, status, size, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(size))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()

    def _json(self, status, payload):
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self._headers(status, len(content), 'application/json; charset=utf-8')
        self.wfile.write(content)

    def _read_json(self, maximum):
        if self.headers.get_all('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
            raise ValueError('请求必须有唯一 Content-Length，不能使用分块传输')
        if len(self.headers.get_all('Content-Type', [])) != 1:
            raise ValueError('请求内容类型无效')
        if self.headers['Content-Type'].split(';')[0].strip().lower() != 'application/json':
            raise ValueError('请求必须为 application/json')
        try:
            length = int(self.headers['Content-Length'])
        except ValueError as exc:
            raise ValueError('请求长度无效') from exc
        if not 0 < length <= maximum:
            raise ValueError(f'请求为空或超过 {maximum} 字节')
        content = self.rfile.read(length)
        if len(content) != length:
            raise ValueError('请求未完整接收')
        body = json.loads(content.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
        if not isinstance(body, dict):
            raise ValueError('请求必须为 JSON 对象')
        return body

    def do_GET(self):
        self._handle('GET')

    def do_POST(self):
        self._handle('POST')

    def do_OPTIONS(self):
        self._json(405, {'error': '设备通信不支持浏览器跨域请求'})

    def _handle(self, method):
        try:
            if self.headers.get_all('Origin') or self.headers.get('Sec-Fetch-Site', 'none') != 'none':
                raise AgentDenied('设备通信端口不接受浏览器来源请求')
            target = urlsplit(self.path)
            if target.scheme or target.netloc or target.query or target.fragment:
                raise ValueError('设备接口地址格式无效')
            path = target.path
            if path == '/api/agent/health' and method == 'GET':
                self._json(200, {'product': 'wbot-oc-agent', 'protocol_version': 1})
                return
            if path == '/api/agent/enroll' and method == 'POST':
                self._json(201, {'device': self.server.service.agents.enroll(self._read_json(MAX_CONTROL_BYTES))})
                return
            parts = path.strip('/').split('/')
            job_route = (len(parts) == 5 and parts[:3] == ['api', 'agent', 'jobs']
                         and ((method == 'GET' and parts[4] == 'package')
                              or (method == 'POST' and parts[4] == 'report')))
            if not job_route and (method, path) not in {
                    ('GET', '/api/agent/status'), ('POST', '/api/agent/poll')}:
                self._json(404, {'error': '设备接口不存在'})
                return
            if any(len(self.headers.get_all(name, [])) != 1
                   for name in ('X-WBot-Device', 'X-WBot-Device-Token')):
                raise AgentDenied('设备身份或凭据无效')
            agents = self.server.service.agents
            device = agents.authenticate(self.headers['X-WBot-Device'], self.headers['X-WBot-Device-Token'])
            if path == '/api/agent/status':
                self._json(200, agents.status(device))
            elif path == '/api/agent/poll':
                self._json(200, agents.poll(device, self._read_json(MAX_CONTROL_BYTES)))
            elif parts[4] == 'report':
                self._json(200, agents.report(device, parts[3], self._read_json(MAX_REPORT_BYTES)))
            else:
                archive = self.server.service.agent_package(device, parts[3])
                with archive.open('rb') as stream:
                    self._headers(200, archive.stat().st_size, 'application/zip')
                    while chunk := stream.read(1024 * 1024):
                        self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return
        except AgentDenied as exc:
            self._json(403, {'error': str(exc)})
        except (KeyError, FileNotFoundError):
            self._json(404, {'error': '找不到该设备的任务或发布包'})
        except (ValueError, UnicodeError, RecursionError) as exc:
            self._json(400, {'error': str(exc)})
        except RuntimeError as exc:
            self._json(409, {'error': str(exc)})
        except OSError:
            self._json(503, {'error': '设备通信服务暂不可用'})
        except Exception:
            logging.exception('Agent 请求处理失败')
            self._json(500, {'error': '设备通信服务发生错误'})


def create_agent_server(service, host='127.0.0.1', port=8793, certfile=None, keyfile=None):
    return AgentServer(service, host, port, certfile, keyfile)
