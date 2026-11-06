"""以真实 HTTP 验证设备凭据边界、慢速流取消及响应校验。"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest

from app.assistant.remote_client import GatewayClient, GatewayError, MAX_RESPONSE_BYTES


class GatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self._respond()

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self._respond()

    def _respond(self):
        self.server.received.append((self.command, self.path,
                                     self.headers.get('X-WBot-Device'),
                                     self.headers.get('X-WBot-Device-Token')))
        if self.path == '/api/agent/redirect':
            self.send_response(self.server.redirect_status)
            self.send_header('Location', self.server.redirect_url)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(65536 if self.server.trickle else len(self.server.payload)))
        self.end_headers()
        try:
            if not self.server.trickle:
                self.wfile.write(self.server.payload)
                return
            self.wfile.write(b' ')
            self.wfile.flush()
            self.server.stream_started.set()
            # 持续有字节到达，避免把 socket 空闲超时误当成取消成功。
            while not self.server.release_stream.wait(0.02):
                self.wfile.write(b' ')
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class GatewayClientTests(unittest.TestCase):
    def setUp(self):
        self.servers = []
        self.server = self.new_server()
        self.stop = threading.Event()
        self.client = GatewayClient({'server_url': self.origin(self.server),
                                     'device_id': 'test-device', 'secret': 'test-device-secret'},
                                    timeout=2, stop=self.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.destination = Path(self.temporary.name) / 'automation.wbot.zip'

    @staticmethod
    def origin(server):
        return f'http://127.0.0.1:{server.server_port}'

    def new_server(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), GatewayHandler)
        server.received = []
        server.payload = b'{"ok":true}'
        server.redirect_status = 302
        server.redirect_url = ''
        server.trickle = False
        server.stream_started = threading.Event()
        server.release_stream = threading.Event()
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        worker.start()
        self.servers.append((server, worker))
        return server

    def tearDown(self):
        self.stop.set()
        for server, worker in self.servers:
            server.release_stream.set()
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
        self.temporary.cleanup()

    def test_redirect_never_forwards_device_credentials(self):
        destination = self.new_server()
        self.server.redirect_url = self.origin(destination) + '/api/agent/target'
        for status, body in ((302, None), (307, {'operation': 'private'}), (308, {'operation': 'private'})):
            with self.subTest(status=status):
                self.server.redirect_status = status
                with self.assertRaises(GatewayError) as raised:
                    self.client.request('/api/agent/redirect', body)
                self.assertEqual(raised.exception.status, status)
                self.assertEqual(destination.received, [])
                self.assertEqual(self.server.received[-1][2:], ('test-device', 'test-device-secret'))

    def _assert_trickle_stops(self, operation):
        self.server.trickle = True
        finished = threading.Event()
        errors = []

        def call():
            try:
                operation()
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        try:
            self.assertTrue(self.server.stream_started.wait(2), 'HTTP 流未开始')
            self.stop.set()
            self.assertTrue(finished.wait(2), '停止信号发出后仍在等待凑满响应块')
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], InterruptedError)
        finally:
            self.server.release_stream.set()
            worker.join(timeout=2)

    def test_streaming_json_response_stops_without_waiting_for_full_chunk(self):
        self._assert_trickle_stops(lambda: self.client.request('/api/agent/poll'))

    def test_streaming_package_download_stops_without_waiting_for_full_chunk(self):
        command = {'id': 'job1', 'package_url': '/api/agent/jobs/job1/package',
                   'package_size': 65536, 'package_sha256': '0' * 64}
        self._assert_trickle_stops(lambda: self.client.download(command, self.destination, self.stop))
        if self.destination.exists():
            self.assertLess(self.destination.stat().st_size, command['package_size'])

    def test_invalid_json_and_non_object_responses_are_rejected(self):
        for payload in (b'not-json', b'[]', b'\xff'):
            with self.subTest(payload=payload):
                self.server.payload = payload
                with self.assertRaises(GatewayError):
                    self.client.request('/api/agent/poll')

    def test_response_limit_is_enforced_while_reading(self):
        self.server.payload = b' ' * (MAX_RESPONSE_BYTES + 1)
        with self.assertRaisesRegex(GatewayError, '8 MiB'):
            self.client.request('/api/agent/poll')

    def test_download_rejects_bytes_that_do_not_match_declared_digest(self):
        self.server.payload = b'actual-package-bytes'
        command = {'id': 'job1', 'package_url': '/api/agent/jobs/job1/package',
                   'package_size': len(self.server.payload),
                   'package_sha256': hashlib.sha256(b'another-package').hexdigest()}
        with self.assertRaisesRegex(ValueError, '校验失败'):
            self.client.download(command, self.destination, self.stop)
        self.assertEqual(self.destination.read_bytes(), self.server.payload)


if __name__ == '__main__':
    unittest.main()
