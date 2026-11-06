"""验证 Qt 默认入口与便携包的独立运行环境选择。"""
import contextlib
import builtins
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from app.assistant import __main__ as assistant_cli
from app.assistant.lifecycle import service_launch


class AssistantPackagingTests(unittest.TestCase):
    def test_source_service_uses_current_interpreter(self):
        with patch.object(sys, 'frozen', False, create=True):
            command, directory = service_launch(Path('state'), 0)
        self.assertEqual(command[:4], [sys.executable, '-m', 'app.assistant', 'serve'])
        self.assertTrue((directory / 'app' / 'assistant' / '__main__.py').is_file())

    def test_frozen_service_uses_bundled_python_and_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            interpreter = bundle / 'python' / 'python.exe'
            source = bundle / 'runtime'
            interpreter.parent.mkdir()
            interpreter.touch()
            (source / 'app' / 'assistant').mkdir(parents=True)
            (source / 'app' / 'assistant' / '__main__.py').touch()
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(bundle / 'WBotAssistant.exe')):
                command, directory = service_launch(Path('state'), 8791)
            self.assertEqual(command[0], str(interpreter))
            self.assertEqual(directory, source)
            self.assertNotIn('WBotAssistant.exe', command)

    def test_incomplete_portable_bundle_fails_before_starting_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(Path(temporary) / 'WBotAssistant.exe')):
                with self.assertRaisesRegex(RuntimeError, '完整解压'):
                    service_launch(Path('state'), 0)

    def test_default_open_calls_qt_with_state_directory(self):
        called = []
        module = types.ModuleType('app.assistant.qt_app')
        module.open_desktop = lambda state_dir: called.append(state_dir) or 0
        with patch.dict(sys.modules, {'app.assistant.qt_app': module}), patch.object(assistant_cli, 'start_service', return_value={'running': True, 'url': 'http://127.0.0.1:12345'}), contextlib.redirect_stdout(io.StringIO()):
            result = assistant_cli.main(['open', '--state-dir', 'test-state'])
        self.assertEqual(result, 0)
        self.assertEqual(called, [Path('test-state')])

    def test_browser_mode_does_not_load_qt(self):
        with patch.object(assistant_cli, 'start_service', return_value={'running': True, 'url': 'http://127.0.0.1:12345'}), patch.object(assistant_cli.webbrowser, 'open') as opened, patch.object(assistant_cli, 'load_desktop', side_effect=AssertionError('不应导入 Qt')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(assistant_cli.main(['open', '--browser']), 0)
        opened.assert_called_once_with('http://127.0.0.1:12345')

    def test_missing_qt_reports_install_command_without_starting_service(self):
        original = builtins.__import__

        def import_without_qt(name, *args, **kwargs):
            if name == 'qt_app':
                raise ModuleNotFoundError("No module named 'PySide6'", name='PySide6')
            return original(name, *args, **kwargs)

        errors = io.StringIO()
        with patch('builtins.__import__', side_effect=import_without_qt), patch.object(assistant_cli, 'start_service') as started, contextlib.redirect_stderr(errors):
            self.assertEqual(assistant_cli.main(['open']), 1)
        started.assert_not_called()
        self.assertIn('requirements-assistant.txt', errors.getvalue())


if __name__ == '__main__':
    unittest.main()
