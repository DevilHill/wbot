"""用真实 HTTP、SQLite 与任务进程验证跨端绑定和执行。"""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app.automation_package import create_project, build_package
from app.assistant.connection import ConnectionService
from app.assistant.execution import ExecutionService
from app.assistant.remote_client import GatewayClient, GatewayError
from app.oc.agent_server import create_agent_server
from app.oc.service import OcService
from tests.flow_environment import prepare_environment


class AssistantOcIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.execution = ExecutionService(self.root / 'assistant')
        self.connection = ConnectionService(self.root / 'assistant', self.execution)
        self.oc = OcService(self.root / 'oc')
        self.gateway = create_agent_server(self.oc, port=0)
        self.thread = threading.Thread(target=self.gateway.serve_forever, daemon=True)
        self.thread.start()
        self.settings = self.connection.connect(self.gateway.origin, '集成测试设备')
        self.device_id = self.settings['device_id']

    def tearDown(self):
        self.connection.close()
        self.execution.shutdown()
        self.gateway.shutdown()
        self.gateway.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def approve(self):
        self.connection.synchronize()
        self.assertEqual(self.connection.snapshot()['binding_state'], 'pending')
        self.oc.agents.decide(self.device_id, 'approve')
        self.connection.synchronize()
        self.assertEqual(self.connection.snapshot()['binding_state'], 'approved')

    def dispatch(self, script=None):
        project = self.root / 'project'
        create_project(project, 'remote-example')
        if script is not None:
            (project / 'main.py').write_text(script, encoding='utf-8')
            prepare_environment(project)
            self.execution.host_project(project)
        package = self.oc.import_package(build_package(project))
        process = self.oc.create_process({'name': '远程示例', 'package_id': package['id'],
                                          'device_id': self.device_id, 'defaults': {}, 'enabled': True})
        return self.oc.run_process(process['id'], {'name': '远程助手'}, 'integration-run')

    def wait_local(self, expected):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            jobs = self.execution.list_jobs()
            if jobs and jobs[0]['state'] == expected:
                return jobs[0]
            time.sleep(.02)
        self.fail(f'本机任务未到达 {expected}: {self.execution.list_jobs()}')

    def test_approval_download_execution_and_restart_report_do_not_repeat_job(self):
        self.approve()
        remote = self.dispatch('from wbot import runtime\nprint("remote-success")\n'
                               'runtime.set_result({"name": runtime.parameters()["name"]})\n')
        self.connection.synchronize()
        local = self.wait_local('succeeded')
        self.connection.close()
        self.connection = ConnectionService(self.root / 'assistant', self.execution)
        self.connection.synchronize()
        self.connection.synchronize()
        observed = self.oc.get_job(remote['id'])
        self.assertEqual(observed['state'], 'succeeded')
        self.assertEqual(observed['assistant_job_id'], local['id'])
        self.assertEqual(observed['result'], {'name': '远程助手'})
        self.assertIn('remote-success', self.oc.read_log(remote['id'])['log'])
        self.assertEqual(len(self.execution.list_jobs()), 1)
        self.assertNotIn('_secret_hash', str(self.oc.snapshot()))

    def test_lost_report_response_replays_persisted_sequence(self):
        self.approve()
        remote = self.dispatch('print("once")\n')
        self.connection.synchronize()
        self.wait_local('succeeded')
        original = GatewayClient.request
        def lose_ack(client, endpoint, body=None):
            response = original(client, endpoint, body)
            if endpoint.endswith('/report'):
                raise GatewayError('模拟响应丢失')
            return response
        with patch.object(GatewayClient, 'request', lose_ack), self.assertRaises(GatewayError):
            self.connection.synchronize()
        pending = self.connection.store.unfinished_job(self.device_id)
        self.assertIsNotNone(pending['pending_report'])
        self.connection.synchronize()
        self.assertIsNone(self.connection.store.unfinished_job(self.device_id))
        self.assertEqual(self.oc.get_job(remote['id'])['state'], 'succeeded')
        self.assertEqual(len(self.execution.list_jobs()), 1)

    def test_revocation_blocks_download_and_reports_failure_without_execution(self):
        self.approve()
        remote = self.dispatch()
        original = GatewayClient.download
        def revoke_before_download(client, command, destination, stop):
            self.oc.agents.decide(self.device_id, 'revoke')
            return original(client, command, destination, stop)
        with patch.object(GatewayClient, 'download', revoke_before_download):
            self.connection.synchronize()
        self.connection.synchronize()
        self.assertEqual(self.execution.list_jobs(), [])
        self.assertEqual(self.oc.get_job(remote['id'])['state'], 'failed')
        self.assertEqual(self.connection.snapshot()['binding_state'], 'revoked')

    def test_remote_stop_only_targets_the_claimed_job(self):
        self.approve()
        remote = self.dispatch('import time\nprint("started", flush=True)\ntime.sleep(30)\n')
        self.connection.synchronize()
        self.wait_local('running')
        self.connection.synchronize()
        self.oc.stop_job(remote['id'])
        self.connection.synchronize()
        self.wait_local('stopped')
        self.connection.synchronize()
        self.assertEqual(self.oc.get_job(remote['id'])['state'], 'stopped')

    def test_corrupt_download_hash_prevents_install_and_execution(self):
        self.approve()
        remote = self.dispatch()
        original = GatewayClient.download
        def corrupt_expected_hash(client, command, destination, stop):
            return original(client, dict(command, package_sha256='0' * 64), destination, stop)
        with patch.object(GatewayClient, 'download', corrupt_expected_hash):
            self.connection.synchronize()
        self.connection.synchronize()
        self.assertEqual(self.execution.list_jobs(), [])
        self.assertEqual(self.execution.list_packages(), [])
        self.assertEqual(self.oc.get_job(remote['id'])['state'], 'failed')
        self.assertIn('校验失败', self.oc.get_job(remote['id'])['error'])

    def test_restart_after_submit_before_journal_save_reattaches_existing_job(self):
        self.approve()
        remote = self.dispatch('print("executed-once")\n')
        original = self.connection.store.save_job
        def lose_local_ack(journal):
            if journal['assistant_job_id']:
                raise OSError('模拟提交后断电，连接日志尚未保存')
            return original(journal)
        with patch.object(self.connection.store, 'save_job', lose_local_ack), self.assertRaises(OSError):
            self.connection.synchronize()
        local = self.wait_local('succeeded')
        self.connection.close()
        self.connection = ConnectionService(self.root / 'assistant', self.execution)
        self.connection.synchronize()
        self.connection.synchronize()
        self.assertEqual(self.oc.get_job(remote['id'])['state'], 'succeeded')
        self.assertEqual(self.oc.get_job(remote['id'])['assistant_job_id'], local['id'])
        self.assertEqual(len(self.execution.list_jobs()), 1)

    def test_cancel_before_execution_reports_stopped(self):
        self.approve()
        remote = self.dispatch()
        with patch.object(self.connection, '_execute'):
            self.connection.synchronize()
        self.oc.stop_job(remote['id'])
        self.connection.synchronize()
        self.connection.synchronize()
        self.assertEqual(self.execution.list_jobs(), [])
        self.assertEqual(self.oc.get_job(remote['id'])['state'], 'stopped')

    def test_rebinding_after_revocation_still_reports_finished_old_task(self):
        self.approve()
        remote = self.dispatch('print("finished-before-rebind")\n')
        self.connection.synchronize()
        self.wait_local('succeeded')
        self.oc.agents.decide(self.device_id, 'revoke')
        settings = self.connection.store.settings()
        settings['binding_state'] = 'revoked'
        self.connection.store.save_settings(settings)
        renewed = self.connection.connect(self.gateway.origin, '集成测试设备')
        self.assertNotEqual(renewed['device_id'], self.device_id)
        self.connection.synchronize()
        self.assertEqual(self.oc.get_job(remote['id'])['state'], 'succeeded')
        self.assertEqual(self.connection.snapshot()['pending_reports'], 0)


if __name__ == '__main__':
    unittest.main()
