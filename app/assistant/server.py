"""仅供本机 Assistant 界面使用的 HTTP 接口。"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit

from .protocol import MAX_REQUEST_BYTES
from .shared_elements import SharedElementService
from .remote_client import GatewayError
from .updates import UpdateService
from .version import VERSION


WEB_ROOT = Path(__file__).with_name("web")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assistant.js": ("assistant.js", "text/javascript; charset=utf-8"),
    "/assistant.css": ("assistant.css", "text/css; charset=utf-8"),
}


class AssistantServer(ThreadingHTTPServer):
    def __init__(self, execution, port, connection=None):
        self.updates = UpdateService(execution, connection)
        super().__init__(("127.0.0.1", port), AssistantHandler)
        self.execution = execution
        self.oc_connection = connection
        self.shared_elements = SharedElementService(connection) if connection is not None else None
        self.token = secrets.token_urlsafe(32)

    def server_close(self):
        self.updates.close()
        super().server_close()

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_port}"


class AssistantHandler(BaseHTTPRequestHandler):
    server: AssistantServer

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_args):
        pass

    def _send(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; object-src 'none'")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _authorize(self, path):
        expected_host = f"127.0.0.1:{self.server.server_port}"
        origin = self.headers.get("Origin")
        is_local = (self.headers.get("Host") == expected_host
                    and (origin is None or origin == self.server.origin)
                    and self.headers.get("Sec-Fetch-Site", "none") in ("none", "same-origin"))
        if not is_local:
            self._json(403, {"error": "仅允许本机同源访问"})
            return False
        if path.startswith("/api/") and path != "/api/session":
            supplied = self.headers.get("X-WBot-Token", "").encode("utf-8")
            if not secrets.compare_digest(supplied, self.server.token.encode("ascii")):
                self._json(403, {"error": "Assistant 会话已失效，请刷新页面"})
                return False
        return True

    def _read_body(self):
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("不支持分块请求")
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ValueError("需要 application/json 请求")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("请求长度无效") from exc
        if not 0 < size <= MAX_REQUEST_BYTES:
            raise ValueError("请求为空或超过 2 MiB")
        content = self.rfile.read(size)
        if len(content) != size:
            raise ValueError("请求未完整接收")
        body = json.loads(content.decode("utf-8"), parse_constant=self._reject_constant)
        if not isinstance(body, dict):
            raise ValueError("请求必须是 JSON 对象")
        return body

    @staticmethod
    def _reject_constant(value):
        raise ValueError(f"JSON 不支持 {value}")

    @staticmethod
    def _required_text(body, key):
        value = body.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise ValueError(f"{key} 必须是非空字符串")
        return value

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method):
        path = urlsplit(self.path).path
        if not self._authorize(path):
            return
        try:
            if method == "GET":
                self._get(path)
            else:
                self._post(path, self._read_body())
        except (KeyError, FileNotFoundError):
            self._json(404, {"error": "找不到指定的文件、发布包或作业"})
        except FileExistsError as exc:
            self._json(409, {"error": str(exc)})
        except (ValueError, UnicodeError) as exc:
            self._json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self._json(409, {"error": str(exc)})
        except PermissionError as exc:
            self._json(403, {"error": str(exc)})
        except GatewayError as exc:
            self._json(exc.status if exc.status in (400, 403, 404, 409, 413) else 503, {"error": str(exc)})
        except OSError as exc:
            self._json(500, {"error": f"本机读写失败：{exc}"})
        except Exception:
            logging.exception("Assistant 请求处理失败")
            self._json(500, {"error": "后台服务发生错误，请查看服务日志"})

    def _get(self, path):
        execution = self.server.execution
        if path == "/api/session":
            self._json(200, {"token": self.server.token, "mode": "local"})
        elif path == "/api/health":
            self._json(200, {"ok": True, "product": "wbot-assistant", "mode": "local",
                             "version": VERSION, "updating": execution.updating})
        elif path == '/api/updates':
            self._json(200, {'update': self.server.updates.snapshot()})
        elif path == "/api/packages":
            self._json(200, {"items": execution.list_packages()})
        elif path == "/api/settings":
            self._json(200, {"settings": self._connection().snapshot()})
        elif path == "/api/jobs":
            self._json(200, {"items": execution.list_jobs()})
        elif path == "/api/jobs/summary":
            self._json(200, execution.job_summary())
        elif path.startswith("/api/jobs/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                self._json(200, {"job": execution.get_job(parts[2])})
            elif len(parts) == 4 and parts[3] == "log":
                self._json(200, {"log": execution.read_log(parts[2])})
            else:
                self._json(404, {"error": "接口不存在"})
        elif path in STATIC_FILES:
            name, content_type = STATIC_FILES[path]
            self._send(200, (WEB_ROOT / name).read_bytes(), content_type)
        else:
            self._json(404, {"error": "页面不存在"})

    def _post(self, path, body):
        execution = self.server.execution
        if path.startswith('/api/updates/'):
            self._update_action(path, body)
        elif path.startswith('/api/shared-elements/'):
            self._connection()
            self._json(200, self.server.shared_elements.dispatch(path.removeprefix('/api/shared-elements/'), body))
        elif path == "/api/settings/connect":
            if set(body) != {'server_url', 'device_name'}:
                raise ValueError('连接设置需要 server_url 与 device_name')
            self._json(200, {'settings': self._connection().connect(body['server_url'], body['device_name'])})
        elif path == "/api/settings/disconnect":
            if body:
                raise ValueError('断开连接不接受额外参数')
            self._json(200, {'settings': self._connection().disconnect()})
        elif path == "/api/packages":
            archive = Path(self._required_text(body, "path"))
            if not archive.is_absolute():
                raise ValueError("请输入发布包的本机完整路径")
            self._json(201, {"package": execution.install_package(archive)})
        elif path == "/api/jobs":
            package_id = self._required_text(body, "package_id")
            parameters = body.get("parameters", {})
            if not isinstance(parameters, dict):
                raise ValueError("parameters 必须是对象")
            request_id = body.get("request_id")
            if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 128):
                raise ValueError("request_id 必须为 1–128 字符")
            self._json(201, {"job": execution.submit(package_id, parameters, request_id=request_id)})
        elif path.startswith("/api/jobs/") and path.endswith("/stop"):
            parts = path.strip("/").split("/")
            if len(parts) != 4:
                raise ValueError("作业路径无效")
            self._json(200, {"job": execution.stop_job(parts[2])})
        elif path == "/api/service/stop":
            self._json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._json(404, {"error": "接口不存在"})

    def _connection(self):
        if self.server.oc_connection is None:
            raise RuntimeError('此执行服务尚未启用连接设置，请更新并重启 Assistant 后台服务')
        return self.server.oc_connection

    def _update_action(self, path, body):
        updates = self.server.updates
        if path in ('/api/updates/check', '/api/updates/download'):
            if body:
                raise ValueError('检查或下载更新不接受额外参数')
            result = updates.check() if path.endswith('/check') else updates.download()
        elif path == '/api/updates/install':
            if set(body) != {'desktop_pid'}:
                raise ValueError('安装更新需要界面进程标识')
            result = updates.install(body['desktop_pid'])
        elif path in ('/api/updates/stop', '/api/updates/resume'):
            self.server.execution.authorize_update(body.get('token'))
            if path.endswith('/stop'):
                if not self.server.execution.updating:
                    raise RuntimeError('更新尚未锁定执行端')
                self._json(200, {'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self.server.execution.resume_update(body['token'])
            result = updates.snapshot()
        else:
            self._json(404, {'error': '更新接口不存在'})
            return
        self._json(200, {'update': result})


def create_server(execution, port=0, connection=None):
    return AssistantServer(execution, port, connection)
