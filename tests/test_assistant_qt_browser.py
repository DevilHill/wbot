import os
import importlib.util
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtWidgets import QApplication
    from app.assistant.qt_browser import BrowserExtensionCard


@unittest.skipUnless(HAS_QT, '未安装可选 PySide6-Essentials')
class BrowserCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.calls = []
        self.card = BrowserExtensionCard(self)
        self.addCleanup(self.card.close)

    def request(self, method, path, body, on_success, on_error):
        self.calls.append((method, path, body))
        self.success, self.failure = on_success, on_error

    def test_selected_browser_setup_shows_manual_steps_without_claiming_installed(self):
        self.card.browser.setCurrentIndex(1)
        self.card.prepare()
        self.card.prepare()
        self.assertEqual(self.calls, [('POST', '/api/browser',
            {'path': '/api/extension/install', 'body': {'browser': 'edge'}})])
        self.assertFalse(self.card.install.isEnabled())
        with patch.object(QApplication, 'clipboard') as clipboard:
            self.success({'directory': 'D:/流程/extension', 'management_url': 'edge://extensions/', 'opened': True})
            clipboard.return_value.setText.assert_called_once_with('D:/流程/extension')
        self.assertTrue(self.card.install.isEnabled())
        self.assertIn('开发者模式', self.card.instructions.text())
        self.assertIn('edge://extensions/', self.card.instructions.text())
        self.assertIn('完成加载', self.card.status.text())

    def test_connection_counts_and_errors_remain_actionable(self):
        self.card.check_connection()
        self.success({'bridge': {'extensions': 0}})
        self.assertIn('尚未检测到', self.card.status.text())
        self.card.check_connection()
        self.success({'bridge': {'extensions': 2}})
        self.assertIn('所有浏览器合计', self.card.status.text())
        self.card.prepare()
        self.failure('后台服务未启动')
        self.assertTrue(self.card.install.isEnabled())
        self.assertEqual(self.card.status.text(), '后台服务未启动')
        self.card.close()
        self.failure('late callback')
        self.assertEqual(self.card.status.text(), '后台服务未启动')
