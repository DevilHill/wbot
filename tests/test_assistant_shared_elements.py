"""通过真实 OC 通信验证共享元素的本地保护与重试恢复。"""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.assistant.connection import ConnectionService
from app.assistant.execution import ExecutionService
from app.assistant.remote_client import GatewayClient, GatewayError
from app.assistant.shared_elements import SharedElementService
from app.oc.agent_server import create_agent_server
from app.oc.service import OcService
from wbot.elements import ElementLibrary


class SharedElementIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.oc = OcService(self.root / 'oc')
        self.gateway = create_agent_server(self.oc, port=0)
        self.thread = threading.Thread(target=self.gateway.serve_forever, daemon=True)
        self.thread.start()
        self.execution = ExecutionService(self.root / 'assistant')
        self.connection = ConnectionService(self.root / 'assistant', self.execution)
        identity = self.connection.connect(self.gateway.origin, '开发机')
        self.connection.synchronize()
        self.oc.agents.decide(identity['device_id'], 'approve')
        self.connection.synchronize()
        self.shared = SharedElementService(self.connection)
        self.library = ElementLibrary(self.root / 'elements.sqlite3')
        self.repository = self.oc.elements.create_repository({'name': '业务系统', 'request_id': uuid4().hex})

    def tearDown(self):
        self.connection.close()
        self.execution.shutdown()
        self.gateway.shutdown()
        self.gateway.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def call(self, action, **values):
        return self.shared.dispatch(action, dict(library_path=str(self.library.path), **values))

    def write_body(self, **values):
        status = self.call('status')
        binding = status['binding'] or {}
        return dict(expected_fingerprint=status['fingerprint'], expected_branch=binding.get('branch_id'),
                    expected_head=binding.get('head'), request_id=uuid4().hex, **values)

    def connect(self, name='fix-login'):
        return self.call('connect', **self.write_body(repository_id=self.repository['id'], branch_name=name))

    def edit(self, xpath='//button'):
        return self.library.upsert({'id': 'login', 'name': '登录', 'group': '登录页', 'xpath': xpath})

    def merge(self, request):
        review = self.oc.elements.review_request(self.repository['id'], request['id'])
        return self.oc.elements.merge_request(self.repository['id'], request['id'], {
            'expected_main': review['main_head'], 'expected_source': review['source_head'],
            'resolutions': [], 'request_id': uuid4().hex})

    def test_submit_review_merge_and_pull_preserve_versioned_workflow(self):
        self.edit()
        connected = self.connect()
        self.assertTrue(connected['dirty'])
        committed = self.call('commit', **self.write_body(message='新增登录按钮'))
        self.assertFalse(committed['dirty'])
        self.assertEqual(self.oc.elements.get_repository(self.repository['id'])['head']['items'], [])
        submitted = self.call('request', **self.write_body(title='共享登录按钮', description='已在页面验证'))
        self.merge(submitted['request'])
        pulled = self.call('pull', **self.write_body())
        self.assertFalse(pulled['dirty'])
        self.assertEqual(pulled['branch_status'], 'merged')
        self.assertEqual(self.library.get('login')['xpath'], '//button')
        with self.assertRaisesRegex((ValueError, RuntimeError, GatewayError), '分支|合并'):
            self.edit('//input')
            self.call('commit', **self.write_body(message='需要新的分支'))

    def test_stale_editor_confirmation_and_dirty_pull_do_not_change_working_copy(self):
        self.connect()
        body = self.write_body(message='过期确认')
        self.edit()
        with self.assertRaisesRegex(RuntimeError, '本地元素'):
            self.call('commit', **body)
        committed = self.call('commit', **self.write_body(message='登录'))
        submitted = self.call('request', **self.write_body(title='登录', description=''))
        self.merge(submitted['request'])
        self.edit('//input')
        with self.assertRaisesRegex(RuntimeError, '未提交'):
            self.call('pull', **self.write_body())
        self.assertEqual(self.library.get('login')['xpath'], '//input')
        self.assertEqual(self.call('status')['binding']['head'], committed['binding']['head'])

    def test_lost_commit_response_recovers_after_restart_without_duplicate_commit(self):
        self.connect()
        self.edit()
        body = self.write_body(message='只提交一次')
        original = GatewayClient.request
        def lost_ack(client, endpoint, payload=None):
            result = original(client, endpoint, payload)
            if endpoint.endswith('/commits') and payload is not None:
                raise GatewayError('模拟回包丢失')
            return result
        with patch.object(GatewayClient, 'request', lost_ack), self.assertRaises(GatewayError):
            self.call('commit', **body)
        count = len(self.oc.elements.get_repository(self.repository['id'])['commits'])
        self.shared = SharedElementService(self.connection)
        resumed = self.call('commit', **body)
        self.assertFalse(resumed['dirty'])
        self.assertEqual(len(self.oc.elements.get_repository(self.repository['id'])['commits']), count)

    def test_edit_during_commit_is_preserved_as_new_uncommitted_change(self):
        self.connect()
        self.edit()
        body = self.write_body(message='提交旧快照')
        original = GatewayClient.request
        def edited_during_request(client, endpoint, payload=None):
            response = original(client, endpoint, payload)
            if endpoint.endswith('/commits') and payload is not None:
                self.edit('//input')
            return response
        with patch.object(GatewayClient, 'request', edited_during_request):
            result = self.call('commit', **body)
        self.assertTrue(result['dirty'])
        self.assertEqual(self.library.get('login')['xpath'], '//input')
        self.assertEqual(result['commit']['items'][0]['xpath'], '//button')

    def test_switching_oc_keeps_local_diff_but_blocks_old_repository_write(self):
        self.connect()
        self.edit()
        body = self.write_body(message='不能提交到另一个OC')
        self.connection.connect('http://127.0.0.1:1', '其他后台')
        self.assertEqual(len(self.call('diff')['changes']), 1)
        with self.assertRaises((RuntimeError, PermissionError)):
            self.call('commit', **body)

    def test_delete_during_connection_is_not_reintroduced_by_shared_snapshot(self):
        self.edit()
        original_items = self.library.export_data()['items']
        self.repository = self.oc.elements.create_repository({'name': '含登录元素', 'items': original_items,
                                                              'request_id': uuid4().hex})
        original = GatewayClient.request
        def delete_during_request(client, endpoint, payload=None):
            response = original(client, endpoint, payload)
            if endpoint.endswith('/branches') and payload is not None:
                self.library.delete('login')
            return response
        with patch.object(GatewayClient, 'request', delete_during_request):
            result = self.connect()
        self.assertEqual(self.library.list(), [])
        self.assertTrue(result['dirty'])
        self.assertEqual(result['changes'][0]['type'], 'deleted')

    def test_status_recovers_lost_merge_request_response_without_reposting(self):
        self.connect()
        self.edit()
        self.call('commit', **self.write_body(message='登录'))
        body = self.write_body(title='登录', description='')
        original = GatewayClient.request
        def lose_ack(client, endpoint, payload=None):
            response = original(client, endpoint, payload)
            if endpoint.endswith('/requests') and payload is not None:
                raise GatewayError('模拟回包丢失')
            return response
        with patch.object(GatewayClient, 'request', lose_ack), self.assertRaises(GatewayError):
            self.call('request', **body)
        def reads_only(client, endpoint, payload=None):
            self.assertIsNone(payload)
            return original(client, endpoint, payload)
        with patch.object(GatewayClient, 'request', reads_only):
            status = self.call('status')
        self.assertIsNone(status['pending_action'])
        self.assertEqual(status['request']['state'], 'open')

    def test_new_branch_after_merge_carries_uncommitted_edits_and_deletions(self):
        self.connect()
        self.edit()
        self.library.upsert({'id': 'gone', 'name': '待删除', 'xpath': '//div'})
        self.call('commit', **self.write_body(message='两个元素'))
        request = self.call('request', **self.write_body(title='初始元素', description=''))['request']
        self.merge(request)
        self.edit('//input')
        self.library.delete('gone')
        connected = self.connect('next-change')
        self.assertTrue(connected['dirty'])
        self.assertEqual(self.library.get('login')['xpath'], '//input')
        self.assertEqual([item['id'] for item in self.library.list()], ['login'])
        committed = self.call('commit', **self.write_body(message='后续修改'))
        self.assertFalse(committed['dirty'])

    def test_new_branch_cannot_silently_overwrite_conflicting_main_changes(self):
        self.connect()
        self.edit()
        self.call('commit', **self.write_body(message='登录'))
        request = self.call('request', **self.write_body(title='登录', description=''))['request']
        self.merge(request)
        other = self.oc.elements.create_branch(self.repository['id'], {'id': 'other', 'name': '其他开发者'},
            {'name': 'main-update', 'base_commit': self.oc.elements.get_repository(self.repository['id'])['head']['id'],
             'request_id': uuid4().hex})
        changed = self.oc.elements.commit_branch(self.repository['id'], other['id'], {'id': 'other', 'name': '其他开发者'},
            {'expected_head': other['head'], 'message': '改变主分支', 'items': [dict(self.library.get('login'), xpath='//a')],
             'request_id': uuid4().hex})
        mr = self.oc.elements.open_request(self.repository['id'], other['id'], {'id': 'other', 'name': '其他开发者'},
            {'expected_head': changed['commit']['id'], 'title': '改变主分支', 'request_id': uuid4().hex})
        self.merge(mr)
        self.edit('//input')
        with self.assertRaisesRegex(RuntimeError, '冲突'):
            self.connect('conflicting-next-change')
        self.assertEqual(self.library.get('login')['xpath'], '//input')


if __name__ == '__main__':
    unittest.main()
