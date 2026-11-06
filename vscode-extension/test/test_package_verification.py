"""内置 wheel 必须同时覆盖新增源码与已有源码内容。"""
import importlib.util
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'verify-package.py'
SPEC = importlib.util.spec_from_file_location('verify_package', SCRIPT)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class WheelSourceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'wbot').mkdir()
        (self.root / 'wbot' / '__init__.py').write_bytes(b'VERSION = 1\n')
        (self.root / 'wbot' / 'runtime.py').write_bytes(b'RUNNING = True\n')

    def archive(self, files):
        content = BytesIO()
        with zipfile.ZipFile(content, 'w') as archive:
            for name, text in files.items():
                archive.writestr(name, text)
        return zipfile.ZipFile(content)

    def test_old_wheel_missing_new_runtime_is_rejected(self):
        with self.archive({'wbot/__init__.py': b'VERSION = 1\n'}) as wheel:
            with self.assertRaisesRegex(AssertionError, 'runtime.py'):
                VERIFIER.verify_wheel_sources(wheel, self.root)

    def test_extra_obsolete_module_is_rejected(self):
        files = {'wbot/__init__.py': b'VERSION = 1\n', 'wbot/runtime.py': b'RUNNING = True\n',
                 'wbot/old.py': b'obsolete = True\n'}
        with self.archive(files) as wheel:
            with self.assertRaisesRegex(AssertionError, 'old.py'):
                VERIFIER.verify_wheel_sources(wheel, self.root)

    def test_same_file_set_still_requires_identical_content(self):
        files = {'wbot/__init__.py': b'VERSION = 1\n', 'wbot/runtime.py': b'RUNNING = False\n'}
        with self.archive(files) as wheel:
            with self.assertRaisesRegex(AssertionError, 'runtime.py'):
                VERIFIER.verify_wheel_sources(wheel, self.root)
        files['wbot/runtime.py'] = b'RUNNING = True\n'
        with self.archive(files) as wheel:
            self.assertEqual(VERIFIER.verify_wheel_sources(wheel, self.root), 2)


if __name__ == '__main__':
    unittest.main()
