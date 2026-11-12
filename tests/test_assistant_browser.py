"""Assistant owns element storage and the browser bridge independently of VS Code."""
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from app.assistant.server import create_server
from tests.test_assistant_server import RecordingExecution


class AssistantBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.library = Path(self.temporary.name) / 'elements.sqlite3'
        self.server = create_server(RecordingExecution(self.temporary.name), browser_port=0, library_path=self.library)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path='/api/browser', body=None, token=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-WBot-Token'] = self.server.token
        connection.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_authorized_element_operations_use_assistant_library(self):
        self.assertEqual(self.request(token=False)[0], 403)
        status, info = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(info['library_path'], str(self.library))
        record = {'name': '搜索框', 'xpath': '//input', 'group': '首页'}
        status, saved = self.request(body={'path': '/api/elements/save', 'body': {'record': record}})
        self.assertEqual(status, 200)
        status, items = self.request(body={'path': '/api/elements'})
        self.assertEqual(items['items'][0]['id'], saved['item']['id'])
        self.assertEqual(self.request(body={'path': '/api/settings/connect', 'body': {}})[0], 400)
        self.assertEqual(self.request(body={'path': '/api/bridge/pick', 'body': {}})[1]['ok'], False)

    def test_browser_port_cannot_write_elements_without_assistant_token(self):
        _, info = self.request()
        from urllib.parse import urlsplit
        url = urlsplit(info['bridge_url'])
        connection = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
        connection.request('POST', '/api/elements/save', json.dumps({'record': {'name': '非法', 'xpath': '//a'}}), {'Content-Type': 'application/json'})
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        connection.close()
        self.assertEqual(self.request(body={'path': '/api/elements'})[1]['items'], [])

    def test_browser_rejects_web_origins_and_releases_port_on_shutdown(self):
        _, info = self.request()
        from urllib.parse import urlsplit
        port = urlsplit(info['bridge_url']).port
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        connection.request('GET', '/api/health', headers={'Origin': 'https://attacker.example'})
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        connection.close()
        self.server.browser.close()
        with self.assertRaises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=1)

    def test_capture_and_xpath_validation_travel_through_assistant_and_websocket(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        from app.ws_bridge import WSClientConn
        _, info = self.request()
        client = WSClientConn(info['bridge_url'].replace('http:', 'ws:') + '/ws', timeout=3,
                              origin='chrome-extension://' + 'a' * 32)
        client.connect()
        self.addCleanup(client.close)
        client.recv_json()
        client.send_json({'type': 'hello', 'role': 'extension', 'browserId': 'test-browser'})
        deadline = time.monotonic() + 3
        while self.request(body={'path': '/api/health'})[1]['bridge']['extensions'] != 1:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.02)
        self.assertTrue(self.request(body={'path': '/api/bridge/pick', 'body': {}})[1]['ok'])
        while client.recv_json().get('type') != 'start-pick':
            pass
        target = {'browserId': 'test-browser', 'tabId': 1, 'frameId': 0, 'documentId': 'document-1'}
        client.send_json({'type': 'picked', 'payload': {'xpath': '//input', 'browserId': 'test-browser', 'frame': target}})
        deadline = time.monotonic() + 3
        while self.request(body={'path': '/api/bridge/last'})[1]['payload'] is None:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.02)
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(self.request, body={'path': '/api/bridge/validate',
                'body': {'target': target, 'action': 'validate', 'xpath': '//input'}})
            command = client.recv_json()
            while command.get('type') != 'browser-command':
                command = client.recv_json()
            self.assertEqual(command['target'], target)
            client.send_json({'type': 'browser-result', 'requestId': command['requestId'],
                              'result': {'ok': True, 'valid': True, 'count': 1, 'highlighted': 1}})
            status, payload = result.result(timeout=4)
            self.assertEqual(status, 200)
            self.assertEqual(payload['highlighted'], 1)

    def test_port_conflict_does_not_attach_to_an_unrelated_service(self):
        from app.assistant.browser_service import BrowserService
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            service = BrowserService(self.temporary.name, occupied.getsockname()[1], self.library)
            self.addCleanup(service.close)
            with self.assertRaisesRegex(RuntimeError, '端口'):
                service.start()
