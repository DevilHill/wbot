import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.oc.service import OcService
from app.oc.server import create_server


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = OcService(Path(self.temp.name) / 'state')
        self.addCleanup(self.service.close)
        self.auth = self.service.auth
        self.admin = self.auth.bootstrap('owner', 'temporary-pass')

    def test_bootstrap_never_overwrites_existing_accounts(self):
        with self.assertRaises(RuntimeError):
            self.auth.bootstrap('owner', 'replacement')
        self.assertNotIn('password', self.admin)
        stored = self.service.store.get('users', 'owner')
        self.assertNotIn('temporary-pass', json.dumps(stored))

    def test_login_change_password_and_logout_invalidate_sessions(self):
        token, session = self.auth.login('owner', 'temporary-pass', 'local')
        self.assertTrue(session['user']['must_change_password'])
        self.assertNotEqual(session['token'], token)
        self.auth.change_password('owner', 'temporary-pass', 'updated-password-42')
        self.assertIsNone(self.auth.authenticate(token))
        token, session = self.auth.login('owner', 'updated-password-42', 'local')
        self.assertFalse(session['user']['must_change_password'])
        self.auth.logout(token)
        self.assertIsNone(self.auth.authenticate(token))

    def test_role_disable_and_reset_revoke_sessions(self):
        self.auth.create_user({'username': 'reader', 'password': 'reader-password', 'role': 'viewer'})
        for changes in ({'role': 'operator'}, {'password': 'reset-password'}, {'enabled': False}):
            password = 'reset-password' if 'enabled' in changes else 'reader-password'
            token, _ = self.auth.login('reader', password, 'local')
            self.auth.update_user('reader', changes)
            self.assertIsNone(self.auth.authenticate(token))

    def test_last_enabled_admin_cannot_be_disabled_or_demoted(self):
        for changes in ({'role': 'viewer'}, {'enabled': False}):
            with self.assertRaises(ValueError):
                self.auth.update_user('owner', changes)
        self.auth.create_user({'username': 'backup', 'password': 'backup-password', 'role': 'admin'})
        self.auth.update_user('owner', {'enabled': False})

    def test_login_throttling_and_session_expiry(self):
        from app.oc.auth import AuthError
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.auth.login('owner', 'incorrect', 'local')
        with self.assertRaises(AuthError) as error:
            self.auth.login('owner', 'temporary-pass', 'local')
        self.assertEqual(error.exception.status, 429)
        token, _ = self.auth.login('owner', 'temporary-pass', 'other')
        with patch('app.oc.auth.time.time', return_value=10**12):
            self.assertIsNone(self.auth.authenticate(token))

    def test_permission_matrix_covers_mutation_categories_and_denies_unknown(self):
        from app.oc.auth import ROLES
        from app.oc.auth_http import required_permission
        cases = [
            ('POST', '/api/oc/packages', {'admin', 'developer'}),
            ('PATCH', '/api/oc/processes/process', {'admin', 'developer'}),
            ('POST', '/api/oc/elements/repositories', {'admin', 'developer'}),
            ('POST', '/api/oc/processes/process/enqueue', {'admin', 'developer', 'operator'}),
            ('POST', '/api/oc/jobs/job/stop', {'admin', 'developer', 'operator'}),
            ('POST', '/api/oc/devices/robot/approve', {'admin'}),
            ('POST', '/api/oc/assets', {'admin'}),
            ('PATCH', '/api/oc/environments/env', {'admin'}),
            ('POST', '/api/oc/assistant-releases', {'admin'}),
            ('GET', '/api/oc/users', {'admin'}),
            ('POST', '/api/oc/service/stop', set()),
            ('POST', '/api/oc/unknown', set()),
        ]
        for method, path, expected in cases:
            with self.subTest(path=path):
                permission = required_permission(method, path)
                actual = {role for role, data in ROLES.items() if permission in data['permissions']}
                self.assertEqual(actual, expected)


class AuthHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = OcService(self.root / 'state')
        self.service.auth.bootstrap('owner', 'temporary-pass')
        self.service.auth.change_password('owner', 'temporary-pass', 'owner-password')
        self.service.auth.create_user({'username': 'reader', 'password': 'reader-password', 'role': 'viewer'})
        self.service.auth.change_password('reader', 'reader-password', 'reader-updated-pass')
        web = self.root / 'web'
        web.mkdir()
        (web / 'index.html').write_text('login application')
        self.server = create_server(self.service, web, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ''
        self.csrf = ''

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.service.close()
        self.temp.cleanup()

    def request(self, path, body=None, method=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        fields = {'Cookie': self.cookie, 'X-WBot-Token': self.csrf}
        if body is not None:
            fields['Content-Type'] = 'application/json'
        fields.update(headers or {})
        try:
            connection.request(method or ('POST' if body is not None else 'GET'), path,
                               json.dumps(body) if body is not None else None, fields)
            response = connection.getresponse()
            raw = response.read()
            data = json.loads(raw) if response.getheader('Content-Type', '').startswith('application/json') else raw
            return response.status, data, dict(response.getheaders())
        finally:
            connection.close()

    def login(self, name='owner', password='owner-password'):
        status, result, headers = self.request('/api/oc/auth/login', {'username': name, 'password': password})
        self.assertEqual(status, 200)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        self.csrf = result['token']
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])

    def test_anonymous_and_old_service_token_cannot_access_business_data(self):
        self.assertEqual(self.request('/')[0], 200)
        self.assertEqual(self.request('/api/oc/session')[0], 401)
        self.assertEqual(self.request('/api/oc/state', headers={'X-WBot-Token': self.server.token})[0], 401)

    def test_viewer_cannot_mutate_or_manage_users_but_admin_can(self):
        self.login('reader', 'reader-updated-pass')
        self.assertEqual(self.request('/api/oc/state')[0], 200)
        self.assertEqual(self.request('/api/oc/users')[0], 403)
        self.assertEqual(self.request('/api/oc/assets', {'name': 'forbidden'})[0], 403)
        self.assertEqual(self.request('/api/oc/devices/id/approve', {})[0], 403)
        self.assertEqual(self.request('/api/oc/processes/id/enqueue', {})[0], 403)
        self.login()
        self.assertEqual(self.request('/api/oc/users')[0], 200)
        self.assertEqual(self.request('/api/oc/assets', {'name': 'allowed', 'type': 'string', 'value': 'ok'})[0], 201)

    def test_csrf_origin_forced_change_and_logout(self):
        self.login()
        self.assertEqual(self.request('/api/oc/assets', {}, headers={'X-WBot-Token': ''})[0], 403)
        self.assertEqual(self.request('/api/oc/auth/login', {}, headers={'Origin': 'https://foreign.example'})[0], 403)
        self.assertEqual(self.request('/api/oc/auth/logout', {})[0], 200)
        self.assertEqual(self.request('/api/oc/state')[0], 401)
        self.service.auth.update_user('owner', {'password': 'reset-owner-password'})
        self.login('owner', 'reset-owner-password')
        self.assertEqual(self.request('/api/oc/state')[0], 403)
        self.assertEqual(self.request('/api/oc/auth/password', {'current_password': 'reset-owner-password', 'password': 'new-owner-password'})[0], 200)
        self.assertEqual(self.request('/api/oc/state')[0], 401)

    def test_secure_cookie_when_configured_and_loopback_health(self):
        with patch.dict('os.environ', {'WBOT_OC_SECURE_COOKIE': '1'}):
            _, _, headers = self.request('/api/oc/auth/login', {'username': 'owner', 'password': 'owner-password'})
        self.assertIn('; Secure', headers['Set-Cookie'])
        self.assertEqual(self.request('/api/oc/health', headers={'X-WBot-Token': self.server.token})[0], 200)
        self.assertEqual(self.request('/api/oc/health', headers={'X-WBot-Token': self.server.token, 'X-WBot-Proxy': '1'})[0], 401)
