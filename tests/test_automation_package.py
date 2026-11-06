"""Versioned automation packages validate before writing or executing files."""
import copy
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from app import automation_package as packages


class AutomationPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'
        self.manifest = packages.create_project(self.project, name='demo')

    def save_manifest(self, **changes):
        self.manifest.update(changes)
        (self.project / 'wbot.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def rewrite_archive(self, archive, changes):
        target = self.root / 'modified.wbot.zip'
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(target, 'w') as output:
            for member in source.infolist():
                output.writestr(member, changes.pop(member.filename, source.read(member)))
            for name, content in changes.items():
                output.writestr(name, content)
        return target

    def test_initialize_new_project_without_overwriting_existing_files(self):
        self.assertEqual(self.manifest['schemaVersion'], 1)
        self.assertEqual(self.manifest['files'], ['main.py'])
        source = (self.project / 'main.py').read_text(encoding='utf-8')
        self.assertIn('runtime.parameters()', source)
        self.assertIn('runtime.set_result(', source)
        with self.assertRaises(FileExistsError):
            packages.create_project(self.project, name='replacement')
        self.assertEqual(source, (self.project / 'main.py').read_text(encoding='utf-8'))

    def test_build_inspect_and_extract_only_declared_files(self):
        (self.project / 'secrets.env').write_text('PRIVATE=not included')
        archive = packages.build_package(self.project)
        self.assertEqual(archive.name, 'demo-0.1.0.wbot.zip')
        self.assertEqual(packages.inspect_package(archive), self.manifest)
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(set(package.namelist()), {'wbot.json', 'main.py', 'checksums.sha256.json'})
            hashes = json.loads(package.read('checksums.sha256.json'))
            self.assertEqual(hashes['main.py'], hashlib.sha256(package.read('main.py')).hexdigest())
        destination = self.root / 'installed'
        self.assertEqual(packages.extract_package(archive, destination), self.manifest)
        self.assertEqual((destination / 'main.py').read_bytes(), (self.project / 'main.py').read_bytes())
        with self.assertRaises(FileExistsError):
            packages.extract_package(archive, destination)

    def test_build_is_reproducible_and_existing_version_is_preserved(self):
        first = packages.build_package(self.project)
        original = first.read_bytes()
        second = packages.build_package(self.project, self.root / 'copy.wbot.zip')
        self.assertEqual(original, second.read_bytes())
        (self.project / 'main.py').write_text('print("changed")')
        with self.assertRaises(FileExistsError):
            packages.build_package(self.project)
        self.assertEqual(original, first.read_bytes())

    def test_manifest_rejects_invalid_identity_schema_and_unknown_fields(self):
        original = copy.deepcopy(self.manifest)
        for change in ({'schemaVersion': True}, {'schemaVersion': 2}, {'name': '../demo'},
                       {'version': 'latest'}, {'version': '1.0'}, {'unknown': 'ignored'},
                       {'requirements': {'lxml': '>=5.0'}}, {'requirements': {'lxml; evil': '5.0'}}):
            with self.subTest(change=change):
                self.manifest = copy.deepcopy(original)
                self.save_manifest(**change)
                with self.assertRaises(ValueError):
                    packages.build_package(self.project)

    def test_manifest_rejects_invalid_entry_and_file_names(self):
        original = copy.deepcopy(self.manifest)
        for change in ({'entry': 'missing.py'}, {'entry': 'main.txt', 'files': ['main.txt']},
                       {'files': ['main.py', 'MAIN.py']}, {'files': ['../outside.py']},
                       {'files': ['sub\\main.py']}, {'files': ['./main.py']},
                       {'files': ['C:/outside.py']}, {'files': ['CON.py']},
                       {'files': ['sub//main.py']}, {'files': ['main.py', 'wbot.json']},
                       {'files': ['main.py', 'main.py/helper.py']}):
            with self.subTest(change=change):
                self.manifest = copy.deepcopy(original)
                self.save_manifest(**change)
                with self.assertRaises(ValueError):
                    packages.build_package(self.project)

    def test_missing_declared_file_fails_before_creating_output(self):
        self.save_manifest(files=['main.py', 'missing.txt'])
        output = self.root / 'missing.wbot.zip'
        with self.assertRaises((ValueError, FileNotFoundError)):
            packages.build_package(self.project, output)
        self.assertFalse(output.exists())

    def test_parameter_defaults_required_and_strict_types(self):
        self.save_manifest(parameters={
            'name': {'type': 'string', 'required': True, 'description': 'Input name'},
            'count': {'type': 'integer', 'default': 2},
            'rate': {'type': 'number', 'default': 1.5},
            'enabled': {'type': 'boolean', 'default': False},
            'note': {'type': 'string'},
        })
        values = {'name': 'Alice', 'count': 3}
        self.assertEqual(packages.resolve_parameters(self.manifest, values),
                         {'name': 'Alice', 'count': 3, 'rate': 1.5, 'enabled': False})
        self.assertEqual(values, {'name': 'Alice', 'count': 3})
        for values in ({}, {'name': 'Alice', 'extra': 1}, {'name': 12},
                       {'name': 'Alice', 'count': True}, {'name': 'Alice', 'count': 2.0},
                       {'name': 'Alice', 'rate': float('nan')}, {'name': 'Alice', 'enabled': 'true'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                packages.resolve_parameters(self.manifest, values)

    def test_invalid_parameter_definitions_fail_at_build(self):
        for definition in ({'type': 'object'}, {'type': 'string', 'default': 5},
                           {'type': 'number', 'default': float('inf')},
                           {'type': 'integer', 'required': 'yes'}, {'type': 'string', 'secret': True}):
            with self.subTest(definition=definition):
                self.save_manifest(parameters={'value': definition})
                with self.assertRaises(ValueError):
                    packages.build_package(self.project)

    def test_elements_export_is_portable_without_changing_source(self):
        exported = {'format': 'wbot-elements', 'version': 1, 'items': [
            {'name': '搜索', 'group': '首页', 'xpath': "//input[@name='q']", 'browserId': 'ephemeral',
             'frame': {'browserId': 'browser', 'tabId': 4, 'frameId': 2, 'documentId': 'doc',
                       'url': 'https://example.test', 'isTop': True, 'xpathScope': 'page'}}]}
        source = json.dumps(exported, ensure_ascii=False).encode('utf-8')
        (self.project / 'elements.json').write_bytes(source)
        self.save_manifest(files=['main.py', 'elements.json'], elements='elements.json')
        archive = packages.build_package(self.project)
        with zipfile.ZipFile(archive) as package:
            record = json.loads(package.read('elements.json'))['items'][0]
        self.assertNotIn('browserId', record)
        self.assertEqual(record['frame'], {'url': 'https://example.test', 'isTop': True, 'xpathScope': 'page'})
        self.assertEqual(source, (self.project / 'elements.json').read_bytes())

    def test_undeclared_or_invalid_elements_export_is_rejected(self):
        self.save_manifest(elements='elements.json')
        with self.assertRaises(ValueError):
            packages.build_package(self.project)
        (self.project / 'elements.json').write_text('{"items": []}')
        self.save_manifest(files=['main.py', 'elements.json'])
        with self.assertRaises(ValueError):
            packages.build_package(self.project)

    def test_tampered_content_fails_before_destination_is_created(self):
        original = packages.build_package(self.project)
        modified = self.rewrite_archive(original, {'main.py': b'print("tampered")'})
        destination = self.root / 'unsafe'
        with self.assertRaisesRegex(ValueError, 'SHA|校验|完整性'):
            packages.extract_package(modified, destination)
        self.assertFalse(destination.exists())

    def test_reject_extra_traversal_case_duplicate_and_link_archive_members(self):
        original = packages.build_package(self.project)
        link = zipfile.ZipInfo('link.py')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for member in ('extra.py', '../outside.py', '/outside.py', 'MAIN.py', link):
            with self.subTest(member=member):
                modified = self.rewrite_archive(original, {member: b'main.py'})
                with self.assertRaises(ValueError):
                    packages.inspect_package(modified)

    def test_duplicate_json_keys_and_checksum_coverage_are_rejected(self):
        original = packages.build_package(self.project)
        for changed in ({'wbot.json': b'{"schemaVersion":1,"schemaVersion":1}'},
                        {'checksums.sha256.json': b'{}'}):
            with self.subTest(changed=changed):
                modified = self.rewrite_archive(original, changed)
                with self.assertRaises(ValueError):
                    packages.inspect_package(modified)

    def test_archive_and_project_size_limits_are_enforced(self):
        original = packages.build_package(self.project)
        with patch.object(packages, 'MAX_FILE_BYTES', 8):
            with self.assertRaises(ValueError):
                packages.inspect_package(original)
            with self.assertRaises(ValueError):
                packages.build_package(self.project, self.root / 'large.wbot.zip')
        with patch.object(packages, 'MAX_FILES', 1):
            with self.assertRaises(ValueError):
                packages.inspect_package(original)

    def test_source_symlink_and_destination_link_are_rejected(self):
        actual = self.root / 'outside.py'
        actual.write_text('print("outside")')
        link = self.project / 'linked.py'
        try:
            link.symlink_to(actual)
        except OSError as error:
            self.skipTest(f'Symlink creation unavailable: {error}')
        self.save_manifest(files=['main.py', 'linked.py'])
        with self.assertRaises(ValueError):
            packages.build_package(self.project)
        self.save_manifest(files=['main.py'])
        original = packages.build_package(self.project)
        alias = self.root / 'alias'
        alias.symlink_to(self.project, target_is_directory=True)
        with self.assertRaises(ValueError):
            packages.extract_package(original, alias / 'extracted')

    def test_direct_script_cli_emits_json_and_reports_duplicate_build(self):
        script = Path(packages.__file__).resolve()
        command = [sys.executable, str(script), 'build', str(self.project)]
        built = subprocess.run(command, cwd=self.root, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(built.returncode, 0, built.stderr)
        self.assertTrue(Path(json.loads(built.stdout)['path']).is_file())
        duplicate = subprocess.run(command, cwd=self.root, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(duplicate.returncode, 1)
        self.assertIn('error', json.loads(duplicate.stderr))


if __name__ == '__main__':
    unittest.main()
