"""通过实际管理端与设备端 HTTP 验证共享元素的权限和合并流程。"""
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from uuid import uuid4

from app.oc.agent_server import create_agent_server
from app.oc.element_service import ElementRepositoryService
from app.oc.server import create_server
from app.oc.service import OcService


ADMIN_PATH = '/api/oc/elements/repositories'
AGENT_PATH = '/api/agent/elements/repositories'


def element():
    return {'id': 'login', 'name': '登录按钮', 'group': '登录页', 'xpath': '//button',
            'url': '', 'frame': None, 'description': ''}


class SharedElementsHttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = OcService(self.root / 'oc')
        self.service.elements = ElementRepositoryService(self.root / 'oc' / 'elements.sqlite3')
        web = self.root / 'web'
        web.mkdir()
        (web / 'index.html').write_text('<html>OC</html>', encoding='utf-8')
        self.admin = create_server(self.service, web, 0)
        self.gateway = create_agent_server(self.service, port=0)
        self.threads = []
        for server in (self.admin, self.gateway):
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
            thread.start()
            self.threads.append(thread)
        self.device = self.enroll('开发电脑 A')

    def tearDown(self):
        for server in (self.admin, self.gateway):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=3)
        self.temporary.cleanup()

    @staticmethod
    def body(**fields):
        return dict(fields, request_id=uuid4().hex)

    def call(self, path, body=None, device=None, headers=None):
        admin = path.startswith('/api/oc/')
        server = self.admin if admin else self.gateway
        request_headers = {'X-WBot-Token': self.admin.token} if admin else {}
        if device:
            request_headers.update({'X-WBot-Device': device['device_id'], 'X-WBot-Device-Token': device['secret']})
        content = None
        if body is not None:
            request_headers['Content-Type'] = 'application/json'
            content = json.dumps(body, ensure_ascii=False).encode('utf-8')
        request_headers.update(headers or {})
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            connection.request('POST' if body is not None else 'GET', path, content, request_headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def enroll(self, name):
        device = {'device_id': uuid4().hex, 'name': name, 'secret': secrets.token_urlsafe(32)}
        status, payload = self.call('/api/agent/enroll', device)
        self.assertEqual(status, 201, payload)
        return device

    def approve(self, device=None):
        device = device or self.device
        status, payload = self.call('/api/oc/devices/' + device['device_id'] + '/approve', {})
        self.assertEqual(status, 200, payload)

    def repository(self):
        status, payload = self.call(ADMIN_PATH, self.body(name='共享登录页', description='HTTP 验证', items=[element()]))
        self.assertEqual(status, 201, payload)
        return payload['repository']

    def branch(self, repository):
        status, payload = self.call(AGENT_PATH + '/' + repository['id'] + '/branches',
            self.body(name='fix-login', base_commit=repository['head']), self.device)
        self.assertEqual(status, 201, payload)
        return payload['branch']

    def proposal(self, repository):
        branch = self.branch(repository)
        path = AGENT_PATH + '/' + repository['id'] + '/branches/' + branch['id']
        items = [dict(element(), xpath='//button[@id="login"]')]
        status, payload = self.call(path + '/commits',
            self.body(expected_head=branch['head'], message='修复登录定位', items=items), self.device)
        self.assertEqual(status, 201, payload)
        status, payload = self.call(path + '/requests',
            self.body(expected_head=payload['branch']['head'], title='修复登录按钮', description='XPath 已本机验证'), self.device)
        self.assertEqual(status, 201, payload)
        return payload['request']

    def test_admin_create_device_commit_request_review_merge_and_restore(self):
        repository = self.repository()
        self.approve()
        status, catalog = self.call(AGENT_PATH, device=self.device)
        self.assertEqual(status, 200)
        self.assertEqual(catalog['items'], [repository])
        request = self.proposal(repository)
        base_path = ADMIN_PATH + '/' + repository['id']
        status, review = self.call(base_path + '/requests/' + request['id'])
        self.assertEqual(status, 200, review)
        self.assertEqual(review['changes'][0]['type'], 'modified')
        self.assertEqual(review['changes'][0]['after']['xpath'], '//button[@id="login"]')
        self.assertEqual(review['conflicts'], [])
        payload = self.body(expected_main=review['main_head'], expected_source=review['source_head'], resolutions=[])
        status, merged = self.call(base_path + '/requests/' + request['id'] + '/merge', payload)
        self.assertEqual(status, 200, merged)
        self.assertEqual(merged['request']['state'], 'merged')
        self.assertEqual(self.call(base_path + '/requests/' + request['id'] + '/merge', payload)[1], merged)
        status, detail = self.call(AGENT_PATH + '/' + repository['id'], device=self.device)
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail['head']['items'][0]['xpath'], '//button[@id="login"]')
        status, restored = self.call(base_path + '/restore', self.body(expected_head=detail['head']['id'],
            commit_id=repository['head'], message='回退至已知可用版本'))
        self.assertEqual(status, 200, restored)
        self.assertEqual(restored['commit']['items'], [element()])
        self.assertEqual(self.call(base_path + '/commits/' + merged['commit']['id'])[1]['commit'], merged['commit'])

    def test_pending_wrong_credentials_and_revoked_devices_cannot_access(self):
        repository = self.repository()
        path = AGENT_PATH + '/' + repository['id']
        self.assertEqual(self.call(path, device=self.device)[0], 403)
        self.assertEqual(self.call(AGENT_PATH)[0], 403)
        self.approve()
        branch = self.branch(repository)
        wrong = dict(self.device, secret=secrets.token_urlsafe(32))
        self.assertEqual(self.call(path, device=wrong)[0], 403)
        self.assertEqual(self.call('/api/oc/devices/' + self.device['device_id'] + '/revoke', {})[0], 200)
        self.assertEqual(self.call(path, device=self.device)[0], 403)
        self.assertEqual(self.call(path + '/branches/' + branch['id'] + '/commits',
            self.body(expected_head=branch['head'], message='撤销后提交', items=[]), self.device)[0], 403)

    def test_accepted_operation_receipt_is_readable_only_by_its_approved_device(self):
        repository = self.repository()
        self.approve()
        body = self.body(name='receipt', base_commit=repository['head'])
        status, created = self.call(AGENT_PATH + '/' + repository['id'] + '/branches', body, self.device)
        self.assertEqual(status, 201, created)
        path = '/api/agent/elements/operations/' + body['request_id']
        status, receipt = self.call(path, device=self.device)
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt['result'], created['branch'])
        other = self.enroll('其他设备')
        self.approve(other)
        self.assertEqual(self.call(path, device=other)[0], 404)
        self.assertEqual(self.call('/api/agent/elements/operations/' + uuid4().hex, device=self.device)[0], 404)
        self.assertEqual(self.call('/api/oc/devices/' + self.device['device_id'] + '/revoke', {})[0], 200)
        self.assertEqual(self.call(path, device=self.device)[0], 403)

    def test_device_cannot_change_another_branch_or_spoof_author(self):
        repository = self.repository()
        self.approve()
        branch = self.branch(repository)
        other = self.enroll('开发电脑 B')
        self.approve(other)
        path = AGENT_PATH + '/' + repository['id'] + '/branches/' + branch['id']
        body = self.body(expected_head=branch['head'], message='非法写入', items=[])
        self.assertEqual(self.call(path + '/commits', body, other)[0], 403)
        self.assertEqual(self.call(path + '/commits', dict(body, device_id=self.device['device_id']), self.device)[0], 400)
        self.assertEqual(self.call(path + '/requests', self.body(expected_head=branch['head'], title='冒用'), other)[0], 403)

    def test_agent_never_gains_management_actions(self):
        repository = self.repository()
        self.approve()
        request = self.proposal(repository)
        path = AGENT_PATH + '/' + repository['id']
        for endpoint, body in (
            (AGENT_PATH, self.body(name='非法创建')),
            (path + '/requests/' + request['id'] + '/merge', self.body(expected_main=repository['head'],
                expected_source=request['source_head'], resolutions=[])),
            (path + '/requests/' + request['id'] + '/close', self.body(expected_source=request['source_head'], reason='无权关闭')),
            (path + '/restore', self.body(expected_head=repository['head'], commit_id=request['source_head'], message='无权恢复')),
        ):
            with self.subTest(endpoint=endpoint):
                self.assertIn(self.call(endpoint, body, self.device)[0], (403, 404))
        status, review = self.call(path + '/requests/' + request['id'], device=self.device)
        self.assertEqual(status, 200, review)
        self.assertEqual(review['request']['state'], 'open')

    def test_admin_requires_token_same_origin_and_does_not_leak_device_secret(self):
        self.assertEqual(self.call(ADMIN_PATH, headers={'X-WBot-Token': ''})[0], 403)
        self.assertEqual(self.call(ADMIN_PATH, self.body(name='跨站'), headers={'Origin': 'http://evil.test'})[0], 403)
        repository = self.repository()
        self.approve()
        request = self.proposal(repository)
        endpoints = [ADMIN_PATH, ADMIN_PATH + '/' + repository['id'],
                     ADMIN_PATH + '/' + repository['id'] + '/requests/' + request['id']]
        for path in endpoints:
            status, payload = self.call(path)
            self.assertEqual(status, 200)
            serialized = json.dumps(payload)
            self.assertNotIn(self.device['secret'], serialized)
            self.assertNotIn(hashlib.sha256(self.device['secret'].encode()).hexdigest(), serialized)
        missing = uuid4().hex
        self.assertEqual(self.call(ADMIN_PATH + '/' + missing)[0], 404)
        self.assertEqual(self.call(AGENT_PATH + '/' + missing, device=self.device)[0], 404)

    def test_large_valid_snapshot_uses_element_limit_and_oversized_body_is_rejected(self):
        repository = self.repository()
        self.approve()
        branch = self.branch(repository)
        path = AGENT_PATH + '/' + repository['id'] + '/branches/' + branch['id'] + '/commits'
        items = [dict(element(), id=str(index), name=f'元素{index}', description='内容' * 1000) for index in range(8)]
        body = self.body(expected_head=branch['head'], message='超过控制消息 8 KiB 的有效快照', items=items)
        status, payload = self.call(path, body, self.device)
        self.assertEqual(status, 201, payload)
        self.assertEqual(self.call(path, {}, self.device, {'Content-Length': str(2 * 1024 * 1024 + 1)})[0], 400)
        self.assertEqual(self.call(ADMIN_PATH, {}, headers={'Content-Length': str(2 * 1024 * 1024 + 1)})[0], 400)

    def test_close_and_optimistic_head_conflict_are_exposed_over_http(self):
        repository = self.repository()
        self.approve()
        request = self.proposal(repository)
        path = ADMIN_PATH + '/' + repository['id']
        restored = self.call(path + '/restore', self.body(expected_head=repository['head'],
            commit_id=repository['head'], message='产生新的已知主分支版本'))[1]['commit']
        status, payload = self.call(path + '/requests/' + request['id'] + '/merge', self.body(
            expected_main=repository['head'], expected_source=request['source_head'], resolutions=[]))
        self.assertEqual(status, 409, payload)
        status, closed = self.call(path + '/requests/' + request['id'] + '/close', self.body(
            expected_source=request['source_head'], reason='请重新验证'))
        self.assertEqual(status, 200, closed)
        self.assertEqual(closed['request']['state'], 'closed')
        self.assertEqual(self.call(path)[1]['head']['id'], restored['id'])


if __name__ == '__main__':
    unittest.main()
