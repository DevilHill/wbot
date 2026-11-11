"""账号认证的 HTTP 边界；管理权限与 Robot 凭据互相独立。"""
from http.cookies import SimpleCookie, CookieError
import os
import secrets

from .auth import AuthError, ROLES, PERMISSIONS, SESSION_LIFETIME


def cookie_token(handler):
    try:
        cookie = SimpleCookie(handler.headers.get('Cookie', ''))
        return cookie['wbot_session'].value if 'wbot_session' in cookie else ''
    except CookieError:
        return ''


def session_cookie(token):
    secure = '; Secure' if os.environ.get('WBOT_OC_SECURE_COOKIE') == '1' else ''
    return f'wbot_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_LIFETIME if token else 0}{secure}'


def required_permission(method, path):
    parts = path.strip('/').split('/')
    resource = parts[2] if len(parts) > 2 else ''
    if resource in ('users', 'roles'):
        return 'users.manage'
    if method == 'GET':
        return 'read'
    if resource == 'processes' and len(parts) == 5 and parts[4] in ('run', 'enqueue'):
        return 'jobs.run'
    if resource == 'jobs' and len(parts) == 5 and parts[4] == 'stop':
        return 'jobs.stop'
    return {'devices': 'robots.manage', 'environments': 'environments.manage', 'assets': 'assets.manage',
            'packages': 'packages.manage', 'processes': 'processes.manage', 'elements': 'elements.manage',
            'assistant-releases': 'releases.manage'}.get(resource)


def authorize(handler, path):
    if not path.startswith('/api/'):
        return True
    if path == '/api/oc/auth/login' and handler.command == 'POST':
        return True
    # The service token remains usable by local lifecycle/health checks only.
    if (path in ('/api/oc/health', '/api/oc/service/stop') and not handler.headers.get('X-WBot-Proxy')
            and secrets.compare_digest(handler.headers.get('X-WBot-Token', '').encode(), handler.server.token.encode())):
        return True
    identity = handler.server.service.auth.authenticate(cookie_token(handler))
    if not identity:
        raise AuthError('请登录管理账号')
    handler.identity = identity
    if path == '/api/oc/session' and handler.command == 'GET':
        return True
    if handler.command != 'GET' and not secrets.compare_digest(
            handler.headers.get('X-WBot-Token', '').encode(), identity['token'].encode()):
        raise AuthError('会话校验失败，请刷新页面', 403)
    if path in ('/api/oc/auth/password', '/api/oc/auth/logout') and handler.command == 'POST':
        return True
    if identity['user']['must_change_password']:
        raise AuthError('请先修改初始密码', 403)
    permission = required_permission(handler.command, path)
    if permission is None or permission not in identity['permissions']:
        raise AuthError('当前角色无权执行此操作', 403)
    return True


def route(handler, method, path):
    auth = handler.server.service.auth
    if path == '/api/oc/auth/login' and method == 'POST':
        body = handler._read_json()
        address = handler.headers.get('X-Forwarded-For', '') if handler.headers.get('X-WBot-Proxy') else handler.client_address[0]
        token, identity = auth.login(body.get('username'), body.get('password'), address)
        handler.response_cookie = session_cookie(token)
        handler._json(200, handler.session_payload(identity))
    elif path == '/api/oc/auth/logout' and method == 'POST':
        handler._read_json()
        auth.logout(cookie_token(handler))
        handler.response_cookie = session_cookie('')
        handler._json(200, {'ok': True})
    elif path == '/api/oc/auth/password' and method == 'POST':
        body = handler._read_json()
        auth.change_password(handler.identity['user']['id'], body.get('current_password'), body.get('password'))
        handler.response_cookie = session_cookie('')
        handler._json(200, {'ok': True})
    elif path == '/api/oc/users' and method == 'GET':
        handler._json(200, {'items': auth.list_users()})
    elif path == '/api/oc/roles' and method == 'GET':
        handler._json(200, {'items': [dict(value, id=key) for key, value in ROLES.items()], 'permissions': PERMISSIONS})
    elif path == '/api/oc/users' and method == 'POST':
        handler._json(201, {'user': auth.create_user(handler._read_json())})
    elif path.startswith('/api/oc/users/') and method == 'PATCH':
        handler._json(200, {'user': auth.update_user(path.removeprefix('/api/oc/users/'), handler._read_json())})
    else:
        return False
    return True
