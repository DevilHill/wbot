"""通过真实 HTTP 验证远程设备绑定、任务领取和凭据边界。"""
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from uuid import uuid4

from app.automation_package import build_package, create_project
from app.oc.agent_server import create_agent_server
from app.oc.server import create_server
from app.oc.service import OcService


class OcAgentServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = OcService(self.root / 'oc')
        web = self.root / 'web'
        web.mkdir()
        (web / 'index.html').write_text('<html>OC</html>', encoding='utf-8')
        self.admin = create_server(self.service, web, 0)
        self.gateway = create_agent_server(self.service, port=0)
        self.threads = []
        for server in (self.admin, self.gateway):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)

    def tearDown(self):
        for server in (self.admin, self.gateway):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=3)
        self.temporary.cleanup()

    def request(self, path, body=None, credentials=None, admin=False, headers=None):
        server = self.admin if admin else self.gateway
        request_headers = {'X-WBot-Token': self.admin.token} if admin else {}
        if credentials:
            request_headers.update({'X-WBot-Device': credentials['device_id'],
                                    'X-WBot-Device-Token': credentials['secret']})
        if body is not None:
            request_headers['Content-Type'] = 'application/json'
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        request_headers.update(headers or {})
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            connection.request('POST' if body is not None else 'GET', path, body, request_headers)
            response = connection.getresponse()
            content = response.read()
            if response.getheader('Content-Type', '').startswith('application/json'):
                content = json.loads(content)
            return response.status, content, dict(response.getheaders())
        finally:
            connection.close()

    def enroll(self, name='远程设备'):
        identity = {'device_id': uuid4().hex, 'name': name, 'secret': secrets.token_urlsafe(32)}
        status, response, _ = self.request('/api/agent/enroll', identity)
        self.assertEqual(status, 201, response)
        return identity, response['device']

    def approve(self, identity):
        status, response, _ = self.request('/api/oc/devices/' + identity['device_id'] + '/approve', {}, admin=True)
        self.assertEqual(status, 200, response)
        self.request('/api/agent/poll', {'active_job_id': None}, identity)

    def deploy(self, identity):
        project = self.root / uuid4().hex
        create_project(project, 'remote-demo')
        archive = build_package(project)
        package = self.service.import_package(archive)
        process = self.service.create_process({'name': '远程流程', 'package_id': package['id'],
                                              'device_id': identity['device_id']})
        return process, archive

    def report(self, state='running', sequence=1, **updates):
        return dict({'state': state, 'sequence': sequence, 'assistant_job_id': 'local-job',
                     'started_at': 1.0, 'finished_at': None, 'result': None, 'error': '', 'log': '真实日志'}, **updates)

    def test_resource_admin_routes_and_queue_authentication(self):
        identity, robot = self.enroll()
        self.approve(identity)
        process, _ = self.deploy(identity)
        status, _, _ = self.request('/api/oc/assets', {'name': '普通配置', 'type': 'string', 'value': '正文'},
                                    admin=True, headers={'X-WBot-Token': ''})
        self.assertEqual(status, 403)
        status, asset, _ = self.request('/api/oc/assets', {'name': '普通配置', 'type': 'string', 'value': '正文'}, admin=True)
        self.assertEqual(status, 201, asset)
        status, environment, _ = self.request('/api/oc/environments', {'name': '财务', 'robot_ids': [robot['id']]}, admin=True)
        self.assertEqual(status, 201, environment)
        status, body, _ = self.request('/api/oc/processes/' + process['id'] + '/enqueue',
                                       {'request_id': 'http-queue', 'priority': 90}, admin=True)
        self.assertEqual(status, 201, body)
        self.assertEqual(body['job']['state'], 'queued')
        status, robots, _ = self.request('/api/oc/robots', admin=True)
        self.assertEqual(status, 200)
        self.assertNotIn('_secret_hash', str(robots))
        status, _, _ = self.request('/api/agent/assets', credentials=identity)
        self.assertEqual(status, 404)
        status, _, _ = self.request('/api/oc/assets/' + asset['item']['id'] + '/delete', {}, admin=True)
        self.assertEqual(status, 200)

    def test_gateway_exposes_no_admin_session_static_or_browser_origin(self):
        status, health, headers = self.request('/api/agent/health')
        self.assertEqual(status, 200)
        self.assertEqual(health, {'product': 'wbot-oc-agent', 'protocol_version': 1})
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        for path in ('/', '/api/oc/session', '/api/oc/state'):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request('/api/agent/health', headers={'Origin': 'http://evil.test'})[0], 403)
        self.assertEqual(self.request('/api/agent/status')[0], 403)

    def test_enrollment_is_pending_idempotent_and_never_leaks_secret_hash(self):
        identity, device = self.enroll()
        self.assertEqual(device['binding_state'], 'pending')
        self.assertRegex(device['verification_code'], r'^\d{6}$')
        self.assertEqual(self.request('/api/agent/enroll', identity)[1]['device'], device)
        changed = dict(identity, secret=secrets.token_urlsafe(32))
        self.assertEqual(self.request('/api/agent/enroll', changed)[0], 403)
        public = json.dumps(self.service.snapshot())
        self.assertNotIn(identity['secret'], public)
        self.assertNotIn(hashlib.sha256(identity['secret'].encode()).hexdigest(), public)
        self.assertNotIn(identity['secret'].encode(), (self.root / 'oc' / 'oc.sqlite3').read_bytes())
        self.assertEqual(self.request('/api/agent/poll', {'active_job_id': None}, identity)[1]['job'], None)
        self.assertEqual(self.request('/api/oc/devices/' + device['id'] + '/reject', {}, admin=True)[0], 200)
        self.assertEqual(self.request('/api/agent/enroll', identity)[1]['device']['binding_state'], 'rejected')
        self.assertEqual(self.request('/api/oc/devices/' + device['id'] + '/approve', {}, admin=True)[0], 409)

    def test_claim_download_report_idempotency_and_device_isolation(self):
        identity, _ = self.enroll()
        other, _ = self.enroll('另一设备')
        self.approve(identity)
        self.approve(other)
        process, archive = self.deploy(identity)
        created = self.service.run_process(process['id'], {}, 'remote-request')
        self.assertEqual(created['state'], 'dispatching')
        response = self.request('/api/agent/poll', {'active_job_id': None}, identity)[1]
        job = response['job']
        self.assertEqual(job['id'], created['id'])
        self.assertEqual(self.request('/api/agent/poll', {'active_job_id': job['id']}, identity)[1]['job'], job)
        status, content, _ = self.request(job['package_url'], credentials=identity)
        self.assertEqual(status, 200)
        self.assertEqual(content, archive.read_bytes())
        self.assertEqual(hashlib.sha256(content).hexdigest(), job['package_sha256'])
        self.assertEqual(self.request(job['package_url'], credentials=other)[0], 404)
        report_path = '/api/agent/jobs/' + job['id'] + '/report'
        self.assertEqual(self.request(report_path, self.report(), other)[0], 404)
        self.assertEqual(self.request(report_path, self.report(), identity)[0], 200)
        self.assertEqual(self.request(report_path, self.report(), identity)[0], 200)
        self.assertEqual(self.request(report_path, self.report(log='changed'), identity)[0], 409)
        final = self.report('succeeded', 2, result={'ok': True}, finished_at=2.0)
        self.assertEqual(self.request(report_path, final, identity)[0], 200)
        self.assertEqual(self.service.get_job(job['id'])['result'], {'ok': True})
        self.assertEqual(self.service.read_log(job['id'])['log'], '真实日志')
        self.assertEqual(self.request(report_path, self.report(sequence=3), identity)[0], 409)

    def test_revocation_blocks_new_work_but_received_job_can_finish_and_receive_stop(self):
        identity, _ = self.enroll()
        self.approve(identity)
        process, _ = self.deploy(identity)
        created = self.service.run_process(process['id'], {}, 'revoke-job')
        job = self.request('/api/agent/poll', {'active_job_id': None}, identity)[1]['job']
        self.service.stop_job(created['id'])
        self.assertIn(job['id'], self.request('/api/agent/poll', {'active_job_id': job['id']}, identity)[1]['stop_job_ids'])
        self.assertEqual(self.request('/api/oc/devices/' + identity['device_id'] + '/revoke', {}, admin=True)[0], 200)
        self.assertEqual(self.request('/api/agent/poll', {'active_job_id': job['id']}, identity)[1]['job'], None)
        self.assertEqual(self.request(job['package_url'], credentials=identity)[0], 403)
        self.assertEqual(self.request('/api/agent/enroll', identity)[1]['device']['binding_state'], 'revoked')
        with self.assertRaises(RuntimeError):
            self.service.run_process(process['id'], {}, 'after-revoke')
        final = self.report('stopped', 1, finished_at=2.0)
        self.assertEqual(self.request('/api/agent/jobs/' + job['id'] + '/report', final, identity)[0], 200)
        self.assertEqual(self.service.get_job(job['id'])['state'], 'stopped')

    def test_pending_devices_cannot_deploy_and_pending_limit_is_enforced(self):
        identity, _ = self.enroll()
        with self.assertRaises(RuntimeError):
            self.deploy(identity)
        for index in range(99):
            self.service.agents.enroll({'device_id': uuid4().hex, 'name': str(index), 'secret': secrets.token_urlsafe(32)})
        self.assertEqual(self.request('/api/agent/enroll', {
            'device_id': uuid4().hex, 'name': 'overflow', 'secret': secrets.token_urlsafe(32)})[0], 409)

    def test_local_busy_defers_claim_and_revocation_cancels_only_unclaimed_dispatch(self):
        identity, _ = self.enroll()
        self.approve(identity)
        process, _ = self.deploy(identity)
        created = self.service.run_process(process['id'], {}, 'waiting-for-local')
        response = self.request('/api/agent/poll', {'active_job_id': None, 'busy': True}, identity)[1]
        self.assertIsNone(response['job'])
        self.assertEqual(response['device']['status'], 'busy')
        status, response, _ = self.request('/api/oc/devices/' + identity['device_id'] + '/revoke', {}, admin=True)
        self.assertEqual(status, 200, response)
        self.assertEqual(self.service.get_job(created['id'])['state'], 'failed')
        self.assertIsNone(self.request('/api/agent/poll', {'active_job_id': None, 'busy': False}, identity)[1]['job'])

    def test_reports_survive_oc_restart_and_null_local_id_can_report_download_failure(self):
        identity, _ = self.enroll()
        self.approve(identity)
        process, _ = self.deploy(identity)
        created = self.service.run_process(process['id'], {}, 'failed-download')
        self.request('/api/agent/poll', {'active_job_id': None}, identity)
        report_path = '/api/agent/jobs/' + created['id'] + '/report'
        final = self.report('failed', 0, assistant_job_id=None, started_at=None, finished_at=2,
                            error='下载校验失败', log='')
        self.assertEqual(self.request(report_path, final, identity)[0], 200)
        restored = OcService(self.root / 'oc')
        self.gateway.service = restored
        self.assertEqual(self.request(report_path, final, identity)[0], 200)
        self.assertEqual(restored.get_job(created['id'])['error'], '下载校验失败')
        self.assertEqual(restored.read_log(created['id'])['log'], '')
        self.assertEqual(restored.run_process(process['id'], {}, 'failed-download')['id'], created['id'])

    def test_bad_credentials_and_oversized_reports_never_change_job_state(self):
        identity, _ = self.enroll()
        self.approve(identity)
        process, _ = self.deploy(identity)
        created = self.service.run_process(process['id'], {}, 'report-limits')
        self.request('/api/agent/poll', {'active_job_id': None}, identity)
        endpoint = '/api/agent/jobs/' + created['id'] + '/report'
        wrong = dict(identity, secret=secrets.token_urlsafe(32))
        self.assertEqual(self.request(endpoint, self.report(), wrong)[0], 403)
        self.assertEqual(self.request(endpoint, self.report(log='x' * (512 * 1024 + 1)), identity)[0], 400)
        self.assertEqual(self.request(endpoint, self.report(result='x' * 1024 * 1024), identity)[0], 400)
        self.assertEqual(self.request(endpoint, self.report(state=[]), identity)[0], 400)
        self.assertEqual(self.request(endpoint, self.report(started_at=10 ** 400), identity)[0], 400)
        self.assertEqual(self.service.get_job(created['id'])['state'], 'dispatching')


if __name__ == '__main__':
    unittest.main()
