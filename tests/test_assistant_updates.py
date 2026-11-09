from pathlib import Path
import tempfile
import unittest

from app.assistant.connection import ConnectionService
from app.assistant.execution import ExecutionService
from app.assistant.updates import UpdateService, require_update_transport
from app.assistant.update_worker import swap_directories, restore_directories, validate_plan
from tests.test_assistant_releases import release_zip
from tests import test_oc_agent_server


class UpdateTests(unittest.TestCase):
    setUp = test_oc_agent_server.OcAgentServerTests.setUp
    tearDown = test_oc_agent_server.OcAgentServerTests.tearDown
    request = test_oc_agent_server.OcAgentServerTests.request
    enroll = test_oc_agent_server.OcAgentServerTests.enroll
    approve = test_oc_agent_server.OcAgentServerTests.approve

    def test_real_gateway_auth_publication_download_and_revocation(self):
        release = self.service.releases.upload(release_zip(self.root / 'release.zip'))
        identity, _ = self.enroll()
        route = '/api/agent/assistant-updates/'
        self.assertEqual(self.request(route + 'latest', {'version': '0.7.0'}, identity)[0], 403)
        self.approve(identity)
        self.assertIsNone(self.request(route + 'latest', {'version': '0.7.0'}, identity)[1]['release'])
        self.service.releases.publish(release['id'], {'published': True, 'device_ids': []})
        status, latest, _ = self.request(route + 'latest', {'version': '0.7.0'}, identity)
        self.assertEqual(status, 200)
        self.assertNotIn('_archive', latest['release'])
        self.assertEqual(self.request(route + '0.8.0/archive', credentials=identity)[0], 200)
        self.service.agents.decide(identity['device_id'], 'revoke')
        self.assertEqual(self.request(route + '0.8.0/archive', credentials=identity)[0], 403)

    def test_check_download_staging_tampering_and_withdrawn_install(self):
        execution = ExecutionService(self.root / 'assistant')
        connection = ConnectionService(execution.state_dir, execution)
        updates = UpdateService(execution, connection)
        try:
            connection.connect(self.gateway.origin, '更新设备')
            connection.synchronize()
            self.service.agents.decide(connection.store.settings()['device_id'], 'approve')
            connection.synchronize()
            self.service.releases.upload(release_zip(self.root / 'release.zip'))
            self.service.releases.publish('0.8.0', {'published': True, 'device_ids': []})
            updates.bundle = self.root / 'installed'
            (updates.bundle / 'python').mkdir(parents=True)
            (updates.bundle / 'python/python.exe').write_bytes(b'python')
            (updates.bundle / 'WBotAssistant.exe').write_bytes(b'old')
            updates.check()
            updates._thread.join(5)
            self.assertEqual(updates.snapshot()['status'], 'available')
            updates.download()
            updates._thread.join(5)
            self.assertEqual(updates.snapshot()['status'], 'ready', updates.snapshot())
            self.service.releases.publish('0.8.0', {'published': False, 'device_ids': []})
            with self.assertRaises(ConnectionError):
                updates.install(999999)
            self.assertFalse(execution.updating)
            self.service.releases.publish('0.8.0', {'published': True, 'device_ids': []})
            (updates._prepared / 'prepared/WBotAssistant/WBotAssistant.exe').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                updates.install(999999)
            self.assertEqual((updates.bundle / 'WBotAssistant.exe').read_bytes(), b'old')
        finally:
            updates.close()
            connection.close()
            execution.shutdown()

    def test_update_gate_blocks_jobs_and_requires_idle_and_correct_token(self):
        execution = ExecutionService(self.root / 'assistant')
        try:
            execution._active_id = 'existing-job'
            with self.assertRaises(RuntimeError):
                execution.begin_update('token')
            execution._active_id = None
            execution.begin_update('token')
            with self.assertRaises(RuntimeError):
                execution.submit('unused', {})
            with self.assertRaises(PermissionError):
                execution.resume_update('wrong')
            execution.resume_update('token')
            self.assertFalse(execution.updating)
        finally:
            execution.shutdown()

    def test_network_update_requires_tls_except_loopback(self):
        require_update_transport('http://127.0.0.1:8793')
        require_update_transport('https://oc.example.test')
        with self.assertRaises(ValueError):
            require_update_transport('http://192.168.1.2:8793')


class UpdateWorkerTests(unittest.TestCase):
    def test_directory_swap_and_rollback_preserve_old_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            install = root / 'Assistant'
            staged = root / '.wbot-update-test/prepared/WBotAssistant'
            backup = root / '.wbot-backup-test'
            for path, content in ((install, b'old'), (staged, b'new')):
                path.mkdir(parents=True)
                (path / 'WBotAssistant.exe').write_bytes(content)
            plan = dict(install=str(install), staged=str(staged), backup=str(backup),
                        work=str(root / '.wbot-update-test'), state_dir=str(root / 'data'))
            validate_plan(plan)
            swap_directories(install, staged, backup)
            self.assertEqual((install / 'WBotAssistant.exe').read_bytes(), b'new')
            restore_directories(install, staged, backup)
            self.assertEqual((install / 'WBotAssistant.exe').read_bytes(), b'old')
            with self.assertRaises(ValueError):
                validate_plan(dict(plan, state_dir=str(install / 'data')))

    def test_failed_second_rename_restores_original_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install, staged, backup = root / 'install', root / 'missing', root / 'backup'
            install.mkdir()
            (install / 'user-file').write_text('retained')
            with self.assertRaises(FileNotFoundError):
                swap_directories(install, staged, backup)
            self.assertEqual((install / 'user-file').read_text(), 'retained')
