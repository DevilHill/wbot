"""通过真实 Assistant HTTP 与任务进程验证 OC 编排和持久化。"""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app.assistant.execution import ExecutionService
from app.assistant.server import create_server
from app.automation_package import build_package
from app.oc.service import OcService
from tests.flow_environment import prepare_environment


class OcServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assistant_dir = self.root / 'assistant'
        self.execution = ExecutionService(self.assistant_dir)
        self.server = create_server(self.execution, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.metadata = self.assistant_dir / 'service.json'
        self.metadata.write_text(json.dumps({'url': self.server.origin, 'token': self.server.token}), encoding='utf-8')
        self.service = OcService(self.root / 'oc')
        self.sequence = 0

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.execution.shutdown()
        self.temp.cleanup()

    def package(self, script=None, version='1.0.0'):
        self.sequence += 1
        project = self.root / f'project-{self.sequence}'
        project.mkdir()
        (project / 'main.py').write_text(script or 'from wbot import runtime\nprint("已执行")\nruntime.set_result(runtime.parameters())', encoding='utf-8')
        (project / 'wbot.json').write_text(json.dumps({'schemaVersion': 1, 'name': 'demo', 'version': version,
            'entry': 'main.py', 'files': ['main.py'], 'parameters': {'name': {'type': 'string', 'default': '默认'}},
            'requirements': {}}), encoding='utf-8')
        prepare_environment(project)
        self.execution.host_project(project)
        return self.service.import_package(build_package(project))

    def deploy(self, package=None):
        package = package or self.package()
        device = self.service.add_device('测试设备', str(self.assistant_dir))
        return self.service.create_process({'name': '问候流程', 'description': '真实执行', 'package_id': package['id'],
            'device_id': device['id'], 'defaults': {'name': '部署默认'}})

    def test_queue_runs_without_browser_and_drains_with_real_assistant(self):
        from app.oc.server import create_server as create_oc_server
        process = self.deploy()
        jobs = [self.service.queue.enqueue(process['id'], {'request_id': f'queued-{index}',
                    'parameters': {'name': f'队列参数 {index}'}}) for index in range(3)]
        web = self.root / 'web'
        web.mkdir()
        (web / 'index.html').write_text('<html>OC</html>', encoding='utf-8')
        admin = create_oc_server(self.service, web, 0)
        thread = threading.Thread(target=admin.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        thread.start()
        try:
            for index, job in enumerate(jobs):
                completed = self.finished(job['id'])
                self.assertEqual(completed['state'], 'succeeded', completed)
                self.assertEqual(completed['result'], {'name': f'队列参数 {index}'})
                self.assertIn('已执行', self.service.read_log(job['id'])['log'])
            self.assertEqual(len(self.execution.list_jobs()), 3)
        finally:
            admin.shutdown()
            admin.server_close()
            thread.join(timeout=3)

    def finished(self, job_id):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            job = self.service.get_job(job_id)
            if job['state'] in ('succeeded', 'failed', 'stopped', 'interrupted'):
                return job
            time.sleep(.03)
        self.fail(f'作业未结束：{job}')

    def test_real_deployment_run_and_terminal_history_survive_restart_and_device_offline(self):
        process = self.deploy()
        job = self.service.run_process(process['id'], {}, 'request-1')
        done = self.finished(job['id'])
        self.assertEqual(done['state'], 'succeeded', done)
        self.assertEqual(done['result'], {'name': '部署默认'})
        self.assertEqual(done['assistant_job_id'], self.execution.list_jobs()[0]['id'])
        self.assertIn('已执行', self.service.read_log(job['id'])['log'])
        self.metadata.unlink()
        restored = OcService(self.root / 'oc')
        self.assertEqual(restored.get_job(job['id'])['result'], {'name': '部署默认'})
        self.assertTrue(restored.read_log(job['id'])['cached'])
        self.assertEqual(restored.snapshot()['devices'][0]['status'], 'offline')

    def test_repeated_request_preserves_original_snapshot_after_deployment_edit(self):
        process = self.deploy()
        first = self.service.run_process(process['id'], {'name': '原参数'}, 'same-request')
        self.finished(first['id'])
        second_package = self.package(version='2.0.0')
        self.service.update_process(process['id'], {'name': '改名', 'package_id': second_package['id'], 'defaults': {'name': '新默认'}})
        repeated = self.service.run_process(process['id'], {'name': '原参数'}, 'same-request')
        self.assertEqual(repeated['id'], first['id'])
        self.assertEqual(repeated['package_id'], 'demo@1.0.0')
        self.assertEqual(repeated['process_name'], '问候流程')
        with self.assertRaises(ValueError):
            self.service.run_process(process['id'], {'name': '不同'}, 'same-request')
        self.assertEqual(len(self.execution.list_jobs()), 1)

    def test_package_versions_are_immutable_and_tampering_is_rejected(self):
        self.package('print("original")')
        with self.assertRaises(ValueError):
            self.package('print("different")')
        self.assertEqual(len(self.service.list_packages()), 1)
        archive = next((self.root / 'oc' / 'packages').glob('*.zip'))
        archive.write_bytes(b'not a package')
        process = self.deploy(self.service.list_packages()[0])
        job = self.service.run_process(process['id'], {}, 'tampered')
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(self.execution.list_jobs(), [])

    def test_invalid_defaults_disabled_and_maintenance_never_dispatch(self):
        process = self.deploy()
        with self.assertRaises(ValueError):
            self.service.update_process(process['id'], {'defaults': {'unknown': 'bad'}})
        with self.assertRaises(ValueError):
            self.service.run_process(process['id'], {'name': 3}, 'wrong-type')
        self.service.update_process(process['id'], {'enabled': False})
        with self.assertRaises(RuntimeError):
            self.service.run_process(process['id'], {}, 'disabled')
        self.service.update_process(process['id'], {'enabled': True})
        self.service.update_device(process['device_id'], True)
        with self.assertRaises(RuntimeError):
            self.service.run_process(process['id'], {}, 'maintenance')
        self.assertEqual(self.service.list_jobs(), [])
        self.assertEqual(self.execution.list_jobs(), [])

    def test_offline_device_busy_and_stop_use_real_assistant(self):
        process = self.deploy(self.package('import time\nprint("started", flush=True)\ntime.sleep(30)'))
        self.metadata.rename(self.metadata.with_suffix('.offline'))
        with self.assertRaises(RuntimeError):
            self.service.run_process(process['id'], {}, 'offline')
        self.metadata.with_suffix('.offline').rename(self.metadata)
        job = self.service.run_process(process['id'], {}, 'long-job')
        with self.assertRaises(RuntimeError):
            self.service.run_process(process['id'], {}, 'busy')
        stopped = self.service.stop_job(job['id'])
        self.assertEqual(stopped['state'], 'stopped', stopped)

    def test_uncertain_submit_is_reconciled_without_second_execution(self):
        process = self.deploy()
        from app.oc.client import AssistantClient
        original = AssistantClient.request

        def lost_response(client, endpoint, body=None):
            result = original(client, endpoint, body)
            if endpoint == '/api/jobs' and body is not None:
                raise OSError('模拟已提交但响应丢失')
            return result

        with patch.object(AssistantClient, 'request', lost_response):
            job = self.service.run_process(process['id'], {}, 'lost-response')
        self.assertEqual(job['state'], 'unknown')
        restored = OcService(self.root / 'oc')
        done = self.finished(job['id'])
        self.assertEqual(done['state'], 'succeeded')
        self.assertEqual(restored.run_process(process['id'], {}, 'lost-response')['id'], job['id'])
        self.assertEqual(len(self.execution.list_jobs()), 1)

    def test_device_metadata_and_tokens_never_leak_to_catalog(self):
        device = self.service.add_device('设备', str(self.assistant_dir))
        self.assertEqual(device['status'], 'online')
        self.assertNotIn(self.server.token, json.dumps(self.service.snapshot()))
        with self.assertRaises(ValueError):
            self.service.add_device('重复', str(self.assistant_dir))
        with self.assertRaises(ValueError):
            self.service.add_device('相对路径', 'relative')

    def test_terminal_log_fetch_failure_does_not_freeze_partial_log_cache(self):
        process = self.deploy(self.package('import time\nfrom pathlib import Path\nprint("first", flush=True)\n'
            'while not Path("release").exists(): time.sleep(.01)\nprint("last", flush=True)'))
        job = self.service.run_process(process['id'], {}, 'partial-log')
        deadline = time.monotonic() + 10
        while 'first' not in self.service.read_log(job['id'])['log']:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.02)
        (self.execution.jobs_dir / job['assistant_job_id'] / 'work' / 'release').touch()
        while self.execution.get_job(job['assistant_job_id'])['state'] not in ('succeeded', 'failed'):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.02)
        from app.oc.client import AssistantClient
        original = AssistantClient.request

        def lost_log(client, endpoint, body=None):
            if endpoint.endswith('/log'):
                raise OSError('日志连接暂时断开')
            return original(client, endpoint, body)

        with patch.object(AssistantClient, 'request', lost_log):
            completed = self.service.get_job(job['id'])
        self.assertEqual(completed['state'], 'succeeded')
        self.assertTrue(completed['sync_error'])
        self.assertIn('last', self.service.read_log(job['id'])['log'])
        self.assertEqual(self.service.get_job(job['id'])['sync_error'], '')

    def test_unconfirmed_dispatch_is_never_replayed_on_restart(self):
        process = self.deploy()
        from app.oc.client import AssistantClient
        original = AssistantClient.request

        def unaccepted(client, endpoint, body=None):
            if endpoint == '/api/jobs' and body is not None:
                raise OSError('提交连接中断')
            return original(client, endpoint, body)

        with patch.object(AssistantClient, 'request', unaccepted):
            job = self.service.run_process(process['id'], {}, 'not-accepted')
        restored = OcService(self.root / 'oc')
        self.assertEqual(restored.get_job(job['id'])['state'], 'unknown')
        self.assertEqual(restored.run_process(process['id'], {}, 'not-accepted')['id'], job['id'])
        self.assertEqual(self.execution.list_jobs(), [])


if __name__ == '__main__':
    unittest.main()
