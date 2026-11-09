import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import importlib.util
import unittest
from unittest.mock import patch

HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.assistant.qt_ui import AssistantWindow
    from app.assistant.qt_dialogs import ParameterDialog
    from tests.test_assistant_qt_ui import FakeClient, PACKAGE


@unittest.skipUnless(HAS_QT, '未安装可选 Qt')
class TitleBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_caption_maximize_restore_and_close_keep_background_behavior(self):
        window = AssistantWindow(FakeClient(), 'unused')
        window.tray_available = True
        window.show()
        QTest.qWait(20)
        self.assertTrue(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        window.title_bar.maximize_button.click()
        self.assertTrue(window.isMaximized())
        window.title_bar.maximize_button.click()
        self.assertFalse(window.isMaximized())
        self.assertEqual(window.title_bar.maximize_button.accessibleName(), '最大化')
        self.assertEqual(len(window.title_bar.resize_handles), 8)
        window.title_bar.close_button.click()
        self.assertFalse(window.isVisible())
        self.assertFalse(window._closed)
        window.tray_available = False
        window.close()

    def test_native_fallback_has_no_duplicate_caption(self):
        with patch.dict(os.environ, {'WBOT_NATIVE_TITLE_BAR':'1'}):
            window = AssistantWindow(FakeClient(), 'unused')
            self.assertFalse(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
            self.assertIsNone(window.title_bar)
            window.close()

    def test_dialog_has_same_caption_and_close_only_closes_dialog(self):
        dialog = ParameterDialog(FakeClient(), PACKAGE)
        dialog.show()
        QTest.qWait(20)
        dialog.title_bar.close_button.click()
        self.assertTrue(dialog.closed)
        self.assertFalse(dialog.isVisible())
