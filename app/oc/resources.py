"""Environment 资源组与可绑定流程参数的普通配置 Asset。"""
import math
import time
from uuid import uuid4

from app.automation_package import resolve_parameters


def text(value, label, limit=120):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{label} 必须为 1–{limit} 字符的非空文本')
    return value.strip()


class Resources:
    def __init__(self, store, lock):
        self.store = store
        self.lock = lock

    def _values(self, table, identifier, body, fields):
        if not isinstance(body, dict) or body.keys() - fields:
            raise ValueError('包含不支持的资源字段')
        existing = self.store.get(table, identifier) if identifier else {}
        values = dict(existing, **body)
        values['name'] = text(values.get('name'), '名称')
        if any(item['id'] != identifier and item['name'].casefold() == values['name'].casefold()
               for item in self.store.list(table)):
            raise ValueError('名称已存在，请使用不同的名称')
        description = values.setdefault('description', '')
        if not isinstance(description, str) or len(description) > 2000:
            raise ValueError('说明最多 2000 字符')
        return values

    def _save(self, table, identifier, values):
        values.update(id=identifier or uuid4().hex, updated_at=time.time())
        if identifier:
            self.store.replace(table, values)
        else:
            values['created_at'] = values['updated_at']
            self.store.insert(table, values)
        return values

    def save_environment(self, identifier, body):
        with self.lock:
            values = self._values('environments', identifier, body,
                                  {'name', 'description', 'robot_ids', 'enabled'})
            members = values.setdefault('robot_ids', [])
            if (not isinstance(members, list) or len(members) > 1000
                    or any(not isinstance(item, str) for item in members) or len(set(members)) != len(members)):
                raise ValueError('robot_ids 必须是不重复的 Robot ID 列表，最多 1000 个')
            previous = self.store.get('environments', identifier)['robot_ids'] if identifier else []
            for member in members:
                device = self.store.get('devices', member)
                if device.get('binding_state', 'approved') != 'approved' and member not in previous:
                    raise ValueError('只能添加已批准的 Robot')
            if type(values.setdefault('enabled', True)) is not bool:
                raise ValueError('enabled 必须是布尔值')
            return self._save('environments', identifier, values)

    def save_asset(self, identifier, body):
        with self.lock:
            values = self._values('assets', identifier, body, {'name', 'description', 'type', 'value'})
            kind, value = values.get('type'), values.get('value')
            valid = ((kind == 'string' and isinstance(value, str) and len(value) <= 16384)
                     or (kind == 'boolean' and type(value) is bool)
                     or (kind == 'integer' and type(value) is int and abs(value) <= 2 ** 53 - 1)
                     or (kind == 'number' and type(value) in (int, float) and abs(value) <= 2 ** 53 - 1
                         and math.isfinite(value)))
            if not valid:
                raise ValueError('Asset 值与类型不符；仅支持文本、有限数字、整数和布尔配置')
            if identifier and values['type'] != self.store.get('assets', identifier)['type']:
                if any(identifier in process.get('asset_bindings', {}).values()
                       for process in self.store.list('processes')):
                    raise RuntimeError('Asset 已绑定流程，解除绑定后才能修改类型')
            values['revision'] = values.get('revision', 0) + 1
            return self._save('assets', identifier, values)

    def bindings(self, manifest, bindings):
        if not isinstance(bindings, dict) or bindings.keys() - manifest['parameters'].keys():
            raise ValueError('Asset 绑定必须对应发布包中已有的参数')
        resolved, snapshots = {}, {}
        for parameter, identifier in bindings.items():
            if identifier != text(identifier, 'Asset ID'):
                raise ValueError('Asset ID 不能包含首尾空白')
            asset = self.store.get('assets', identifier)
            expected = manifest['parameters'][parameter]['type']
            if asset['type'] != expected and not (expected == 'number' and asset['type'] == 'integer'):
                raise ValueError(f'参数 {parameter} 与 Asset 类型不一致')
            resolved[parameter] = asset['value']
            snapshots[parameter] = {'id': identifier, 'name': asset['name'], 'revision': asset['revision']}
        optional = dict(manifest, parameters={key: dict(value, required=False)
                                             for key, value in manifest['parameters'].items()})
        resolve_parameters(optional, resolved)
        return resolved, snapshots

    def resolve_inputs(self, process, manifest, parameters):
        assets, snapshots = self.bindings(manifest, process.get('asset_bindings', {}))
        inputs = process['defaults'] | assets | parameters
        snapshots = {key: value for key, value in snapshots.items() if key not in parameters}
        return resolve_parameters(manifest, inputs), snapshots

    def delete(self, table, identifier):
        if table not in {'environments', 'assets'}:
            raise ValueError('不支持删除该类型')
        with self.lock:
            self.store.get(table, identifier)
            for process in self.store.list('processes'):
                referenced = (process.get('environment_id') == identifier if table == 'environments'
                              else identifier in process.get('asset_bindings', {}).values())
                if referenced:
                    raise RuntimeError('资源仍被流程引用，请先修改流程部署')
            if table == 'environments' and any(job.get('environment_id') == identifier and job['state'] == 'queued'
                                               for job in self.store.list('jobs')):
                raise RuntimeError('环境仍有排队任务，请先取消任务')
            self.store.delete(table, identifier)
