"""A prebuilt flow survives relocation, HTTP deployment and source removal."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

from app.automation_package import create_project, inspect_package, extract_package
from app.assistant.execution import ExecutionService
from app.assistant.connection import ConnectionService
from app.oc.agent_server import create_agent_server
from app.oc.service import OcService
from tests.flow_environment import prepare_environment


@unittest.skipUnless(os.name == 'nt', 'Windows x64 portable distribution')
class PortableFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='wbot-portable-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        project = cls.root / '开发项目'
        create_project(project, 'portable-demo')
        prepare_environment(project)
        (project / 'main.py').write_text(
            'import sys, wbot, lxml.etree, sqlite3, ssl\nfrom wbot import runtime\n'
            'runtime.set_result({"python":sys.executable,"sdk":wbot.__file__,"paths":sys.path,'
            '"value":lxml.etree.fromstring(b"<x>portable</x>").text})\n', encoding='utf-8')
        cls.archive = cls.root / 'flow.wbot.zip'
        command = [str(project / '.venv/Scripts/python.exe'), '-X', 'utf8',
                   str(Path(__file__).resolve().parents[1] / 'app/automation_package.py'),
                   'build', str(project), '--with-runtime', '--output', str(cls.archive)]
        built = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=120)
        if built.returncode:
            raise AssertionError(built.stderr)
        cls.manifest = json.loads(built.stdout)['manifest']
        # No task can fall back to the original environment after this rename.
        project.rename(cls.root / 'unavailable-source')

    def setUp(self):
        self.case = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.case.cleanup)
        self.destination = Path(self.case.name)
        self.execution = ExecutionService(self.destination / '目标电脑')
        self.addCleanup(self.execution.shutdown)

    def finished(self, identifier):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = self.execution.get_job(identifier)
            if job['state'] not in ('preparing', 'running', 'stopping'):
                return job
            time.sleep(.02)
        self.fail(str(job))

    def test_offline_deployment_uses_only_shipped_python_and_dependencies(self):
        self.assertEqual(inspect_package(self.archive)['schemaVersion'], 2)
        with patch('venv.EnvBuilder.create', side_effect=AssertionError('Assistant must not create environments')):
            package = self.execution.install_package(self.archive)
            job = self.finished(self.execution.submit(package['id'], {})['id'])
        self.assertEqual(job['state'], 'succeeded', job)
        deployed = self.execution.packages_dir / package['id'] / '_runtime'
        self.assertEqual(Path(job['result']['python']), deployed / 'python.exe')
        self.assertTrue(Path(job['result']['sdk']).is_relative_to(deployed))
        self.assertEqual(job['result']['value'], 'portable')
        self.assertFalse((self.execution.jobs_dir / job['id'] / 'work/_runtime').exists())
        self.assertFalse(any('unavailable-source' in path or '开发项目' in path for path in job['result']['paths']))
        # Immutable version redeployment is idempotent; altered runtime cannot execute.
        self.assertEqual(self.execution.install_package(self.archive)['id'], package['id'])
        with (deployed / 'Lib/site.py').open('a', encoding='utf-8') as output:
            output.write('\n# modified\n')
        failed = self.finished(self.execution.submit(package['id'], {})['id'])
        self.assertEqual(failed['state'], 'failed')
        self.assertIn('内容发生变化', failed['error'])
        self.assertIsNone(failed['exit_code'])

    def test_oc_transfers_and_deploys_to_an_empty_assistant(self):
        oc = OcService(self.destination / 'oc')
        self.addCleanup(oc.close)
        gateway = create_agent_server(oc, port=0)
        thread = threading.Thread(target=gateway.serve_forever, daemon=True)
        thread.start()
        def close_gateway():
            gateway.shutdown()
            gateway.server_close()
            thread.join(2)
        self.addCleanup(close_gateway)
        connection = ConnectionService(self.execution.state_dir, self.execution)
        self.addCleanup(connection.close)
        settings = connection.connect(gateway.origin, '空白执行电脑')
        connection.synchronize()
        oc.agents.decide(settings['device_id'], 'approve')
        connection.synchronize()
        package = oc.import_package(self.archive)
        process = oc.create_process({'name': '可移植流程', 'package_id': package['id'],
            'device_id': settings['device_id'], 'defaults': {}, 'enabled': True})
        remote = oc.run_process(process['id'], {}, 'portable-test')
        self.assertEqual(self.execution.list_packages(), [])
        connection.synchronize()
        self.assertEqual(len(self.execution.list_jobs()), 1, connection.snapshot())
        local = self.finished(self.execution.list_jobs()[0]['id'])
        self.assertEqual(local['state'], 'succeeded', local)
        connection.synchronize()
        self.assertEqual(oc.get_job(remote['id'])['state'], 'succeeded')
        self.assertEqual(oc.get_job(remote['id'])['result']['value'], 'portable')

    def test_corruption_is_rejected_without_leaving_a_deployment(self):
        damaged = self.destination / 'damaged.zip'
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(damaged, 'w', zipfile.ZIP_DEFLATED) as target:
            for member in source.infolist():
                target.writestr(member, b'corrupt' if member.filename == '_runtime/python.exe' else source.read(member))
        output = self.destination / 'deployment'
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            extract_package(damaged, output)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.destination.glob('.deploy-*')), [])

    @unittest.skipUnless(os.environ.get('WBOT_PORTABLE_ASSISTANT'), '未指定已构建的 Assistant 目录')
    def test_packaged_assistant_hosts_the_transferred_environment(self):
        executable = Path(os.environ['WBOT_PORTABLE_ASSISTANT']) / 'python/python.exe'
        script = '''import json, sys, time
from app.assistant.execution import ExecutionService
service = ExecutionService(sys.argv[2])
try:
    package = service.install_package(sys.argv[1])
    job = service.submit(package['id'], {})
    deadline = time.monotonic() + 30
    while job['state'] in ('preparing', 'running', 'stopping') and time.monotonic() < deadline:
        time.sleep(.02)
        job = service.get_job(job['id'])
    assert job['state'] == 'succeeded', job
    print(json.dumps(job['result']))
finally:
    service.shutdown()
'''
        result = subprocess.run([str(executable), '-I', '-B', '-X', 'utf8', '-c', script,
            str(self.archive), str(self.destination / 'packaged-service')],
            capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed['value'], 'portable')
        self.assertTrue(Path(observed['python']).is_relative_to(self.destination / 'packaged-service/packages'))


if __name__ == '__main__':
    unittest.main()
