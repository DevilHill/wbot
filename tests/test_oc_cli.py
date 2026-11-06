"""验证 OC 独立启动、重启核对和执行端的独立生命周期。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from app.automation_package import build_package, create_project


ROOT = Path(__file__).resolve().parents[1]


class OcLifecycleTests(unittest.TestCase):
    def command(self, module, action, state_dir, *extra):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-m', module, action,
                                 '--state-dir', str(state_dir), *extra], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8', timeout=25,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_oc_restart_reconciles_job_without_stopping_assistant(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            assistant_dir, oc_dir = directory / 'assistant', directory / 'oc'
            web = directory / 'web'
            web.mkdir()
            (web / 'index.html').write_text('<html>OC</html>', encoding='utf-8')
            project = directory / 'project'
            create_project(project, 'oc-lifecycle')
            (project / 'main.py').write_text(
                'import time\nfrom wbot import runtime\ntime.sleep(4)\n'
                'print("任务独立完成")\nruntime.set_result({"ok": True})\n', encoding='utf-8')
            archive = build_package(project)
            try:
                self.command('app.assistant', 'start', assistant_dir, '--port', '0')
                started = self.command('app.oc', 'start', oc_dir, '--port', '0', '--agent-port', '0', '--web-dir', str(web))
                self.assertTrue(started['running'])
                self.assertNotIn('token', started)
                gateway_url = started['agent_gateway']['url']
                with build_opener(ProxyHandler({})).open(gateway_url + '/api/agent/health', timeout=3) as response:
                    self.assertEqual(json.load(response)['product'], 'wbot-oc-agent')

                def request(endpoint, body=None, raw=False):
                    metadata = json.loads((oc_dir / 'service.json').read_text(encoding='utf-8'))
                    headers = {'X-WBot-Token': metadata['token']}
                    if body is not None:
                        headers['Content-Type'] = 'application/octet-stream' if raw else 'application/json'
                        if not raw:
                            body = json.dumps(body).encode('utf-8')
                    req = Request(metadata['url'] + '/api/oc' + endpoint, body, headers)
                    with build_opener(ProxyHandler({})).open(req, timeout=10) as response:
                        return json.load(response)

                package = request('/packages', archive.read_bytes(), raw=True)['package']
                device = request('/devices', {'name': '本机执行端', 'state_dir': str(assistant_dir)})['device']
                process = request('/processes', {'name': '独立生命周期验证', 'description': '',
                    'package_id': package['id'], 'device_id': device['id'], 'defaults': {}, 'enabled': True})['process']
                job = request(f'/processes/{process["id"]}/run',
                              {'parameters': {}, 'request_id': 'lifecycle-job'})['job']
                self.command('app.oc', 'stop', oc_dir)
                with self.assertRaises(URLError):
                    build_opener(ProxyHandler({})).open(gateway_url + '/api/agent/health', timeout=1)
                self.assertTrue(self.command('app.assistant', 'status', assistant_dir)['running'])
                self.command('app.oc', 'start', oc_dir, '--port', '0', '--agent-port', '0', '--web-dir', str(web))
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    restored = request('/jobs/' + job['id'])['job']
                    if restored['state'] == 'succeeded':
                        break
                    time.sleep(0.15)
                self.assertEqual(restored['state'], 'succeeded', restored)
                self.assertEqual(restored['result'], {'ok': True})
                self.assertIn('任务独立完成', request('/jobs/' + job['id'] + '/log')['log'])
                self.assertEqual(len(request('/state')['jobs']), 1)
                self.assertEqual(self.command('app.oc', 'start', oc_dir)['pid'],
                                 self.command('app.oc', 'status', oc_dir)['pid'])
            finally:
                for module, state in [('app.oc', oc_dir), ('app.assistant', assistant_dir)]:
                    subprocess.run([sys.executable, '-m', module, 'stop', '--state-dir', str(state)],
                                   cwd=ROOT, capture_output=True, timeout=20,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


if __name__ == '__main__':
    unittest.main()
