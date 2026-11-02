"""独立编码版的文件边界、保存冲突、真实 Python 运行与停止。"""
import tempfile
import time
import unittest
import threading
import json
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from pathlib import Path
from app.studio import Studio


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.studio = Studio(self.base / 'config.json', self.base / 'runs')
        state = self.studio.open_project(str(self.base / 'project'), True)
        self.project = state['project']

    def tearDown(self):
        self.studio.stop()
        self.tmp.cleanup()

    def done(self):
        until = time.monotonic() + 10
        while time.monotonic() < until:
            result = self.studio.status()
            if not result['running']: return result
            time.sleep(.03)
        self.fail('脚本未按预期结束')

    def test_file_save_conflict_and_project_switch(self):
        initial = self.studio.read(self.project, 'main.py')
        saved = self.studio.write(self.project, 'main.py', 'print(42)\n', initial['version'])
        self.assertEqual(saved['text'], 'print(42)\n')
        (self.studio.root / 'main.py').write_text('external edit', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '外部修改'):
            self.studio.write(self.project, 'main.py', 'overwrite', saved['version'])
        self.assertEqual((self.studio.root / 'main.py').read_text(), 'external edit')
        self.studio.open_project(str(self.base / 'other'), True)
        with self.assertRaises(ValueError): self.studio.read(self.project, 'main.py')

    def test_boundary_new_file_and_no_overwrite(self):
        for path in ('../outside.py', str(self.base / 'outside.py')):
            with self.assertRaises(ValueError): self.studio.write(self.project, path, 'bad', create=True)
        result = self.studio.write(self.project, 'helpers/test.py', 'x=1', create=True)
        self.assertEqual(result['text'], 'x=1')
        with self.assertRaises(FileExistsError): self.studio.write(self.project, 'helpers/test.py', 'bad', create=True)
        self.assertEqual(self.studio.read(self.project, 'helpers/test.py')['text'], 'x=1')
        self.assertTrue(any(item['directory'] and item['path'] == 'helpers' for item in self.studio.tree(self.project)))

    def test_real_runner_import_and_error(self):
        self.studio.write(self.project, 'app.py', '# 用户项目模块，不应遮蔽运行器', create=True)
        self.studio.write(self.project, 'helper.py', 'message="模块正常"', create=True)
        record = self.studio.read(self.project, 'main.py')
        code = 'from helper import message\nimport os\nprint(message)\nprint(os.environ["WBOT_BRIDGE_URL"])\nraise ValueError("实际错误")\n'
        self.studio.write(self.project, 'main.py', code, record['version'])
        self.studio.run(self.project, 'main.py', 'http://127.0.0.1:9876', self.base / 'elements.db')
        result = self.done()
        self.assertEqual(result['exitCode'], 1)
        self.assertIn('模块正常', result['log'])
        self.assertIn('9876', result['log'])
        self.assertIn('ValueError: 实际错误', result['log'])

    def test_stop_owned_process_and_reject_overlap(self):
        file = self.studio.read(self.project, 'main.py')
        self.studio.write(self.project, 'main.py', 'import time\nprint("started",flush=True)\ntime.sleep(60)', file['version'])
        self.studio.run(self.project, 'main.py', 'http://127.0.0.1:9876', self.base / 'elements.db')
        with self.assertRaises(ValueError): self.studio.run(self.project, 'main.py', '', '')
        with self.assertRaises(ValueError): self.studio.open_project(str(self.base / 'other'), True)
        result = self.studio.stop()
        self.assertFalse(result['running']); self.assertTrue(result['stopped'])
        self.assertIsNotNone(result['exitCode'])

    def test_http_token_origin_and_read_write(self):
        from app import studio, server
        previous = studio.STUDIO
        studio.STUDIO = self.studio
        httpd = server.create_server(0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        opener = build_opener(ProxyHandler({}))
        def call(action, data, origin=base):
            request = Request(base + '/api/studio/' + action, json.dumps(data).encode(),
                              headers={'Content-Type': 'application/json', 'Origin': origin})
            return json.load(opener.open(request, timeout=5))
        try:
            with self.assertRaises(HTTPError) as error:
                call('read', {'project': self.project, 'path': 'main.py'})
            self.assertEqual(error.exception.code, 403)
            with self.assertRaises(HTTPError) as error:
                call('stop', {'token': self.studio.token}, 'https://attacker.example')
            self.assertEqual(error.exception.code, 403)
            result = call('read', {'token': self.studio.token, 'project': self.project, 'path': 'main.py'})
            self.assertIn('WBot Studio', result['text'])
            saved = call('write', {'token': self.studio.token, 'project': self.project, 'path': 'main.py',
                                  'text': 'print(123)', 'version': result['version']})
            self.assertEqual(saved['text'], 'print(123)')
        finally:
            httpd.shutdown(); httpd.server_close(); studio.STUDIO = previous


if __name__ == '__main__': unittest.main()
