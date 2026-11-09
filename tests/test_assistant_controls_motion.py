"""Dropdown keyboard semantics and interruptible navigation motion."""
import importlib.util
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.assistant import qt_theme
    from app.assistant.qt_dialogs import ThemedComboBox
    from app.assistant.qt_ui import AssistantWindow
    from tests.test_assistant_qt_ui import FakeClient


@unittest.skipUnless(HAS_QT, '未安装可选 PySide6')
class ControlsMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        qt_theme.apply_theme(self.app, self.directory.name)
        self.window = AssistantWindow(FakeClient(), self.directory.name)
        self.addCleanup(self.window.close)
        self.window.show()
        QTest.qWait(30)

    def test_rapid_switch_resize_and_hide_leave_current_page_usable(self):
        tabs = self.window.tabs
        tabs.setCurrentIndex(1)
        self.assertIsNotNone(tabs.currentWidget().graphicsEffect())
        QTest.qWait(40)
        tabs.setCurrentIndex(0)
        tabs.setCurrentIndex(1)
        self.window.resize(420, 560)
        QTest.qWait(260)
        self.assertEqual(tabs.currentIndex(), 1)
        self.assertTrue(tabs.currentWidget().isVisible())
        self.assertTrue(all(tabs.widget(i).graphicsEffect() is None for i in range(tabs.count())))
        tabs.setCurrentIndex(0)
        self.window.open_settings()
        self.window.show_home()
        self.assertIsNone(tabs.currentWidget().graphicsEffect())
        self.assertEqual(tabs.currentIndex(), 0)

    def test_reduced_motion_persists_and_skips_page_effect(self):
        self.window.open_settings()
        self.window.settings_page.reduce_motion.setChecked(True)
        self.window.show_home()
        self.window.tabs.setCurrentIndex(1)
        self.assertIsNone(self.window.tabs.currentWidget().graphicsEffect())
        qt_theme.apply_theme(self.app, self.directory.name)
        self.assertTrue(qt_theme.reduced_motion(self.app))

    def test_tabs_keep_keyboard_navigation_and_settle_on_last_selection(self):
        tabs = self.window.tabs
        bar = tabs.tabBar()
        bar.setFocus()
        QTest.keyClick(bar, Qt.Key.Key_Right)
        self.assertEqual(tabs.currentIndex(), 1)
        QTest.qWait(50)
        QTest.keyClick(bar, Qt.Key.Key_Left)
        QTest.qWait(260)
        self.assertEqual(tabs.currentIndex(), 0)
        self.assertEqual(bar._indicator, bar._target_rect())
        self.assertTrue(bar.hasFocus())
        self.assertIsNone(tabs.currentWidget().graphicsEffect())

    def test_dropdown_keyboard_commit_cancel_and_disabled_state(self):
        combo = ThemedComboBox()
        self.addCleanup(combo.close)
        combo.addItem('不指定，使用默认值', None)
        combo.addItem('是', True)
        combo.addItem('否', False)
        combo.resize(260, 44)
        combo.show()
        combo.showPopup()
        QTest.qWait(20)
        self.assertGreaterEqual(combo.view().sizeHintForRow(0), 36)
        QTest.keyClick(combo.view(), Qt.Key.Key_Down)
        QTest.keyClick(combo.view(), Qt.Key.Key_Return)
        self.assertIs(combo.currentData(), True)
        combo.showPopup()
        QTest.keyClick(combo.view(), Qt.Key.Key_Down)
        QTest.keyClick(combo.view(), Qt.Key.Key_Escape)
        self.assertIs(combo.currentData(), True)
        combo.setEnabled(False)
        self.assertFalse(combo.isEnabled())
        self.assertIs(combo.currentData(), True)

    def test_long_dropdown_options_remain_within_screen_and_keep_full_value(self):
        combo = ThemedComboBox()
        self.addCleanup(combo.close)
        long_title = '企业财务部自动化执行环境' * 12
        combo.addItem(long_title, 'stable-key')
        combo.resize(220, 44)
        available = combo.screen().availableGeometry()
        combo.move(available.right() - 220, available.bottom() - 44)
        combo.show()
        combo.showPopup()
        QTest.qWait(20)
        self.assertTrue(available.contains(combo.view().window().geometry()))
        self.assertEqual(combo.currentText(), long_title)
        self.assertEqual(combo.currentData(), 'stable-key')
        combo.hidePopup()
