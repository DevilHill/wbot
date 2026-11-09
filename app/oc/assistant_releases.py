"""Immutable Assistant archives with explicit, device-scoped publication."""
from pathlib import Path
import shutil
import tempfile
import time

from app.assistant_release import file_digest, inspect_release, version_key
from .store import public_record


class AssistantReleases:
    def __init__(self, state_dir, store, lock):
        self.directory = Path(state_dir) / 'assistant-releases'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.store = store
        self.lock = lock

    def list(self):
        return [public_record(record) for record in self.store.list('assistant_releases')]

    def upload(self, source):
        with self.lock, tempfile.TemporaryDirectory(dir=self.directory, prefix='.upload-') as directory:
            copied = Path(directory) / 'release.zip'
            shutil.copyfile(source, copied)
            metadata = inspect_release(copied)
            identifier = metadata['version']
            if any(item['id'] == identifier for item in self.list()):
                raise FileExistsError('此版本已上传；请使用新版本号，已发布内容不可覆盖')
            destination = self.directory / f'{identifier}.zip'
            record = dict(metadata, id=identifier, size=copied.stat().st_size, sha256=file_digest(copied),
                          published=False, device_ids=[], created_at=time.time(), _archive=str(destination))
            copied.replace(destination)
            self.store.insert('assistant_releases', record)
            return public_record(record)

    def publish(self, identifier, body):
        if (set(body) != {'published', 'device_ids'} or type(body['published']) is not bool
                or not isinstance(body['device_ids'], list) or len(body['device_ids']) > 10000
                or any(not isinstance(value, str) for value in body['device_ids'])):
            raise ValueError('发布设置需要 published 布尔值和 device_ids 列表')
        with self.lock:
            record = self.store.get('assistant_releases', identifier)
            for device_id in body['device_ids'] if body['published'] else []:
                device = self.store.get('devices', device_id)
                if device.get('transport') != 'agent' or device.get('binding_state') != 'approved':
                    raise ValueError('只能向已批准的远程设备发布更新')
            record.update(published=body['published'], device_ids=sorted(set(body['device_ids'])))
            self.store.replace('assistant_releases', record)
            return public_record(record)

    @staticmethod
    def _eligible(record, device):
        return (device.get('binding_state') == 'approved' and record['published']
                and (not record['device_ids'] or device['id'] in record['device_ids']))

    def latest(self, device, current):
        current = version_key(current)
        candidates = [record for record in self.list()
                      if self._eligible(record, device) and version_key(record['version']) > current]
        return max(candidates, key=lambda record: version_key(record['version']), default=None)

    def for_device(self, device, identifier):
        record = self.store.get('assistant_releases', identifier)
        if not self._eligible(record, device):
            raise PermissionError('此更新未发布给当前设备，或已被管理员撤回')
        return record
