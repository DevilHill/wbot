"""共享元素的规范快照、差异和字段级三方合并。"""
import json

from .elements import normalize_element


ELEMENT_FIELDS = ('id', 'name', 'group', 'xpath', 'url', 'frame', 'description')
MAX_SNAPSHOT_BYTES = 1536 * 1024


def canonical_items(items):
    if not isinstance(items, list) or len(items) > 10000:
        raise ValueError('元素快照必须为最多 10000 条记录的数组')
    normalized, identifiers, names = [], set(), set()
    for record in items:
        if not isinstance(record, dict) or not isinstance(record.get('id'), str) or not record['id']:
            raise ValueError('共享元素必须包含稳定的 id')
        value = normalize_element(record)
        item = {field: value[field] for field in ELEMENT_FIELDS}
        identity = (item['group'], item['name'])
        if item['id'] in identifiers:
            raise ValueError(f'快照中存在重复元素 id：{item["id"]}')
        if identity in names:
            raise ValueError(f'元素名称冲突：{item["group"]}/{item["name"]}；请修改名称后重新提交')
        identifiers.add(item['id'])
        names.add(identity)
        normalized.append(item)
    normalized.sort(key=lambda item: item['id'])
    if len(json.dumps(normalized, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_SNAPSHOT_BYTES:
        raise ValueError('元素快照超过 1.5 MiB')
    return normalized


def diff_items(before, after):
    old = {item['id']: item for item in canonical_items(before)}
    new = {item['id']: item for item in canonical_items(after)}
    changes = []
    for identifier in sorted(old.keys() | new.keys()):
        previous, current = old.get(identifier), new.get(identifier)
        if previous == current:
            continue
        kind = 'added' if previous is None else 'deleted' if current is None else 'modified'
        changes.append({'id': identifier, 'type': kind, 'before': previous, 'after': current})
    return changes


def merge_items(base, main, source):
    snapshots = [{item['id']: item for item in canonical_items(items)} for items in (base, main, source)]
    baseline, current, incoming = snapshots
    merged, conflicts = [], []
    for identifier in sorted(baseline.keys() | current.keys() | incoming.keys()):
        before, ours, theirs = (snapshot.get(identifier) for snapshot in snapshots)
        if ours == theirs or theirs == before:
            chosen = ours
        elif ours == before:
            chosen = theirs
        elif before is None or ours is None or theirs is None:
            conflicts.append({'id': identifier, 'field': '__record__', 'base': before, 'main': ours, 'source': theirs})
            chosen = ours
        else:
            chosen = {'id': identifier}
            for field in ELEMENT_FIELDS[1:]:
                left, right, previous = ours[field], theirs[field], before[field]
                if left == right or right == previous:
                    chosen[field] = left
                elif left == previous:
                    chosen[field] = right
                else:
                    conflicts.append({'id': identifier, 'field': field, 'base': previous, 'main': left, 'source': right})
                    chosen[field] = left
        if chosen is not None:
            merged.append(chosen)
    # 合并候选允许暂存同名项；真正写入版本前统一校验，不能悄悄丢弃任意元素。
    return {'items': merged, 'conflicts': conflicts}
