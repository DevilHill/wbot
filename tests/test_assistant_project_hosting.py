import json
import importlib.metadata
import sqlite3
from contextlib import closing
from pathlib import Path
import tempfile
import time
import unittest
import venv

from app.automation_package import create_project, build_package
from app.assistant.execution import ExecutionService
from tests.flow_environment import prepare_environment


class ProjectHostingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / 'project'
        create_project(self.project, 'hosted-flow')
        self.execution = ExecutionService(self.root / 'assistant')

    def tearDown(self):
        self.execution.shutdown()
        self.temporary.cleanup()

    def finished(self, package_id):
        job = self.execution.submit(package_id, {})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = self.execution.get_job(job['id'])
            if job['state'] not in ('preparing', 'running', 'stopping'):
                return job
            time.sleep(.02)
        self.fail(str(job))

    def test_registration_and_restart_use_flow_interpreter_and_own_sdk(self):
        prepare_environment(self.project)
        manifest_path = self.project / 'wbot.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['requirements'] = {'wbot': importlib.metadata.version('wbot')}
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        (self.project / 'main.py').write_text(
            'import sys,wbot\nfrom wbot import runtime\n'
            'runtime.set_result({"python":sys.executable,"sdk":wbot.__file__,"paths":sys.path})\n', encoding='utf-8')
        package = self.execution.host_project(self.project)
        self.execution.shutdown()
        self.execution = ExecutionService(self.root / 'assistant')
        job = self.finished(package['id'])
        self.assertEqual(job['state'], 'succeeded', job)
        environment = self.project / '.venv'
        self.assertTrue(Path(job['result']['python']).is_relative_to(environment))
        self.assertTrue(Path(job['result']['sdk']).is_relative_to(environment))
        self.assertNotIn(str(Path(__file__).resolve().parents[1]), job['result']['paths'])

    def test_missing_or_removed_environment_never_falls_back_to_host(self):
        with self.assertRaisesRegex(ValueError, '虚拟环境'):
            self.execution.host_project(self.project)
        self.assertEqual(self.execution.list_packages(), [])
        prepare_environment(self.project)
        package = self.execution.host_project(self.project)
        (self.project / '.venv/pyvenv.cfg').unlink()
        job = self.finished(package['id'])
        self.assertEqual(job['state'], 'failed')
        self.assertIn('虚拟环境', job['error'])
        self.assertIsNone(job['exit_code'])

    def test_legacy_archive_is_visible_but_cannot_run_without_project_environment(self):
        package = self.execution.install_package(build_package(self.project))
        job = self.finished(package['id'])
        self.assertEqual(job['state'], 'failed')
        self.assertIn('登记', job['error'])
        prepare_environment(self.project)
        self.execution.host_project(self.project)
        self.assertEqual(self.finished(package['id'])['state'], 'succeeded')

    def test_standard_library_flow_does_not_need_or_inherit_assistant_sdk(self):
        venv.EnvBuilder(with_pip=False, symlinks=False).create(self.project / '.venv')
        (self.project / 'main.py').write_text(
            'import importlib.util, json, os\nfrom pathlib import Path\n'
            'assert importlib.util.find_spec("wbot") is None\n'
            'context=json.loads(Path(os.environ["WBOT_RUN_INPUT"]).read_text())\n'
            'Path(os.environ["WBOT_RUN_RESULT"]).write_text(json.dumps(context["parameters"]))\n', encoding='utf-8')
        package = self.execution.host_project(self.project)
        job = self.finished(package['id'])
        self.assertEqual(job['state'], 'succeeded', job)
        self.assertEqual(job['result'], {'name': 'WBot'})

    def test_shared_site_packages_and_another_flow_environment_are_rejected(self):
        prepare_environment(self.project)
        configuration = self.project / '.venv/pyvenv.cfg'
        configuration.write_text(configuration.read_text().replace('false', 'true'))
        with self.assertRaisesRegex(ValueError, '隔离'):
            self.execution.host_project(self.project)
        configuration.write_text(configuration.read_text().replace('true', 'false'))
        self.execution.host_project(self.project)
        manifest = json.loads((self.project / 'wbot.json').read_text(encoding='utf-8'))
        manifest['version'] = '0.2.0'
        (self.project / 'wbot.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, '环境.*版本|版本.*环境'):
            self.execution.host_project(self.project)

    def test_environment_bindings_preserve_old_package_table_for_rollback(self):
        with closing(sqlite3.connect(self.execution.store.path)) as database:
            with database:
                database.execute('INSERT INTO packages VALUES (?, ?, ?)',
                    ('legacy@0.1.0', (self.project / 'wbot.json').read_text(encoding='utf-8'), 'legacy-fingerprint'))
        self.assertEqual(self.execution.store.package('legacy@0.1.0')['project_path'], '')


if __name__ == '__main__':
    unittest.main()
