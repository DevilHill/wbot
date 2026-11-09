import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from app.assistant_release import inspect_release, version_key, verify_prepared
from app.oc.service import OcService


def release_zip(path, version='0.8.0', extra=None):
    files = {'WBotAssistant.exe': b'gui', 'python/python.exe': b'python',
             'runtime/app/assistant/__main__.py': b'# entry',
             'assistant-release.json': json.dumps({'schema': 1, 'product': 'wbot-assistant',
                 'platform': 'windows-x64', 'version': version, 'notes': '修复与改进'}).encode()}
    files.update(extra or {})
    checksums = {key: hashlib.sha256(value).hexdigest() for key, value in files.items()}
    files['checksums.sha256.json'] = json.dumps(checksums).encode()
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in files.items():
            archive.writestr('WBotAssistant/' + name, content)
    return path


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_verify_extract_and_numeric_version_order(self):
        archive = release_zip(self.root / 'release.zip')
        result = inspect_release(archive, self.root / 'prepared')
        self.assertEqual(result['version'], '0.8.0')
        self.assertEqual((self.root / 'prepared/WBotAssistant/WBotAssistant.exe').read_bytes(), b'gui')
        self.assertGreater(version_key('0.10.0'), version_key('0.9.0'))

    def test_reject_unsafe_paths_and_tampered_payload(self):
        for path in ('../outside', 'runtime/CON', 'runtime/a:stream', 'runtime/trailing. ', 'runtime/../outside'):
            with self.subTest(path=path):
                archive = release_zip(self.root / 'release.zip', extra={path: b'bad'})
                with self.assertRaises(ValueError):
                    inspect_release(archive)
        archive = release_zip(self.root / 'release.zip')
        with zipfile.ZipFile(archive, 'a') as output:
            output.writestr('WBotAssistant/unlisted.exe', b'bad')
        with self.assertRaises(ValueError):
            inspect_release(archive)

    def test_changed_staging_manifest_cannot_authorize_changed_executable(self):
        archive = release_zip(self.root / 'release.zip')
        inspect_release(archive, self.root / 'prepared')
        staged = self.root / 'prepared/WBotAssistant'
        (staged / 'WBotAssistant.exe').write_bytes(b'changed')
        checksums = json.loads((staged / 'checksums.sha256.json').read_text())
        checksums['WBotAssistant.exe'] = hashlib.sha256(b'changed').hexdigest()
        (staged / 'checksums.sha256.json').write_text(json.dumps(checksums))
        with self.assertRaises(ValueError):
            verify_prepared(staged, archive)

    def test_draft_targeted_publish_withdraw_and_immutable_version(self):
        service = OcService(self.root / 'oc')
        record = service.releases.upload(release_zip(self.root / 'release.zip'))
        device = {'id': 'approved-device', 'binding_state': 'approved', 'transport': 'agent'}
        service.store.insert('devices', device)
        self.assertIsNone(service.releases.latest(device, '0.7.0'))
        service.releases.publish(record['id'], {'published': True, 'device_ids': [device['id']]})
        self.assertEqual(service.releases.latest(device, '0.7.0')['version'], '0.8.0')
        self.assertIsNone(service.releases.latest(dict(device, id='another'), '0.7.0'))
        self.assertIsNone(service.releases.latest(device, '0.8.0'))
        with self.assertRaises(FileExistsError):
            service.releases.upload(release_zip(self.root / 'changed.zip', extra={'different': b'1'}))
        service.store.replace('devices', dict(device, binding_state='revoked'))
        service.releases.publish(record['id'], {'published': False, 'device_ids': [device['id']]})
        self.assertEqual(service.releases.list()[0]['device_ids'], [device['id']])
        with self.assertRaises(PermissionError):
            service.releases.for_device(device, record['id'])
