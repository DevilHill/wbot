"""为 React 管理端提供同源 API 与构建后的静态资源。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
from pathlib import Path
import secrets
import tempfile
import threading
from urllib.parse import unquote, urlsplit


MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 68 * 1024 * 1024
DEFAULT_ASSISTANT_DIR = Path.home() / '.wbot-assistant'


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'JSON 包含重复字段：{key}')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f'JSON 不支持 {value}')


class OcServer(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, service, web_dir, port):
        self.web_dir = Path(web_dir).resolve()
        if not (self.web_dir / 'index.html').is_file():
            raise ValueError('找不到 OC 前端构建，请先在 oc-web 中执行 npm ci 和 npm run build')
        self.service = service
        self.agent_gateway = None
        self.token = secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1', port), OcHandler)

    @property
    def origin(self):
        return f'http://127.0.0.1:{self.server_port}'


class OcHandler(BaseHTTPRequestHandler):
    server: OcServer

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, *_args):
        pass

    def _send(self, status, content, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                         "frame-ancestors 'none'; object-src 'none'; base-uri 'self'")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'),
                   'application/json; charset=utf-8')

    def _authorized(self, path):
        expected_host = f'127.0.0.1:{self.server.server_port}'
        origin = self.headers.get('Origin')
        if (self.headers.get('Host') != expected_host
                or origin not in (None, self.server.origin)
                or self.headers.get('Sec-Fetch-Site', 'none') not in ('none', 'same-origin')):
            self._json(403, {'error': '仅允许本机同源访问 OC'})
            return False
        if path.startswith('/api/') and path != '/api/oc/session':
            token = self.headers.get('X-WBot-Token', '').encode('utf-8')
            if not secrets.compare_digest(token, self.server.token.encode('ascii')):
                self._json(403, {'error': 'OC 会话已失效，请刷新页面'})
                return False
        return True

    def _body_size(self, maximum, accepted_types):
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('不支持分块请求')
        content_type = self.headers.get('Content-Type', '').split(';')[0].strip().lower()
        if content_type not in accepted_types:
            raise ValueError('请求内容类型无效')
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError as exc:
            raise ValueError('请求长度无效') from exc
        if not 0 < size <= maximum:
            raise ValueError(f'请求为空或超过 {maximum // 1024 // 1024} MiB')
        return size

    def _read_json(self):
        size = self._body_size(MAX_JSON_BYTES, {'application/json'})
        content = self.rfile.read(size)
        if len(content) != size:
            raise ValueError('请求未完整接收')
        body = json.loads(content.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
        if not isinstance(body, dict):
            raise ValueError('请求必须是 JSON 对象')
        return body

    def _upload_package(self):
        size = self._body_size(MAX_UPLOAD_BYTES, {'application/octet-stream', 'application/zip'})
        with tempfile.TemporaryDirectory(prefix='wbot-oc-upload-') as directory:
            archive = Path(directory) / 'upload.wbot.zip'
            with archive.open('xb') as stream:
                remaining = size
                while remaining:
                    chunk = self.rfile.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise ValueError('发布包未完整接收')
                    stream.write(chunk)
                    remaining -= len(chunk)
            package = self.server.service.import_package(archive)
        self._json(201, {'package': package})

    def do_GET(self):
        self._handle('GET')

    def do_POST(self):
        self._handle('POST')

    def do_PATCH(self):
        self._handle('PATCH')

    def _handle(self, method):
        path = urlsplit(self.path).path
        if not self._authorized(path):
            return
        try:
            if method == 'GET':
                self._get(path)
            elif path == '/api/oc/packages' and method == 'POST':
                self._upload_package()
            else:
                self._mutate(method, path, self._read_json())
        except (BrokenPipeError, ConnectionResetError):
            return
        except (KeyError, FileNotFoundError):
            self._json(404, {'error': '找不到指定的发布包、流程、设备或作业'})
        except FileExistsError as exc:
            self._json(409, {'error': str(exc)})
        except (ValueError, UnicodeError) as exc:
            self._json(400, {'error': str(exc)})
        except RuntimeError as exc:
            self._json(409, {'error': str(exc)})
        except OSError as exc:
            self._json(503, {'error': f'本机服务或存储暂不可用：{exc}'})
        except Exception:
            logging.exception('OC 请求处理失败')
            self._json(500, {'error': 'OC 服务发生错误，请查看 service.log'})

    def _get(self, path):
        service = self.server.service
        if path == '/api/oc/session':
            self._json(200, {'token': self.server.token, 'mode': 'local', 'organization': '默认组织',
                             'default_assistant_dir': str(DEFAULT_ASSISTANT_DIR),
                             'agent_gateway': self.server.agent_gateway})
        elif path == '/api/oc/health':
            self._json(200, {'product': 'wbot-oc', 'ok': True, 'mode': 'local'})
        elif path == '/api/oc/state':
            snapshot = service.snapshot()
            self._json(200, dict(snapshot, meta={'mode': 'local', 'organization': '默认组织'}))
        elif path.startswith('/api/oc/jobs/'):
            parts = path.strip('/').split('/')
            if len(parts) == 4:
                self._json(200, {'job': service.get_job(parts[3])})
            elif len(parts) == 5 and parts[4] == 'log':
                self._json(200, service.read_log(parts[3]))
            else:
                self._json(404, {'error': '接口不存在'})
        else:
            self._static(path)

    def _mutate(self, method, path, body):
        service = self.server.service
        if method == 'POST' and path == '/api/oc/devices':
            self._json(201, {'device': service.add_device(body.get('name'), body.get('state_dir'))})
        elif method == 'POST' and path == '/api/oc/processes':
            self._json(201, {'process': service.create_process(body)})
        elif method == 'POST' and path == '/api/oc/service/stop':
            self._json(200, {'ok': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            parts = path.strip('/').split('/')
            if (len(parts) == 5 and parts[:3] == ['api', 'oc', 'devices'] and method == 'POST'
                    and parts[4] in ('approve', 'reject', 'revoke')):
                if body:
                    raise ValueError('设备审批请求必须为空对象')
                self._json(200, {'device': service.agents.decide(parts[3], parts[4])})
            elif len(parts) == 4 and parts[:3] == ['api', 'oc', 'devices'] and method == 'PATCH':
                if set(body) != {'maintenance'} or type(body['maintenance']) is not bool:
                    raise ValueError('设备更新只接受 maintenance 布尔字段')
                self._json(200, {'device': service.update_device(parts[3], body['maintenance'])})
            elif len(parts) == 4 and parts[:3] == ['api', 'oc', 'processes'] and method == 'PATCH':
                self._json(200, {'process': service.update_process(parts[3], body)})
            elif (len(parts) == 5 and parts[:3] == ['api', 'oc', 'processes']
                  and parts[4] == 'run' and method == 'POST'):
                self._json(201, {'job': service.run_process(parts[3], body.get('parameters', {}), body.get('request_id'))})
            elif (len(parts) == 5 and parts[:3] == ['api', 'oc', 'jobs']
                  and parts[4] == 'stop' and method == 'POST'):
                self._json(200, {'job': service.stop_job(parts[3])})
            else:
                self._json(404, {'error': '接口不存在'})

    def _static(self, path):
        relative = 'index.html' if path == '/' else unquote(path).lstrip('/')
        if relative != 'index.html' and not relative.startswith('assets/') and relative != 'favicon.svg':
            self._json(404, {'error': '页面不存在'})
            return
        target = (self.server.web_dir / relative).resolve()
        if not target.is_relative_to(self.server.web_dir) or not target.is_file():
            self._json(404, {'error': '资源不存在'})
            return
        content_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        if target.suffix in {'.js', '.mjs'}:
            content_type = 'text/javascript'
        if target.suffix in {'.html', '.css', '.js', '.mjs', '.svg'}:
            content_type += '; charset=utf-8'
        self._send(200, target.read_bytes(), content_type)


def create_server(service, web_dir, port=8792):
    return OcServer(service, web_dir, port)
