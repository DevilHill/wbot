"""Settings stays inside the Assistant window and preserves its draft."""
import importlib.util
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.assistant.qt_ui import AssistantWindow
    from tests.test_assistant_qt_ui import FakeClient
    from tests.test_assistant_qt_settings import SettingsClient, SETTINGS


@unittest.skipUnless(HAS_QT, '未安装可选 Qt')
class SettingsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.client = FakeClient()
        self.window = AssistantWindow(self.client, 'unused')
        self.window.show()
        QTest.qWait(20)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QTest.qWait(10)

    def test_settings_is_embedded_and_return_keeps_draft_and_home_state(self):
        self.window.search.setText('demo')
        self.window.tabs.setCurrentIndex(1)
        self.window.open_settings()
        QTest.qWait(20)
        page = self.window.settings_page
        self.assertFalse(page.isWindow())
        self.assertIs(page.window(), self.window)
        self.assertIs(self.window.pages.currentWidget(), page)
        page.server_url.setText('https://draft.example.test')
        page.back_button.click()
        self.assertIs(self.window.pages.currentWidget(), self.window.home_page)
        self.assertEqual(self.window.search.text(), 'demo')
        self.assertEqual(self.window.tabs.currentIndex(), 1)
        self.assertFalse(page.timer.isActive())
        self.window.open_settings()
        QTest.qWait(20)
        self.assertIs(self.window.settings_page, page)
        self.assertEqual(page.server_url.text(), 'https://draft.example.test')
        self.assertTrue(page.timer.isActive())
        self.assertFalse(any(method == 'POST' for method, _, _ in self.client.calls))

    def test_escape_returns_home_and_tray_entry_shows_same_window(self):
        self.window.hide()
        self.window.open_settings()
        QTest.qWait(20)
        self.assertTrue(self.window.isVisible())
        QTest.keyClick(self.window.settings_page.back_button, Qt.Key.Key_Escape)
        self.assertIs(self.window.pages.currentWidget(), self.window.home_page)
        self.assertFalse(self.window._closed)

    def test_return_while_saving_keeps_result_without_reopening_settings(self):
        self.window.open_settings()
        QTest.qWait(20)
        page = self.window.settings_page
        connection = SettingsClient()
        page.client = connection
        page.server_url.setText('https://new.example.test')
        page.device_name.setText('开发电脑')
        page.connect_service()
        self.assertTrue(page.busy)
        page.back_button.click()
        connection.pending_action[0]({'settings':dict(SETTINGS, server_url='https://new.example.test', binding_state='pending')})
        self.assertFalse(page.busy)
        self.assertIs(self.window.pages.currentWidget(), self.window.home_page)
        self.assertFalse(page.closed)
        self.assertEqual(page.settings['binding_state'], 'pending')
        self.assertEqual(len([call for call in connection.calls if call[0] == 'POST']), 1)
