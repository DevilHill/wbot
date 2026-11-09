"""受保护主分支、开发者提交与可审阅的共享元素合并。"""
import hashlib
import re
import time
from uuid import uuid4

from wbot.element_versions import canonical_items, diff_items, merge_items
from .element_store import ElementStore, encode


ADMIN = {'id': 'local-operator', 'name': '本地操作员', 'kind': 'admin'}


def _text(value, label, maximum=200, empty=False):
    if not isinstance(value, str) or '\x00' in value or len(value) > maximum or (not empty and not value.strip()):
        qualifier = '' if empty else '非空'
        raise ValueError(f'{label} 必须为最多 {maximum} 字符的{qualifier}文本')
    return value.strip()


def _body(body, required, optional=()):
    required = set(required) | {'request_id'}
    if not isinstance(body, dict) or required - body.keys() or body.keys() - required - set(optional):
        raise ValueError('元素仓库操作字段不完整或包含未知字段')
    _request_id(body['request_id'])
    for field in ('base_commit', 'expected_head', 'expected_main', 'expected_source', 'commit_id'):
        if field in body and (not isinstance(body[field], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', body[field])):
            raise ValueError(f'{field} 必须为有效的提交 ID')


def _request_id(identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identifier):
        raise ValueError('request_id 必须为 1–128 位字母、数字、下划线或连字符')


def _device_actor(device):
    return {'id': _text(device.get('id'), '设备 ID', 128),
            'name': _text(device.get('name'), '设备名称', 120), 'kind': 'device'}


def _expect(actual, expected, label):
    if actual != expected:
        raise RuntimeError(f'{label} 已变化，请刷新差异后重试')


class ElementRepositoryService:
    def __init__(self, path):
        self.store = ElementStore(path)

    def _mutate(self, actor, action, targets, body, operation):
        scope = actor['kind'] + ':' + actor['id']
        fingerprint = hashlib.sha256(encode({'action': action, 'targets': targets, 'body': body}).encode('utf-8')).hexdigest()
        with self.store.connection(write=True) as database:
            previous = self.store.operation(database, scope, body['request_id'])
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise RuntimeError('此 request_id 已用于其他内容，请重新发起操作')
                return previous['result']
            result = operation(database)
            self.store.save_operation(database, scope, body['request_id'], fingerprint, result)
            return result

    def _new_commit(self, database, repository_id, items, parents, message, actor, *, restored_from=None):
        commit = {'id': uuid4().hex, 'repository_id': repository_id, 'parents': parents,
                  'message': message, 'author': actor, 'created_at': time.time(), 'items': items}
        if restored_from is not None:
            commit['restored_from'] = restored_from
        self.store.save_commit(database, commit)
        return commit

    def list_repositories(self):
        with self.store.connection() as database:
            return self.store.list(database, 'repository')

    def create_repository(self, body):
        _body(body, ('name',), ('description', 'items'))
        name = _text(body['name'], '仓库名称', 120)
        description = _text(body.get('description', ''), '仓库描述', 4000, empty=True)
        items = canonical_items(body.get('items', []))
        def create(database):
            if any(record['name'] == name for record in self.store.list(database, 'repository')):
                raise ValueError('已存在同名元素仓库')
            identifier = uuid4().hex
            commit = self._new_commit(database, identifier, items, [], '创建元素仓库', ADMIN)
            repository = {'id': identifier, 'name': name, 'description': description,
                          'head': commit['id'], 'created_at': commit['created_at']}
            self.store.save(database, 'repository', repository, identifier)
            return repository
        return self._mutate(ADMIN, 'create_repository', [], body, create)

    def get_repository(self, repository_id):
        with self.store.connection() as database:
            repository = self.store.get(database, 'repository', repository_id)
            return {'repository': repository, 'head': self.store.commit(database, repository_id, repository['head']),
                    'branches': self.store.list(database, 'branch', repository_id),
                    'requests': self.store.list(database, 'request', repository_id),
                    'commits': self.store.history(database, repository_id)}

    def get_commit(self, repository_id, commit_id):
        with self.store.connection() as database:
            return self.store.commit(database, repository_id, commit_id)

    def get_device_operation(self, device, request_id):
        _request_id(request_id)
        actor = _device_actor(device)
        with self.store.connection() as database:
            operation = self.store.operation(database, 'device:' + actor['id'], request_id)
            if operation is None:
                raise KeyError('未找到该设备已接受的元素操作')
            return operation['result']

    def create_branch(self, repository_id, device, body):
        _body(body, ('name', 'base_commit'))
        name = _text(body['name'], '分支名称', 120)
        actor = _device_actor(device)
        if name.lower() == 'main':
            raise ValueError('main 是受保护主分支，请使用其他分支名称')
        def create(database):
            self.store.get(database, 'repository', repository_id)
            self.store.commit(database, repository_id, body['base_commit'])
            if any(branch['name'] == name for branch in self.store.list(database, 'branch', repository_id)):
                raise ValueError('已存在同名分支，请使用其他名称')
            now = time.time()
            branch = {'id': uuid4().hex, 'repository_id': repository_id, 'name': name,
                      'device_id': actor['id'], 'device_name': actor['name'], 'base_commit': body['base_commit'],
                      'head': body['base_commit'], 'status': 'open', 'created_at': now, 'updated_at': now}
            self.store.save(database, 'branch', branch, repository_id)
            return branch
        return self._mutate(actor, 'create_branch', [repository_id], body, create)

    def _owned_branch(self, database, repository_id, branch_id, actor):
        branch = self.store.get(database, 'branch', branch_id, repository_id)
        if branch['device_id'] != actor['id']:
            raise PermissionError('只能修改当前设备拥有的分支')
        if branch['status'] != 'open':
            raise RuntimeError('该分支已经合并，请从最新主分支创建新分支')
        return branch

    def commit_branch(self, repository_id, branch_id, device, body):
        _body(body, ('expected_head', 'message', 'items'))
        actor = _device_actor(device)
        message = _text(body['message'], '提交说明', 2000)
        items = canonical_items(body['items'])
        def commit(database):
            branch = self._owned_branch(database, repository_id, branch_id, actor)
            _expect(branch['head'], body['expected_head'], '分支版本')
            previous = self.store.commit(database, repository_id, branch['head'])
            if previous['items'] == items:
                raise ValueError('没有元素改动，无需创建新提交')
            saved = self._new_commit(database, repository_id, items, [branch['head']], message, actor)
            branch.update(head=saved['id'], updated_at=saved['created_at'])
            self.store.save(database, 'branch', branch, repository_id)
            for request in self.store.list(database, 'request', repository_id):
                if request['branch_id'] == branch_id and request['state'] == 'open':
                    request.update(source_head=saved['id'], updated_at=saved['created_at'])
                    self.store.save(database, 'request', request, repository_id)
            return {'branch': branch, 'commit': saved}
        return self._mutate(actor, 'commit_branch', [repository_id, branch_id], body, commit)

    def open_request(self, repository_id, branch_id, device, body):
        _body(body, ('expected_head', 'title'), ('description',))
        actor = _device_actor(device)
        title = _text(body['title'], '合并申请标题', 200)
        description = _text(body.get('description', ''), '合并申请说明', 10000, empty=True)
        def create(database):
            branch = self._owned_branch(database, repository_id, branch_id, actor)
            _expect(branch['head'], body['expected_head'], '分支版本')
            if branch['head'] == branch['base_commit']:
                raise ValueError('分支尚无新提交，不能发起合并申请')
            for request in self.store.list(database, 'request', repository_id):
                if request['branch_id'] == branch_id and request['state'] == 'open':
                    raise RuntimeError('此分支已有待处理合并申请；继续提交会自动更新该申请')
            now = time.time()
            request = {'id': uuid4().hex, 'repository_id': repository_id, 'branch_id': branch_id,
                       'branch_name': branch['name'], 'device_id': actor['id'], 'device_name': actor['name'],
                       'title': title, 'description': description, 'state': 'open', 'source_head': branch['head'],
                       'base_commit': branch['base_commit'], 'created_at': now, 'updated_at': now}
            self.store.save(database, 'request', request, repository_id)
            return request
        return self._mutate(actor, 'open_request', [repository_id, branch_id], body, create)

    def _review(self, database, repository_id, request_id):
        repository = self.store.get(database, 'repository', repository_id)
        request = self.store.get(database, 'request', request_id, repository_id)
        base = self.store.commit(database, repository_id, request['base_commit'])
        main = self.store.commit(database, repository_id, repository['head'])
        source = self.store.commit(database, repository_id, request['source_head'])
        merged = merge_items(base['items'], main['items'], source['items'])
        return {'request': request, 'main_head': main['id'], 'source_head': source['id'],
                'base_commit': base['id'], 'changes': diff_items(base['items'], source['items']),
                'merged_items': merged['items'], 'conflicts': merged['conflicts']}

    def review_request(self, repository_id, request_id):
        with self.store.connection() as database:
            return self._review(database, repository_id, request_id)

    @staticmethod
    def _resolve(review, resolutions):
        if not isinstance(resolutions, list):
            raise ValueError('冲突解决必须为数组')
        required = {(conflict['id'], conflict['field']) for conflict in review['conflicts']}
        submitted = {}
        for resolution in resolutions:
            if not isinstance(resolution, dict) or set(resolution) != {'id', 'field', 'value'}:
                raise ValueError('冲突解决须包含 id、field、value')
            if not isinstance(resolution['id'], str) or not isinstance(resolution['field'], str):
                raise ValueError('冲突元素和字段必须为文本')
            key = (resolution['id'], resolution['field'])
            if key not in required or key in submitted:
                raise ValueError('冲突解决包含重复字段或未发生冲突的字段')
            submitted[key] = resolution['value']
        if required - submitted.keys():
            raise RuntimeError('仍有未解决的元素冲突，请逐项选择后合并')
        items = {item['id']: dict(item) for item in review['merged_items']}
        for (identifier, field), value in submitted.items():
            if field != '__record__':
                items[identifier][field] = value
            elif value is None:
                items.pop(identifier, None)
            elif isinstance(value, dict) and value.get('id') == identifier:
                items[identifier] = value
            else:
                raise ValueError('整条元素冲突只能保留相同 id 的元素，或选择删除')
        return canonical_items(list(items.values()))

    def merge_request(self, repository_id, request_id, body):
        _body(body, ('expected_main', 'expected_source', 'resolutions'))
        def merge(database):
            review = self._review(database, repository_id, request_id)
            request = review['request']
            if request['state'] != 'open':
                raise RuntimeError('该合并申请已经处理')
            _expect(review['main_head'], body['expected_main'], '主分支版本')
            _expect(review['source_head'], body['expected_source'], '申请版本')
            items = self._resolve(review, body['resolutions'])
            commit = self._new_commit(database, repository_id, items,
                [review['main_head'], review['source_head']], '合并：' + request['title'], ADMIN)
            repository = self.store.get(database, 'repository', repository_id)
            repository['head'] = commit['id']
            branch = self.store.get(database, 'branch', request['branch_id'], repository_id)
            branch.update(status='merged', updated_at=commit['created_at'])
            request.update(state='merged', merge_commit=commit['id'], updated_at=commit['created_at'])
            self.store.save(database, 'repository', repository, repository_id)
            self.store.save(database, 'branch', branch, repository_id)
            self.store.save(database, 'request', request, repository_id)
            return {'request': request, 'commit': commit}
        return self._mutate(ADMIN, 'merge_request', [repository_id, request_id], body, merge)

    def close_request(self, repository_id, request_id, body):
        _body(body, ('expected_source', 'reason'))
        reason = _text(body['reason'], '关闭说明', 2000)
        def close(database):
            request = self.store.get(database, 'request', request_id, repository_id)
            if request['state'] != 'open':
                raise RuntimeError('该合并申请已经处理')
            _expect(request['source_head'], body['expected_source'], '申请版本')
            request.update(state='closed', close_reason=reason, updated_at=time.time())
            self.store.save(database, 'request', request, repository_id)
            return request
        return self._mutate(ADMIN, 'close_request', [repository_id, request_id], body, close)

    def restore(self, repository_id, body):
        _body(body, ('expected_head', 'commit_id', 'message'))
        message = _text(body['message'], '恢复说明', 2000)
        def restore(database):
            repository = self.store.get(database, 'repository', repository_id)
            _expect(repository['head'], body['expected_head'], '主分支版本')
            previous = self.store.commit(database, repository_id, body['commit_id'])
            commit = self._new_commit(database, repository_id, previous['items'], [repository['head']], message, ADMIN,
                                      restored_from=previous['id'])
            repository['head'] = commit['id']
            self.store.save(database, 'repository', repository, repository_id)
            return commit
        return self._mutate(ADMIN, 'restore', [repository_id], body, restore)
