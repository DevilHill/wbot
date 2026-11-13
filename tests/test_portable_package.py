import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from app.automation_package import inspect_package, extract_package, validate_manifest


class PortablePackageBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = {'schemaVersion': 2, 'name': 'portable', 'version': '1.0.0',
            'entry': 'main.py', 'files': ['main.py', '_runtime/python.exe'],
            'parameters': {}, 'requirements': {},
            'runtime': {'kind': 'bundled-python', 'platform': 'win32-x64',
                        'python': '3.13.14', 'executable': '_runtime/python.exe'}}

    def archive(self, extra=None, symlink=False):
        contents = {'wbot.json': json.dumps(self.manifest).encode(),
                    'main.py': b'print("hello")', '_runtime/python.exe': b'test fixture'}
        contents['checksums.sha256.json'] = json.dumps({name: hashlib.sha256(value).hexdigest()
            for name, value in contents.items()}).encode()
        if extra:
            contents.update(extra)
        target = self.root / 'package.zip'
        with zipfile.ZipFile(target, 'w') as archive:
            for name, value in contents.items():
                member = zipfile.ZipInfo(name)
                member.create_system = 3
                member.external_attr = ((stat.S_IFLNK if symlink and name == '_runtime/python.exe' else stat.S_IFREG) | 0o644) << 16
                archive.writestr(member, value)
        return target

    def test_protocol_verifies_without_executing_runtime(self):
        self.assertEqual(inspect_package(self.archive()), self.manifest)
        extracted = self.root / 'extracted'
        extract_package(self.archive(), extracted)
        self.assertEqual((extracted / '_runtime/python.exe').read_bytes(), b'test fixture')

    def test_traversal_undeclared_files_links_and_missing_checksums_are_rejected(self):
        for extra, symlink in [({'../escape': b'x'}, False), ({'undeclared': b'x'}, False),
                               ({'checksums.sha256.json': b'{}'}, False), ({}, True)]:
            with self.subTest(extra=extra, symlink=symlink), self.assertRaises(ValueError):
                extract_package(self.archive(extra, symlink), self.root / 'output')
            self.assertFalse((self.root / 'output').exists())

    def test_runtime_contract_rejects_external_interpreters_and_wrong_platform(self):
        for field, value in [('executable', 'C:/python/python.exe'), ('platform', 'linux-x64'),
                             ('kind', 'system-python'), ('python', 'latest')]:
            original = self.manifest['runtime'][field]
            self.manifest['runtime'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_manifest(self.manifest)
            self.manifest['runtime'][field] = original
