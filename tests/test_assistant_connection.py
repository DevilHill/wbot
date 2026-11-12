"""连接设置、凭据边界与远程作业恢复。"""
import json
import http.client
from pathlib import Path
import tempfile
import threading
import unittest

from app.assistant.connection import ConnectionService, normalize_server_url
from app.assistant.execution import ExecutionService
from app.assistant.server import create_server


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.execution = ExecutionService(self.directory)
        self.connection = ConnectionService(self.directory, self.execution)

    def tearDown(self):
        self.connection.close()
        self.execution.shutdown()
        self.temporary.cleanup()

    def test_binding_key_retries_without_exposure_and_clears_after_enrollment(self):
        from unittest.mock import patch
        key = 'wbot_' + 'a' * 43
        snapshot = self.connection.connect('https://oc.example.com', '电脑', key)
        self.assertNotIn(key, json.dumps(snapshot))
        identity = snapshot['device_id']
        with patch('app.assistant.connection.GatewayClient') as gateway:
            client = gateway.return_value
            health = {'product': 'wbot-oc-agent', 'protocol_version': 1, 'binding_key_required': True}
            client.request.side_effect = [health, OSError('network interrupted')]
            with self.assertRaises(OSError):
                self.connection.synchronize()
            self.assertEqual(self.connection.store.settings()['binding_key'], key)
            self.assertEqual(self.connection.connect('https://oc.example.com', '电脑', key)['device_id'], identity)
            device = {'id': identity, 'binding_state': 'pending'}
            client.request.side_effect = [health, {'device': device}, {'device': device, 'job': None}]
            self.connection.synchronize()
            enrollment = client.request.call_args_list[-2]
            self.assertEqual(enrollment.args[0], '/api/v1/agent/enroll')
            self.assertEqual(enrollment.args[1]['binding_key'], key)
            self.assertNotIn('binding_key', self.connection.store.settings())
            self.assertNotIn(key, json.dumps(self.connection.snapshot()))

    def test_key_required_server_does_not_fall_back_to_legacy_enrollment(self):
        from unittest.mock import patch
        self.connection.connect('https://oc.example.com', '电脑')
        with patch('app.assistant.connection.GatewayClient') as gateway:
            gateway.return_value.request.return_value = {'product': 'wbot-oc-agent', 'protocol_version': 1, 'binding_key_required': True}
            with self.assertRaisesRegex(ValueError, '接入 Key'):
                self.connection.synchronize()
            gateway.return_value.request.assert_called_once_with('/api/agent/health')

    def test_url_is_normalized_and_rejects_credentials_and_ambiguous_paths(self):
        self.assertEqual(normalize_server_url(' HTTP://localhost:8793/ '), 'http://localhost:8793')
        self.assertEqual(normalize_server_url('https://oc.example.com'), 'https://oc.example.com')
        for value in ('file:///tmp', 'http://user:secret@host', 'http://host/path',
                      'http://host?token=secret', 'http://host#fragment', 'http://host:99999'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_server_url(value)

    def test_settings_persist_without_exposing_device_secret(self):
        settings = self.connection.connect('http://127.0.0.1:8793', '我的电脑')
        self.assertEqual(settings['binding_state'], 'connecting')
        self.assertNotIn('secret', json.dumps(settings))
        self.assertEqual(self.connection.connect('http://127.0.0.1:8793/', '我的电脑')['device_id'], settings['device_id'])
        restored = ConnectionService(self.directory, self.execution)
        self.assertEqual(restored.snapshot()['device_id'], settings['device_id'])
        self.assertEqual(restored.disconnect()['binding_state'], 'disconnected')
        self.assertEqual(restored.connect('http://127.0.0.1:8793', '我的电脑')['device_id'], settings['device_id'])
        restored.close()

    def test_switching_backend_issues_a_new_binding_identity(self):
        first = self.connection.connect('http://127.0.0.1:8793', '电脑')
        second = self.connection.connect('https://oc.example.com', '电脑')
        self.assertNotEqual(first['device_id'], second['device_id'])
        self.assertEqual(second['binding_state'], 'connecting')

    def test_received_job_cannot_reuse_another_jobs_request_identity(self):
        self.connection.connect('http://127.0.0.1:8793', '电脑')
        command = {'id': 'job2', 'request_id': 'oc-job1', 'parameters': {}}
        with self.assertRaisesRegex(ValueError, '作业格式无效'):
            self.connection._receive_job(None, self.connection.store.settings(), command)

    def test_completed_results_allow_switch_and_restore_original_identity(self):
        first = self.connection.connect('http://127.0.0.1:8793', '电脑')
        self.execution.store.create_job('completed', 'sample@1.0.0', {}, 'oc-pending', '')
        self.execution.store.update_job('completed', state='succeeded', result={'ok': True})
        self.connection.store.save_job({'device_id': first['device_id'],
            'command': {'id': 'pending', 'request_id': 'oc-pending'}, 'assistant_job_id': 'completed',
            'sequence': 1, 'pending_report': None, 'terminal_reported': False, 'failure': ''})
        self.connection.disconnect()
        self.connection.connect('https://oc.example.com', '电脑')
        self.assertEqual(self.connection.snapshot()['pending_reports'], 1)
        restored = self.connection.connect('http://127.0.0.1:8793', '电脑')
        self.assertEqual(restored['device_id'], first['device_id'])

    def test_disconnect_cancels_claimed_but_unstarted_work(self):
        settings = self.connection.connect('http://127.0.0.1:8793', '电脑')
        self.connection.store.save_job({'device_id': settings['device_id'],
            'command': {'id': 'pending', 'request_id': 'oc-pending'}, 'assistant_job_id': None,
            'sequence': 1, 'pending_report': None, 'terminal_reported': False, 'failure': ''})
        self.assertEqual(self.connection.disconnect()['binding_state'], 'disconnected')
        journal = self.connection.store.unfinished_job(settings['device_id'])
        self.assertEqual(journal['failure_state'], 'stopped')
        self.assertEqual(self.execution.list_jobs(), [])

    def test_disconnect_and_switch_are_rejected_while_a_job_is_active(self):
        self.connection.connect('http://127.0.0.1:8793', '电脑')
        self.execution.store.create_job('active', 'sample@1.0.0', {}, None, '')
        with self.assertRaisesRegex(ValueError, '任务'):
            self.connection.disconnect()
        with self.assertRaisesRegex(ValueError, '任务'):
            self.connection.connect('https://oc.example.com', '电脑')

    def test_settings_http_requires_local_token_and_never_returns_credentials(self):
        server = create_server(self.execution, connection=self.connection)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, body=None, authorized=True):
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            headers = {'Content-Type': 'application/json'}
            if authorized:
                headers['X-WBot-Token'] = server.token
            client.request('POST' if body is not None else 'GET', path,
                           json.dumps(body) if body is not None else None, headers)
            response = client.getresponse()
            status, payload = response.status, json.loads(response.read())
            client.close()
            return status, payload
        try:
            self.assertEqual(request('/api/settings', authorized=False)[0], 403)
            status, payload = request('/api/settings/connect', {'server_url': 'https://oc.example.com',
                                                               'device_name': '测试设备'})
            self.assertEqual(status, 200)
            secret = self.connection.store.settings()['secret']
            self.assertNotIn(secret, json.dumps(payload))
            self.assertEqual(request('/api/settings')[1], payload)
            status, payload = request('/api/settings/disconnect', {})
            self.assertEqual(status, 200)
            self.assertEqual(payload['settings']['binding_state'], 'disconnected')
            self.assertEqual(request('/api/settings/connect', {'server_url': 'file:///tmp',
                                                              'device_name': '不应保存'})[0], 400)
            self.assertEqual(request('/api/settings')[1]['settings']['device_name'], '测试设备')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
