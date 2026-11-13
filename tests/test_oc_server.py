"""OC HTTP 边界、文件上传和静态资源的行为回归。"""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from app.oc.server import create_server, MAX_UPLOAD_BYTES


class PreviewService:
    def __init__(self):
        self.imported = None
        self.called = []
        self.queue = self

    def dispatch(self):
        pass

    def snapshot(self):
        return {'packages': [], 'processes': [], 'devices': [], 'jobs': []}

    def import_package(self, path):
        self.imported = (Path(path), Path(path).read_bytes())
        return {'id': 'hello@1.0.0'}

    def create_process(self, body):
        self.called.append(body)
        return dict(body, id='process-one')

    def get_job(self, job_id):
        raise KeyError(job_id)


class OcServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.web = self.directory / 'web'
        (self.web / 'assets').mkdir(parents=True)
        (self.web / 'index.html').write_text('<html>OC preview</html>', encoding='utf-8')
        (self.web / 'assets' / 'app.js').write_text('console.log("OC")', encoding='utf-8')
        (self.directory / 'private.txt').write_text('not a web resource', encoding='utf-8')
        self.service = PreviewService()
        self.server = create_server(self.service, self.web, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temporary.cleanup()

    def request(self, path, method='GET', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        request_headers = {'X-WBot-Token': self.server.token}
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            request_headers['Content-Type'] = 'application/json'
        request_headers.update(headers or {})
        try:
            connection.request(method, path, body, request_headers)
            response = connection.getresponse()
            content = response.read()
            if response.getheader('Content-Type', '').startswith('application/json'):
                content = json.loads(content)
            return response.status, content, dict(response.getheaders())
        finally:
            connection.close()

    def test_session_and_snapshot_do_not_expose_device_credentials(self):
        status, session, _ = self.request('/api/oc/session', headers={'X-WBot-Token': ''})
        self.assertEqual(status, 200)
        self.assertEqual(session['token'], self.server.token)
        self.assertEqual(session['mode'], 'local')
        status, snapshot, _ = self.request('/api/oc/state')
        self.assertEqual(status, 200)
        self.assertEqual(snapshot['devices'], [])
        self.assertNotIn('token', snapshot)
        self.assertEqual(snapshot['meta']['organization'], '默认组织')

    def test_host_origin_and_session_are_checked_before_mutations(self):
        invalid_headers = [
            {'Host': 'other.example'}, {'Origin': 'https://other.example'},
            {'Sec-Fetch-Site': 'cross-site'}, {'X-WBot-Token': ''},
            {'X-WBot-Token': '\u00e9'},
        ]
        for headers in invalid_headers:
            with self.subTest(headers=headers):
                status, _, _ = self.request('/api/oc/processes', 'POST', {'name': 'hello'}, headers)
                self.assertEqual(status, 403)
        self.assertEqual(self.service.called, [])
        status, process, _ = self.request('/api/oc/processes', 'POST', {'name': 'hello'},
                                         {'Origin': self.server.origin})
        self.assertEqual(status, 201)
        self.assertEqual(process['process']['id'], 'process-one')

    def test_upload_is_bounded_and_temporary_file_is_removed(self):
        archive = b'package-content'
        status, package, _ = self.request('/api/oc/packages', 'POST', archive,
                                          {'Content-Type': 'application/octet-stream'})
        self.assertEqual(status, 201)
        self.assertEqual(package['package']['id'], 'hello@1.0.0')
        path, actual = self.service.imported
        self.assertEqual(actual, archive)
        self.assertFalse(path.exists())
        status, _, _ = self.request('/api/oc/packages', 'POST', b'',
                                    {'Content-Type': 'application/octet-stream', 'Content-Length': str(MAX_UPLOAD_BYTES + 1)})
        self.assertEqual(status, 400)

    def test_json_errors_and_unknown_job_return_clear_errors(self):
        for body in [b'[]', b'{"defaults": NaN}', b'{"name": 1, "name": 2}', b'broken']:
            status, response, _ = self.request('/api/oc/processes', 'POST', body,
                                               {'Content-Type': 'application/json'})
            self.assertEqual(status, 400)
            self.assertIn('error', response)
        self.assertEqual(self.service.called, [])
        self.assertEqual(self.request('/api/oc/jobs/missing')[0], 404)

    def test_static_files_are_limited_to_built_frontend(self):
        self.assertEqual(self.request('/')[0], 200)
        status, source, headers = self.request('/assets/app.js')
        self.assertEqual(status, 200)
        self.assertIn(b'console.log', source)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        for path in ['/private.txt', '/../private.txt', '/assets/%2e%2e/%2e%2e/private.txt', '/src/App.tsx']:
            self.assertEqual(self.request(path)[0], 404)


if __name__ == '__main__':
    unittest.main()
