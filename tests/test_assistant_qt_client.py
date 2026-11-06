"""Qt 客户端必须异步访问本机服务，并保护执行端会话。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    from app.assistant.qt_client import AssistantClient


class LocalHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.server.received.append((self.path, self.headers.get('X-WBot-Token')))
        if self.path == '/api/redirect':
            self.send_response(302)
            self.send_header('Location', self.server.redirect_url)
            self.end_headers()
            return
        if self.path == '/api/slow':
            time.sleep(0.15)
        if self.headers.get('X-WBot-Token') != 'local-secret':
            status, content = 403, b'{"error":"expired"}'
        else:
            status, content = 200, b'{"items":[{"id":"hello@1.0.0"}]}'
        if self.path == '/api/invalid':
            content = b'not json'
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


@unittest.skipUnless(HAS_QT, '未安装可选 PySide6-Essentials')
class QtClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.servers = []
        self.server = self.new_server()
        self.write_metadata(self.server)
        self.client = AssistantClient(self.directory, timeout_ms=1000)

    def new_server(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), LocalHandler)
        server.received = []
        server.redirect_url = ''
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)
        return server

    def write_metadata(self, server, token='local-secret'):
        (self.directory / 'service.json').write_text(json.dumps({
            'url': f'http://127.0.0.1:{server.server_port}', 'token': token,
        }), encoding='utf-8')

    def tearDown(self):
        self.client.close()
        self.app.processEvents()
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.temporary.cleanup()

    def request(self, path):
        events = []
        loop = QEventLoop()
        def finish(kind, value):
            events.append((kind, value))
            loop.quit()
        self.client.request('GET', path,
                            on_success=lambda value: finish('success', value),
                            on_error=lambda value: finish('error', value))
        QTimer.singleShot(2500, loop.quit)
        loop.exec()
        self.assertEqual(len(events), 1)
        return events[0]

    def test_async_request_keeps_event_loop_responsive_and_uses_token(self):
        ticks = []
        QTimer.singleShot(20, lambda: ticks.append('responsive'))
        kind, content = self.request('/api/slow')
        self.assertEqual(kind, 'success')
        self.assertEqual(content['items'][0]['id'], 'hello@1.0.0')
        self.assertEqual(ticks, ['responsive'])
        self.assertEqual(self.server.received, [('/api/slow', 'local-secret')])

    def test_restarting_service_metadata_is_reloaded_for_each_request(self):
        self.assertEqual(self.request('/api/packages')[0], 'success')
        replacement = self.new_server()
        self.write_metadata(replacement)
        self.assertEqual(self.request('/api/packages')[0], 'success')
        self.assertEqual(len(replacement.received), 1)

    def test_redirect_never_sends_token_to_another_server(self):
        destination = self.new_server()
        self.server.redirect_url = f'http://127.0.0.1:{destination.server_port}/api/packages'
        self.assertEqual(self.request('/api/redirect')[0], 'error')
        self.assertEqual(destination.received, [])

    def test_invalid_json_and_expired_session_are_explicit_errors(self):
        self.assertEqual(self.request('/api/invalid')[0], 'error')
        self.write_metadata(self.server, token='expired')
        kind, message = self.request('/api/packages')
        self.assertEqual(kind, 'error')
        self.assertIn('expired', message)

    def test_remote_metadata_and_absolute_endpoints_are_rejected(self):
        self.assertEqual(self.request('https://example.com/api/packages')[0], 'error')
        metadata = self.directory / 'service.json'
        metadata.write_text('{"url":"http://example.com","token":"local-secret"}', encoding='utf-8')
        self.assertEqual(self.request('/api/packages')[0], 'error')
        self.assertEqual(self.server.received, [])

    def test_oversized_parameters_are_rejected_before_sending(self):
        errors = []
        reply = self.client.request('POST', '/api/jobs',
                                    body={'parameters': {'text': '中' * 750000}},
                                    on_error=errors.append)
        self.assertIsNone(reply)
        self.app.processEvents()
        self.assertEqual(len(errors), 1)
        self.assertIn('2 MiB', errors[0])
        self.assertEqual(self.server.received, [])

    def test_timeout_and_client_close_do_not_leave_pending_callbacks(self):
        self.client.close()
        self.client = AssistantClient(self.directory, timeout_ms=40)
        self.assertEqual(self.request('/api/slow')[0], 'error')
        calls = []
        self.client.request('GET', '/api/slow', on_success=calls.append, on_error=calls.append)
        self.client.close()
        loop = QEventLoop()
        QTimer.singleShot(250, loop.quit)
        loop.exec()
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
