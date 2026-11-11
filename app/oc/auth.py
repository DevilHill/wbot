"""单组织账号、固定角色与可撤销会话；用户记录复用 OC 持久化存储。"""
import hashlib
import hmac
import os
import re
import secrets
import time


PERMISSIONS = {
    'read': '查看运营数据与日志', 'users.manage': '管理账号与角色',
    'robots.manage': '审批与维护 Robot', 'environments.manage': '管理 Environment',
    'assets.manage': '管理 Asset', 'packages.manage': '上传自动化包',
    'processes.manage': '部署与配置流程', 'elements.manage': '管理共享元素与合并',
    'jobs.run': '提交运行任务', 'jobs.stop': '取消或停止任务',
    'releases.manage': '发布客户端更新',
}
ROLES = {
    'admin': {'name': '管理员', 'permissions': list(PERMISSIONS)},
    'developer': {'name': '开发者', 'permissions': ['read', 'packages.manage', 'processes.manage', 'elements.manage', 'jobs.run', 'jobs.stop']},
    'operator': {'name': '操作员', 'permissions': ['read', 'jobs.run', 'jobs.stop']},
    'viewer': {'name': '只读用户', 'permissions': ['read']},
}
SESSION_LIFETIME = 8 * 60 * 60
SESSION_IDLE = 30 * 60


class AuthError(Exception):
    def __init__(self, message, status=401):
        super().__init__(message)
        self.status = status


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def password_matches(password, encoded):
    _, iterations, salt, expected = encoded.split('$')
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    return hmac.compare_digest(digest, expected)


def validate_password(password, *, initial=False):
    minimum = 6 if initial else 12
    if not isinstance(password, str) or not minimum <= len(password) <= 256:
        raise ValueError(f'密码长度须为 {minimum}–256 个字符')
    return password


def public_user(user):
    fields = ('id', 'username', 'display_name', 'role', 'enabled', 'must_change_password', 'created_at', 'updated_at')
    return {key: user[key] for key in fields}


