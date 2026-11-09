"""开发者工作副本：固定连接身份，提交不可变快照并保留未同步改动。"""
import hashlib
import json
from pathlib import Path
import re
import threading

from wbot.element_versions import canonical_items, diff_items, merge_items
from .element_workspace import ElementWorkspace
from .remote_client import GatewayError


REMOTE_ROOT = '/api/agent/elements/repositories'
WRITE_FIELDS = {'library_path', 'expected_fingerprint', 'expected_branch', 'expected_head', 'request_id'}
ACTION_FIELDS = {'connect': {'repository_id', 'branch_name'}, 'commit': {'message'},
                 'request': {'title', 'description'}, 'pull': set()}


def fingerprint(items):
    content = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}', value):
        raise ValueError('共享元素仓库或分支标识无效')
    return value


def _identity(settings):
    return {key: settings[key] for key in ('server_url', 'device_id')}


def _bound_to(binding, settings):
    if not binding or any(binding[key] != settings[key] for key in ('server_url', 'device_id')):
        raise RuntimeError('当前 Assistant 身份与此工作副本不一致，请连接原 OC 和设备身份后重试')


class SharedElementService:
    def __init__(self, connection):
        self.connection = connection
        self._operation = threading.Lock()

    @staticmethod
    def _workspace(body):
        value = body.get('library_path')
        if not isinstance(value, str) or not value.strip() or len(value) > 4096 or '\x00' in value:
            raise ValueError('请配置本机元素库完整路径')
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError('元素库路径必须为本机完整路径')
        return ElementWorkspace(path.resolve())

    def dispatch(self, action, body):
        if action == 'repositories':
            if body:
                raise ValueError('仓库列表不接受额外参数')
            with self.connection.remote_session() as (settings, client):
                response = client.request(REMOTE_ROOT)
                response['connection'] = {key: settings[key] for key in ('server_url', 'device_id', 'device_name')}
                return response
        if action not in {'status', 'diff'} | ACTION_FIELDS.keys():
            raise KeyError('共享元素操作不存在')
        required = {'library_path'} if action in ('status', 'diff') else WRITE_FIELDS | ACTION_FIELDS[action]
        if set(body) != required:
            raise ValueError('共享元素操作字段不完整或包含未知字段')
        workspace = self._workspace(body)
        if action == 'status':
            return self.status(workspace)
        if action == 'diff':
            items, state = workspace.snapshot()
            return {'before': state['baseline'], 'after': items,
                    'changes': diff_items(state['baseline'], items), 'fingerprint': fingerprint(items)}
        if not isinstance(body['request_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', body['request_id']):
            raise ValueError('request_id 必须为 1–128 位字母、数字、下划线或连字符')
        with self._operation, self.connection.remote_session() as (settings, client):
            result = self._write(workspace, action, body, settings, client)
        return dict(self.status(workspace), **result)

    def status(self, workspace):
        recovery_error = self._recover_pending(workspace)
        items, state = workspace.snapshot()
        binding = state['binding']
        result = {'binding': binding, 'dirty': items != state['baseline'],
                  'changes': diff_items(state['baseline'], items), 'fingerprint': fingerprint(items),
                  'branch_status': None, 'request': None, 'remote_error': recovery_error,
                  'pending_action': state['pending']['action'] if state['pending'] else None}
        if not binding:
            return result
        try:
            with self.connection.remote_session() as (settings, client):
                _bound_to(binding, settings)
                detail = client.request(REMOTE_ROOT + '/' + binding['repository_id'])
            branch = next((value for value in detail['branches'] if value['id'] == binding['branch_id']), None)
            if branch is None:
                raise RuntimeError('原共享分支已不存在，请联系管理员核对仓库')
            result['branch_status'] = branch['status']
            result['request'] = next((value for value in detail['requests'] if value['branch_id'] == binding['branch_id']), None)
        except (OSError, ValueError, RuntimeError) as exc:
            result['remote_error'] = str(exc)
        return result

    def _recover_pending(self, workspace):
        with self._operation:
            _, state = workspace.snapshot()
            pending = state['pending']
            if not pending or pending['action'] == 'pull':
                return ''
            try:
                with self.connection.remote_session() as (settings, client):
                    _bound_to(pending['identity'], settings)
                    response = client.request('/api/agent/elements/operations/' + pending['request_id'])
                accepted = response['result']
                if pending['action'] == 'connect':
                    accepted = {'branch': accepted}
                elif pending['action'] == 'request':
                    accepted = {'request': accepted}
                self._finish(workspace, state, pending, accepted)
            except GatewayError as exc:
                return '' if exc.status == 404 else str(exc)
            except (OSError, ValueError, RuntimeError) as exc:
                return str(exc)
            return ''

    @staticmethod
    def _check_expected(state, items, body):
        binding = state['binding'] or {}
        if binding.get('branch_id') != body['expected_branch'] or binding.get('head') != body['expected_head']:
            raise RuntimeError('工作副本分支或版本已变化，请刷新后重新确认')
        if fingerprint(items) != body['expected_fingerprint']:
            raise RuntimeError('本地元素已变化，请重新查看差异后提交；未覆盖任何元素')

    @staticmethod
    def _intent(action, body):
        # 重试继续此前已确认的快照，后来发生的编辑仍留作下一次提交。
        return {'action': action, 'fields': {key: body[key] for key in ACTION_FIELDS[action]},
                'expected_branch': body['expected_branch'], 'expected_head': body['expected_head']}

    def _write(self, workspace, action, body, settings, client):
        items, state = workspace.snapshot()
        intent = self._intent(action, body)
        last = state.get('last_operation')
        if last and last['request_id'] == body['request_id']:
            if last['intent'] != intent or last['identity'] != _identity(settings):
                raise RuntimeError('此请求号已用于其他共享元素操作')
            return last['result']
        pending = state['pending']
        if pending:
            if pending['intent'] != intent or pending['identity'] != _identity(settings):
                raise RuntimeError('上次共享元素操作尚未确认，请连接原 OC 并使用相同参数重试')
        else:
            self._check_expected(state, items, body)
            pending = self._prepare(action, body, state, items, settings, client)
            pending.update(action=action, intent=intent, identity=_identity(settings), request_id=body['request_id'])
            updated = dict(state, pending=pending)
            workspace.save(state, updated, expected_items=items)
            state = updated
        try:
            response = client.request(pending['endpoint'], pending['payload']) if pending.get('endpoint') else {}
        except GatewayError as exc:
            if exc.status in (400, 403, 404, 409, 413):
                workspace.save(state, dict(state, pending=None))
            raise
        try:
            return self._finish(workspace, state, pending, response)
        except RuntimeError:
            if action == 'pull':
                workspace.save(state, dict(state, pending=None))
            raise

    def _prepare(self, action, body, state, items, settings, client):
        if action == 'connect':
            repository_id = _identifier(body['repository_id'])
            detail = client.request(REMOTE_ROOT + '/' + repository_id)
            binding = state['binding']
            carry_baseline = None
            if binding and binding['repository_id'] == repository_id and _identity(binding) == _identity(settings):
                branch = next((value for value in detail['branches'] if value['id'] == binding['branch_id']), None)
                if branch and branch['status'] == 'merged':
                    carry_baseline = state['baseline']
            if binding and items != state['baseline'] and carry_baseline is None:
                raise RuntimeError('当前工作副本有未提交修改；仅可从同一仓库已合并的分支携带改动创建新分支')
            if carry_baseline is None:
                canonical_items(self._combine(detail['head']['items'], items))
            else:
                self._carry_changes(carry_baseline, detail['head']['items'], items)
            return {'endpoint': REMOTE_ROOT + '/' + repository_id + '/branches',
                    'payload': {'name': body['branch_name'], 'base_commit': detail['head']['id'],
                                'request_id': body['request_id']},
                    'baseline': canonical_items(detail['head']['items']),
                    'initial_items': items,
                    'carry_baseline': carry_baseline,
                    'repository_name': detail['repository']['name'], 'repository_id': repository_id}
        binding = state['binding']
        _bound_to(binding, settings)
        repository_path = REMOTE_ROOT + '/' + binding['repository_id']
        branch_path = repository_path + '/branches/' + binding['branch_id']
        if action == 'commit':
            if items == state['baseline']:
                raise ValueError('没有本地元素改动，无需提交')
            return {'endpoint': branch_path + '/commits', 'baseline': items,
                    'payload': {'expected_head': binding['head'], 'message': body['message'],
                                'items': items, 'request_id': body['request_id']}}
        if items != state['baseline']:
            raise RuntimeError('有未提交的本地元素修改，请先提交后再申请合并或拉取主分支')
        if action == 'request':
            return {'endpoint': branch_path + '/requests',
                    'payload': {'expected_head': binding['head'], 'title': body['title'],
                                'description': body['description'], 'request_id': body['request_id']}}
        detail = client.request(repository_path)
        branch = next((item for item in detail['branches'] if item['id'] == binding['branch_id']), None)
        if branch is None or branch['status'] != 'merged':
            raise RuntimeError('个人分支尚未合并，不能用主分支覆盖；请先发起并完成合并申请')
        return {'baseline': canonical_items(detail['head']['items']), 'head': detail['head']['id'],
                'expected_items': items}

    @staticmethod
    def _combine(shared, local):
        combined = {item['id']: item for item in shared}
        combined.update({item['id']: item for item in local})
        return list(combined.values())

    @staticmethod
    def _carry_changes(base, main, local):
        merged = merge_items(base, main, local)
        if merged['conflicts']:
            fields = '、'.join(f'{item["id"]}/{item["field"]}' for item in merged['conflicts'][:5])
            raise RuntimeError('本地改动与最新主分支冲突，请对照主分支调整这些元素后重试：' + fields)
        return canonical_items(merged['items'])

    def _finish(self, workspace, state, pending, response):
        action = pending['action']
        binding = dict(state['binding']) if state['binding'] else None
        updated, result = dict(state, pending=None), {}
        expected_items, replacement = None, None
        if action == 'connect':
            branch = response['branch']
            binding = dict(pending['identity'], repository_id=pending['repository_id'],
                           repository_name=pending['repository_name'], branch_id=branch['id'],
                           branch_name=branch['name'], head=branch['head'], base_commit=branch['base_commit'])
            expected_items, current_state = workspace.snapshot()
            if current_state != state:
                raise RuntimeError('工作副本状态已变化，请重试之前的连接操作')
            if pending.get('carry_baseline') is not None:
                replacement = self._carry_changes(pending['carry_baseline'], pending['baseline'], expected_items)
            else:
                deleted = {item['id'] for item in pending['initial_items']} - {item['id'] for item in expected_items}
                replacement = [item for item in self._combine(pending['baseline'], expected_items)
                               if item['id'] not in deleted]
            updated['baseline'] = pending['baseline']
        elif action == 'commit':
            binding['head'] = response['commit']['id']
            updated['baseline'] = pending['baseline']
            result['commit'] = response['commit']
        elif action == 'request':
            result['request'] = response['request']
        else:
            binding['head'] = pending['head']
            updated['baseline'] = pending['baseline']
            expected_items, replacement = pending['expected_items'], pending['baseline']
        updated['binding'] = binding
        updated['last_operation'] = {key: pending[key] for key in ('request_id', 'intent', 'identity')}
        updated['last_operation']['result'] = result
        workspace.save(state, updated, expected_items=expected_items, replacement=replacement)
        return result
