"""Assistant-owned browser listener; authenticated editor calls reuse the existing bridge."""
from __future__ import annotations

import http.client
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import threading

READ_PATHS = {'/api/health', '/api/elements', '/api/elements/export', '/api/bridge/last'}
WRITE_PATHS = {'/api/elements/save', '/api/elements/delete', '/api/elements/import',
               '/api/bridge/pick', '/api/bridge/stop', '/api/bridge/validate'}


def browser_handler():
    from app.server import Handler

    class BrowserHandler(Handler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)
            with self.server.connections_lock:
                self.server.connections.add(self.connection)

        def finish(self):
            try:
                super().finish()
            finally:
                with self.server.connections_lock:
                    self.server.connections.discard(self.connection)

        def authorized(self, method):
            path = self.path
            origin = self.headers.get('Origin')
            local = f'127.0.0.1:{self.server.server_port}'
            extension = origin and re.fullmatch(r'(?:chrome|moz)-extension://[A-Za-z0-9-]+', origin)
            if (self.headers.get('Host') not in (local, f'localhost:{self.server.server_port}')
                    or origin and origin not in (f'http://{local}', f'http://localhost:{self.server.server_port}') and not extension):
                self._send_json({'ok': False, 'error': '仅允许本机客户端和浏览器扩展访问'}, 403)
                return False
            public = {'GET': {'/ws', '/api/health', '/api/bridge/last'}, 'POST': {'/api/bridge/result', '/api/wbot/command'}}
            private = READ_PATHS if method == 'GET' else WRITE_PATHS
            if path not in public[method] | private:
                self._send_json({'ok': False, 'error': '接口不存在'}, 404)
                return False
            if path not in public[method] and not secrets.compare_digest(
                    self.headers.get('X-WBot-Element-Token', '').encode(), self.server.element_token.encode()):
                self._send_json({'ok': False, 'error': '请通过 Assistant 访问元素库'}, 403)
                return False
            if method == 'POST':
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    length = 0
                if self.headers.get('Transfer-Encoding') or not 0 < length <= 2 * 1024 * 1024 or self.headers.get_content_type() != 'application/json':
                    self._send_json({'ok': False, 'error': '需要小于 2 MiB 的 JSON'}, 400)
                    return False
            return True

        def do_GET(self):
            if self.authorized('GET'):
                if self.path == '/ws':
                    self.connection.settimeout(None)
                super().do_GET()

        def do_POST(self):
            if self.authorized('POST'):
                super().do_POST()

    return BrowserHandler


class BrowserService:
    def __init__(self, state_dir, port=None, library_path=None):
        self.state_dir = Path(state_dir)
        self.port = int(os.environ.get('WBOT_BROWSER_PORT', '8790')) if port is None else port
        self.library_path = Path(library_path or os.environ.get('WBOT_ELEMENT_LIBRARY')
                                 or Path.home() / '.xpath_studio' / 'elements.sqlite3').resolve()
        self._lock = threading.RLock()
        self._server = None
        self._thread = None
        self._closed = False

    def start(self):
        with self._lock:
            if self._closed:
                raise RuntimeError('Assistant 正在退出')
            if self._server is None:
                try:
                    server = ThreadingHTTPServer(('127.0.0.1', self.port), browser_handler())
                except OSError as exc:
                    raise RuntimeError(f'Assistant 浏览器端口 {self.port} 不可用，请关闭旧版插件启动的浏览器服务后重试') from exc
                server.daemon_threads = True
                server.block_on_close = False
                server.element_library_path = self.library_path
                server.element_token = secrets.token_urlsafe(32)
                server.connections = set()
                server.connections_lock = threading.Lock()
                self._server = server
                self._thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
                self._thread.start()
            return {'bridge_url': f'http://127.0.0.1:{self._server.server_port}',
                    'library_path': str(self.library_path)}

    def dispatch(self, request):
        path = request.get('path')
        if path == '/api/extension/prepare' and set(request) == {'path'}:
            return self.prepare_extension()
        if not isinstance(path, str) or path not in READ_PATHS | WRITE_PATHS or set(request) - {'path', 'body'}:
            raise ValueError('不支持的元素服务接口')
        body = request.get('body')
        if path in WRITE_PATHS and not isinstance(body, dict) or path in READ_PATHS and 'body' in request:
            raise ValueError('元素接口请求格式无效')
        self.start()
        with self._lock:
            server = self._server
            if server is None:
                raise RuntimeError('Assistant 正在退出')
            port, token = server.server_port, server.element_token
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=12)
        try:
            connection.request('POST' if body is not None else 'GET', path,
                               json.dumps(body) if body is not None else None,
                               {'X-WBot-Element-Token': token, 'Content-Type': 'application/json'})
            response = connection.getresponse()
            payload = json.loads(response.read(8 * 1024 * 1024 + 1))
            if response.status >= 400:
                raise ValueError(payload.get('error', '元素服务请求失败'))
            return payload
        finally:
            connection.close()

    def prepare_extension(self):
        info = self.start()
        source = Path(__file__).resolve().parents[2] / 'extension'
        destination = self.state_dir / 'browser-extension'
        if destination.is_symlink():
            raise ValueError('浏览器扩展目录不能是符号链接')
        shutil.copytree(source, destination, dirs_exist_ok=True)
        background = destination / 'background.js'
        script = background.read_text(encoding='utf-8')
        script = script.replace('var DEFAULT_BRIDGE = "http://127.0.0.1:8790";',
                                'var DEFAULT_BRIDGE = ' + json.dumps(info['bridge_url']) + ';')
        background.write_text(script, encoding='utf-8')
        return {'directory': str(destination)}

    def close(self):
        with self._lock:
            self._closed = True
            server, self._server = self._server, None
            if server is None:
                return
            server.shutdown()
            with server.connections_lock:
                connections = list(server.connections)
            for connection in connections:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
            server.server_close()
            self._thread.join(timeout=2)
