"""共享元素管理与开发者接口：主分支写入仅向管理端开放。"""
import re


def _parts(path):
    parts = path.strip('/').split('/')[3:]
    if not parts or parts[0] != 'repositories':
        raise KeyError('元素接口不存在')
    for index in (1, 3):
        if len(parts) > index and not re.fullmatch(r'[0-9a-f]{32}', parts[index]):
            raise ValueError('元素仓库标识格式无效')
    return parts


def _read(service, parts):
    if len(parts) == 1:
        return {'items': service.list_repositories()}
    if len(parts) == 2:
        return service.get_repository(parts[1])
    if len(parts) == 4 and parts[2] == 'commits':
        return {'commit': service.get_commit(parts[1], parts[3])}
    if len(parts) == 4 and parts[2] == 'requests':
        return service.review_request(parts[1], parts[3])
    raise KeyError('元素接口不存在')


def admin_elements(service, method, path, body=None):
    parts = _parts(path)
    if method == 'GET':
        return 200, _read(service, parts)
    if method == 'POST':
        if len(parts) == 1:
            return 201, {'repository': service.create_repository(body)}
        if len(parts) == 3 and parts[2] == 'restore':
            return 200, {'commit': service.restore(parts[1], body)}
        if len(parts) == 5 and parts[2] == 'requests':
            if parts[4] == 'merge':
                return 200, service.merge_request(parts[1], parts[3], body)
            if parts[4] == 'close':
                return 200, {'request': service.close_request(parts[1], parts[3], body)}
    raise KeyError('元素管理接口不存在')


def developer_elements(service, device, method, path, body=None):
    operation = re.fullmatch(r'/api/agent/elements/operations/([A-Za-z0-9_-]{1,128})', path)
    if method == 'GET' and operation:
        return 200, {'result': service.get_device_operation(device, operation.group(1))}
    parts = _parts(path)
    if method == 'GET':
        return 200, _read(service, parts)
    if method == 'POST':
        if len(parts) == 3 and parts[2] == 'branches':
            return 201, {'branch': service.create_branch(parts[1], device, body)}
        if len(parts) == 5 and parts[2] == 'branches':
            if parts[4] == 'commits':
                return 201, service.commit_branch(parts[1], parts[3], device, body)
            if parts[4] == 'requests':
                return 201, {'request': service.open_request(parts[1], parts[3], device, body)}
    raise KeyError('开发者元素接口不存在')