class AuthService:
    def __init__(self, store, lock):
        self.store, self.lock = store, lock
        self.enabled = os.environ.get('WBOT_OC_AUTH_REQUIRED') == '1' or bool(store.list('users'))
        self.sessions = {}
        self.failures = {}
        self.dummy_hash = None

    def bootstrap(self, username, password):
        with self.lock:
            if self.store.list('users'):
                raise RuntimeError('已有账号，拒绝重新初始化管理员')
            user = self.create_user({'username': username, 'password': password, 'role': 'admin'}, initial=True)
            self.enabled = True
            return user

    def list_users(self):
        return [public_user(user) for user in self.store.list('users')]

    def create_user(self, body, *, initial=False):
        if set(body) - {'username', 'display_name', 'password', 'role'}:
            raise ValueError('账号字段无效')
        username = body.get('username')
        if not isinstance(username, str) or not re.fullmatch(r'[a-z][a-z0-9_.-]{2,31}', username):
            raise ValueError('账号须为 3–32 位小写字母、数字、点、下划线或连字符，且以字母开头')
        role = body.get('role', 'viewer')
        if not isinstance(role, str) or role not in ROLES:
            raise ValueError('角色无效')
        display_name = body.get('display_name', username)
        if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 80:
            raise ValueError('显示名称须为 1–80 个字符')
        password = validate_password(body.get('password'), initial=initial)
        with self.lock:
            if any(user['id'] == username for user in self.store.list('users')):
                raise ValueError('账号已存在')
            now = time.time()
            user = {'id': username, 'username': username, 'display_name': display_name.strip(), 'role': role,
                    'enabled': True, 'must_change_password': True, '_password_hash': password_hash(password),
                    '_version': 1, 'created_at': now, 'updated_at': now}
            self.store.insert('users', user)
            self.enabled = True
            return public_user(user)

    def update_user(self, identifier, body):
        if not body or set(body) - {'display_name', 'role', 'enabled', 'password'}:
            raise ValueError('账号更新字段无效')
        with self.lock:
            user = self.store.get('users', identifier)
            updated = dict(user)
            if 'display_name' in body:
                name = body['display_name']
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
                    raise ValueError('显示名称须为 1–80 个字符')
                updated['display_name'] = name.strip()
            if 'role' in body:
                if not isinstance(body['role'], str) or body['role'] not in ROLES:
                    raise ValueError('角色无效')
                updated['role'] = body['role']
            if 'enabled' in body:
                if type(body['enabled']) is not bool:
                    raise ValueError('启用状态必须为布尔值')
                updated['enabled'] = body['enabled']
            if user['enabled'] and user['role'] == 'admin' and (not updated['enabled'] or updated['role'] != 'admin'):
                others = [item for item in self.store.list('users') if item['id'] != identifier and item['enabled'] and item['role'] == 'admin']
                if not others:
                    raise ValueError('至少保留一个启用的管理员')
            if 'password' in body:
                updated['_password_hash'] = password_hash(validate_password(body['password']))
                updated['must_change_password'] = True
            updated.update(_version=user['_version'] + 1, updated_at=time.time())
            self.store.replace('users', updated)
            self._revoke(identifier)
            return public_user(updated)

    def _revoke(self, identifier):
        self.sessions = {token: session for token, session in self.sessions.items() if session['user_id'] != identifier}

    def _prune(self, now):
        self.sessions = {key: value for key, value in self.sessions.items()
                         if value['expires'] > now and value['seen'] + SESSION_IDLE > now}
        self.failures = {key: value for key, value in self.failures.items() if value['until'] > now}

    def login(self, username, password, address):
        if not isinstance(username, str) or len(username) > 32 or not isinstance(password, str) or len(password) > 256:
            raise AuthError('账号或密码错误')
        with self.lock:
            now = time.time()
            self._prune(now)
            key = (address, username)
            # Cap both per-account/address attempts and address-wide username spraying.
            keys = (key, (address, '*'))
            if any(self.failures.get(item, {}).get('count', 0) >= limit for item, limit in zip(keys, (5, 30))):
                raise AuthError('登录尝试过多，请 15 分钟后重试', 429)
            if len(self.failures) >= 4096 or len(self.sessions) >= 4096:
                raise AuthError('登录服务繁忙，请稍后重试', 429)
            try:
                user = self.store.get('users', username)
            except KeyError:
                user = None
            if self.dummy_hash is None:
                self.dummy_hash = password_hash(secrets.token_urlsafe(32))
            matched = password_matches(password, user['_password_hash'] if user else self.dummy_hash)
            if not user or not user['enabled'] or not matched:
                for item in keys:
                    entry = self.failures.setdefault(item, {'count': 0, 'until': now + 900})
                    entry['count'] += 1
                raise AuthError('账号或密码错误')
            self.failures.pop(key, None)
            token = secrets.token_urlsafe(32)
            session = {'user_id': user['id'], 'version': user['_version'], 'csrf': secrets.token_urlsafe(32),
                       'expires': now + SESSION_LIFETIME, 'seen': now}
            self.sessions[hashlib.sha256(token.encode()).hexdigest()] = session
            return token, self._identity(user, session)

    @staticmethod
    def _identity(user, session):
        return {'user': public_user(user), 'permissions': ROLES[user['role']]['permissions'], 'token': session['csrf']}

    def authenticate(self, token):
        if not token or len(token) > 128:
            return None
        with self.lock:
            now = time.time()
            self._prune(now)
            session = self.sessions.get(hashlib.sha256(token.encode()).hexdigest())
            if not session:
                return None
            user = self.store.get('users', session['user_id'])
            if not user['enabled'] or user['_version'] != session['version']:
                return None
            session['seen'] = now
            return self._identity(user, session)

    def logout(self, token):
        with self.lock:
            self.sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)

    def change_password(self, identifier, current, password):
        validate_password(password)
        if not isinstance(current, str) or len(current) > 256:
            raise ValueError('当前密码错误')
        with self.lock:
            user = self.store.get('users', identifier)
            if not password_matches(current, user['_password_hash']):
                raise ValueError('当前密码错误')
            if password == current:
                raise ValueError('新密码不能与当前密码相同')
            user.update(_password_hash=password_hash(password), _version=user['_version'] + 1,
                        must_change_password=False, updated_at=time.time())
            self.store.replace('users', user)
            self._revoke(identifier)


def main():
    import argparse
    import sys
    from .service import OcService
    parser = argparse.ArgumentParser(description='仅为空 OC 初始化管理员，密码从标准输入读取')
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--username', required=True)
    args = parser.parse_args()
    service = OcService(args.state_dir, database_url=os.environ.get('WBOT_OC_DATABASE_URL'),
                        namespace=os.environ.get('WBOT_OC_NAMESPACE', 'wbot_oc'))
    try:
        service.auth.bootstrap(args.username, sys.stdin.readline(1024).rstrip('\r\n'))
        print('Administrator initialized; password change required at first login.')
    finally:
        service.close()


if __name__ == '__main__':
    main()
