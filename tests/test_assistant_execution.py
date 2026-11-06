"""通过真实子进程验证包执行、作业持久化和进程树所有权。"""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from app.automation_package import build_package
from app.assistant.execution import ExecutionService


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.service = ExecutionService(self.state, python_executable=sys.executable)
        self.sequence = 0

    def tearDown(self):
        self.service.shutdown()
        self.temp.cleanup()

    def package(self, script, *, name='demo', version='1.0.0', parameters=None, requirements=None, extra=None, elements=None):
        self.sequence += 1
        project = self.root / f'project-{self.sequence}'
        project.mkdir()
        (project / 'main.py').write_text(script, encoding='utf-8')
        files = ['main.py']
        for filename, content in (extra or {}).items():
            (project / filename).write_text(content, encoding='utf-8')
            files.append(filename)
        manifest = {'schemaVersion': 1, 'name': name, 'version': version, 'entry': 'main.py',
                    'files': files, 'parameters': parameters or {}, 'requirements': requirements or {}}
        if elements:
            manifest['elements'] = elements
        (project / 'wbot.json').write_text(json.dumps(manifest), encoding='utf-8')
        return build_package(project, self.root / f'package-{self.sequence}.wbot.zip')

    def finished(self, job_id, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.service.get_job(job_id)
            if job['state'] not in ('preparing', 'running', 'stopping'):
                return job
            time.sleep(.02)
        self.fail(f'Job did not finish: {job}')

    def wait_for_log(self, job_id, marker):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if marker in self.service.read_log(job_id):
                return
            time.sleep(.02)
        self.fail(f'Worker did not print {marker}: {self.service.read_log(job_id)}')

    def test_success_parameters_result_and_private_working_directory(self):
        archive = self.package('from wbot import runtime\nfrom pathlib import Path\n'
            'print("你好", flush=True)\nPath("created.txt").write_text("local")\n'
            'runtime.set_result({"name": runtime.parameters()["name"], "job": runtime.job_id()})',
            parameters={'name': {'type': 'string', 'default': '示例'}},
            extra={'app.py': 'raise RuntimeError("must not shadow worker")'})
        package = self.service.install_package(archive)
        job = self.service.submit(package['id'], {})
        self.assertEqual(job['state'], 'preparing')
        result = self.finished(job['id'])
        self.assertEqual(result['state'], 'succeeded', result)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['result'], {'name': '示例', 'job': job['id']})
        self.assertIn('你好', self.service.read_log(job['id']))
        self.assertFalse((self.root / 'project-1' / 'created.txt').exists())
        self.assertFalse((self.state / 'packages' / package['id'] / 'created.txt').exists())

    def test_versions_are_immutable_and_invalid_parameters_do_not_create_jobs(self):
        archive = self.package('print("one")', parameters={'count': {'type': 'integer', 'required': True}})
        package = self.service.install_package(archive)
        self.assertEqual(self.service.install_package(archive), package)
        with self.assertRaises(ValueError):
            self.service.install_package(self.package('print("changed")'))
        with self.assertRaises(ValueError):
            self.service.submit(package['id'], {'count': True})
        self.assertEqual(self.service.list_jobs(), [])

    def test_job_summary_bounds_history_and_omits_large_payloads(self):
        with closing(sqlite3.connect(self.state / 'assistant.sqlite3')) as database:
            database.executemany('''INSERT INTO jobs
                (id, package_id, payload_hash, parameters, state, created_at, result)
                VALUES (?, 'demo@1.0.0', '', '{}', 'succeeded', ?, ?)''',
                [(f'job-{index}', index, json.dumps('x' * 131072)) for index in range(205)])
            database.execute("UPDATE jobs SET state='running' WHERE id='job-0'")
            database.commit()
        summary = self.service.job_summary()
        self.assertEqual(summary['total'], 205)
        self.assertEqual(len(summary['items']), 200)
        self.assertEqual(summary['items'][0]['id'], 'job-0')
        self.assertEqual(summary['items'][1]['id'], 'job-204')
        self.assertNotIn('result', summary['items'][0])
        self.assertNotIn('parameters', summary['items'][0])
        self.assertLess(len(json.dumps(summary)), 100000)
        self.assertEqual(len(self.service.get_job('job-204')['result']), 131072)

    def test_request_id_is_idempotent_but_different_payload_is_rejected(self):
        package = self.service.install_package(self.package('print("done")',
            parameters={'count': {'type': 'integer', 'default': 1}}))
        first = self.service.submit(package['id'], {}, 'request-1')
        self.assertEqual(self.service.submit(package['id'], {'count': 1}, 'request-1')['id'], first['id'])
        with self.assertRaises(ValueError):
            self.service.submit(package['id'], {'count': 2}, 'request-1')
        self.finished(first['id'])
        self.service.shutdown()
        self.service = ExecutionService(self.state)
        self.assertEqual(self.service.submit(package['id'], {}, 'request-1')['id'], first['id'])
        self.assertEqual(len(self.service.list_jobs()), 1)

    def test_busy_and_stop_are_explicit(self):
        package = self.service.install_package(self.package('import time\nprint("ready", flush=True)\ntime.sleep(60)'))
        job = self.service.submit(package['id'], {})
        self.wait_for_log(job['id'], 'ready')
        with self.assertRaisesRegex(ValueError, '忙|运行'):
            self.service.submit(package['id'], {})
        self.service.stop_job(job['id'])
        result = self.finished(job['id'])
        self.assertEqual(result['state'], 'stopped')
        self.assertIsNotNone(result['exit_code'])

    def test_worker_error_and_missing_requirement_are_different_failures(self):
        package = self.service.install_package(self.package('raise RuntimeError("业务错误")'))
        job = self.finished(self.service.submit(package['id'], {})['id'])
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(job['exit_code'], 1)
        self.assertIn('业务错误', self.service.read_log(job['id']))
        package = self.service.install_package(self.package('print("MUST NOT RUN")', version='2.0.0',
            requirements={'wbot-test-missing-distribution': '1.0.0'}))
        job = self.finished(self.service.submit(package['id'], {})['id'])
        self.assertEqual(job['state'], 'failed')
        self.assertIn('依赖', job['error'])
        self.assertNotIn('MUST NOT RUN', self.service.read_log(job['id']))
        package = self.service.install_package(self.package('print("MUST NOT RUN")', version='3.0.0',
            requirements={'lxml': '0.0.0'}))
        job = self.finished(self.service.submit(package['id'], {})['id'])
        self.assertEqual(job['state'], 'failed')
        self.assertIn('installed', job['error'])
        self.assertIsNone(job['exit_code'])

    def test_logs_are_bounded_without_blocking_process_completion(self):
        package = self.service.install_package(self.package('print("x" * (5 * 1024 * 1024))'))
        job = self.finished(self.service.submit(package['id'], {})['id'])
        self.assertEqual(job['state'], 'succeeded')
        self.assertTrue(job['log_truncated'])
        self.assertLessEqual(len(self.service.read_log(job['id']).encode('utf-8')), 4 * 1024 * 1024)

    def test_stop_owns_descendants_but_not_unrelated_processes(self):
        heartbeat = self.root / 'child-heartbeat.txt'
        child = ('from pathlib import Path\nimport time\n'
                 f'file = Path({str(heartbeat)!r})\n'
                 'while True:\n file.write_text(str(time.monotonic()))\n time.sleep(.02)')
        script = ('import subprocess, sys, time\n'
                  f'subprocess.Popen([sys.executable, "-c", {child!r}])\n'
                  'print("spawned", flush=True)\ntime.sleep(60)')
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            package = self.service.install_package(self.package(script))
            job = self.service.submit(package['id'], {})
            self.wait_for_log(job['id'], 'spawned')
            deadline = time.monotonic() + 5
            while not heartbeat.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(heartbeat.exists())
            self.service.stop_job(job['id'])
            first = heartbeat.read_text()
            time.sleep(.15)
            self.assertEqual(heartbeat.read_text(), first)
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    def test_invalid_output_and_modified_installed_package_fail_explicitly(self):
        package = self.service.install_package(self.package('import os\nfrom pathlib import Path\n'
            'Path(os.environ["WBOT_RUN_RESULT"]).write_text("[]")'))
        job = self.finished(self.service.submit(package['id'], {})['id'])
        self.assertEqual(job['state'], 'failed')
        self.assertIn('结果', job['error'])
        self.assertEqual(job['exit_code'], 0)
        (self.state / 'packages' / package['id'] / 'main.py').write_text('print("changed")')
        job = self.finished(self.service.submit(package['id'], {})['id'])
        self.assertEqual(job['state'], 'failed')
        self.assertIn('内容发生变化', job['error'])
        self.assertIsNone(job['exit_code'])

    def test_unlisted_files_cannot_change_installed_package_imports(self):
        package = self.service.install_package(self.package('print("unchanged")'))
        (self.state / 'packages' / package['id'] / 'extra.py').write_text('print("added")')
        job = self.finished(self.service.submit(package['id'], {})['id'])
        self.assertEqual(job['state'], 'failed')
        self.assertIsNone(job['exit_code'])

    def test_package_elements_are_imported_into_job_private_library(self):
        elements = {'format': 'wbot-elements', 'version': 1, 'items': [
            {'name': '登录', 'group': '页面', 'xpath': '//button', 'description': '', 'url': ''}]}
        package = self.service.install_package(self.package('from wbot import runtime, ElementLibrary\n'
            'runtime.set_result({"count": len(ElementLibrary().list())})',
            extra={'elements.json': json.dumps(elements)}, elements='elements.json'))
        job = self.finished(self.service.submit(package['id'], {})['id'])
        self.assertEqual(job['state'], 'succeeded', job)
        self.assertEqual(job['result'], {'count': 1})

    def test_history_survives_restart_and_unfinished_jobs_are_not_replayed(self):
        package = self.service.install_package(self.package('print("once")'))
        job = self.finished(self.service.submit(package['id'], {})['id'])
        self.service.shutdown()
        with closing(sqlite3.connect(self.state / 'assistant.sqlite3')) as database:
            with database:
                database.execute("UPDATE jobs SET state='running' WHERE id=?", (job['id'],))
        self.service = ExecutionService(self.state)
        recovered = self.service.get_job(job['id'])
        self.assertEqual(recovered['state'], 'interrupted')
        self.assertEqual(len(self.service.list_packages()), 1)
        self.assertEqual(self.service.read_log(job['id']).count('once'), 1)


if __name__ == '__main__':
    unittest.main()
