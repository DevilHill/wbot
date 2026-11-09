"""User-visible theme, connection and form regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
import importlib.util
HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.assistant import qt_theme
    from app.assistant.qt_ui import AssistantWindow
    from app.assistant.qt_settings import SettingsPage
    from app.assistant.qt_dialogs import ParameterDialog
    from tests.test_assistant_qt_ui import FakeClient, PACKAGE
    from tests.test_assistant_qt_settings import SettingsClient

@unittest.skipUnless(HAS_QT, '未安装可选 PySide6')
class PolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_theme_persists_and_system_change_does_not_override_explicit_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            qt_theme.apply_theme(self.app, directory)
            qt_theme.set_theme_mode(self.app, 'dark')
            self.assertEqual(qt_theme.theme_mode(self.app), 'dark')
            self.assertEqual(qt_theme.color('surface'), '#202126')
            qt_theme.apply_theme(self.app, directory)
            self.assertEqual(qt_theme.theme_mode(self.app), 'dark')
            self.app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
            self.assertEqual(qt_theme.color('surface'), '#202126')
            qt_theme.set_theme_mode(self.app, 'light')

    def test_home_distinguishes_local_service_and_oc(self):
        window = AssistantWindow(FakeClient(), 'unused')
        QTest.qWait(30)
        self.assertIn('本机', window.connection.text())
        self.assertIn('尚未连接', window.oc_connection.text())
        window.close()

    def test_approved_settings_hides_verification_and_apply_action_until_edit(self):
        dialog = SettingsPage(SettingsClient(), 'unused')
        dialog.show()
        QTest.qWait(30)
        self.assertFalse(dialog.verification_code.isVisible())
        self.assertFalse(dialog.connect_button.isVisible())
        dialog.device_name.setText('另一台电脑')
        self.assertTrue(dialog.connect_button.isVisible())
        dialog.close()

    def test_invalid_parameter_is_localized_and_focuses_field(self):
        dialog = ParameterDialog(FakeClient(), PACKAGE)
        dialog.show()
        dialog.fields['count'].setText('abc')
        dialog.submit()
        self.assertTrue(dialog.fields['count'].property('invalid'))
        self.assertIn('整数', dialog.field_errors['count'].text())
        dialog.fields['count'].setText('2')
        self.assertFalse(dialog.fields['count'].property('invalid'))
        dialog.close()

    def test_parameter_title_is_optional_and_does_not_change_runtime_key(self):
        import copy
        from app.automation_package import validate_manifest
        package = copy.deepcopy(PACKAGE)
        package['manifest']['parameters']['count']['title'] = '执行次数'
        validate_manifest(package['manifest'])
        dialog = ParameterDialog(FakeClient(), package)
        self.assertEqual(dialog.fields['count'].accessibleName(), '执行次数')
        dialog.fields['count'].setText('3')
        self.assertEqual(dialog.parameters()['count'], 3)
        dialog.close()
        package['manifest']['parameters']['count']['title'] = 7
        with self.assertRaises(ValueError):
            validate_manifest(package['manifest'])
