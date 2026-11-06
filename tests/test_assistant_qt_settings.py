"""设置窗口的异步申请、审批跟踪与编辑草稿回归。"""
import importlib.util
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.assistant.qt_settings import SettingsDialog


SETTINGS = {'server_url': 'https://oc.example.test', 'device_name': '财务电脑',
            'device_id': 'device-one', 'binding_state': 'approved',
            'verification_code': '728194', 'last_connected_at': 1700000000,
            'error': '', 'transport_secure': True}


class SettingsClient:
    def __init__(self):
        self.settings = dict(SETTINGS)
        self.calls = []
        self.pending_action = None
        self.pending_poll = None
        self.defer_poll = False
        self.offline = False

    def request(self, method, path, body=None, on_success=None, on_error=None):
        self.calls.append((method, path, body))
        if method == 'POST':
            self.pending_action = (on_success, on_error)
        elif self.defer_poll:
            self.pending_poll = (on_success, on_error)
        elif self.offline:
            QTimer.singleShot(0, lambda: on_error('本机服务暂时不可用'))
        else:
            QTimer.singleShot(0, lambda: on_success({'settings': dict(self.settings)}))


@unittest.skipUnless(HAS_QT, '未安装可选 PySide6-Essentials')
class SettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.client = SettingsClient()
        self.dialog = SettingsDialog(self.client, 'test-state')
        self.dialog.show()
        QTest.qWait(20)

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        QTest.qWait(10)

    def test_poll_preserves_draft_and_tracks_approval(self):
        self.assertFalse(self.dialog.pending_reports_hint.isVisible())
        self.dialog.server_url.setText('http://192.168.1.20:8793')
        self.dialog.device_name.setText('新设备名称')
        self.client.settings.update(binding_state='pending', verification_code='112233', pending_reports=2)
        self.dialog.refresh()
        QTest.qWait(20)
        self.assertEqual(self.dialog.server_url.text(), 'http://192.168.1.20:8793')
        self.assertEqual(self.dialog.device_name.text(), '新设备名称')
        self.assertIn('等待', self.dialog.state_label.text())
        self.assertIn('112233', self.dialog.verification_code.text())
        self.assertTrue(self.dialog.transport_hint.isVisible())
        self.assertIn('有 2 条结果待同步', self.dialog.pending_reports_hint.text())
        self.assertTrue(self.dialog.pending_reports_hint.isVisible())

    def test_connect_submits_trimmed_fields_once_and_clears_busy(self):
        self.dialog.server_url.setText(' https://new-oc.example.test ')
        self.dialog.device_name.setText(' 新电脑 ')
        QTest.mouseClick(self.dialog.connect_button, Qt.MouseButton.LeftButton)
        self.dialog.connect_service()
        posts = [call for call in self.client.calls if call[0] == 'POST']
        self.assertEqual(posts, [('POST', '/api/settings/connect',
                                 {'server_url': 'https://new-oc.example.test', 'device_name': '新电脑'})])
        self.assertFalse(self.dialog.connect_button.isEnabled())
        self.assertFalse(self.dialog.server_url.isEnabled())
        pending = dict(SETTINGS, server_url='https://new-oc.example.test', device_name='新电脑',
                       binding_state='pending', verification_code='445566')
        self.client.pending_action[0]({'settings': pending})
        self.assertFalse(self.dialog.busy)
        self.assertEqual(self.dialog.server_url.text(), pending['server_url'])
        self.assertIn('445566', self.dialog.verification_code.text())

    def test_disconnect_error_preserves_binding_and_stays_visible_after_poll(self):
        self.dialog.disconnect_service()
        self.assertEqual(self.client.calls[-1][:2], ('POST', '/api/settings/disconnect'))
        self.client.pending_action[1]('本机任务正在运行，暂不能断开')
        self.dialog.refresh()
        QTest.qWait(20)
        self.assertEqual(self.dialog.settings['binding_state'], 'approved')
        self.assertIn('正在运行', self.dialog.error.text())
        self.assertFalse(self.dialog.busy)

    def test_approved_offline_keeps_binding_and_recovers(self):
        self.client.settings['error'] = '无法连接 OC，稍后重试'
        self.dialog.refresh()
        QTest.qWait(20)
        self.assertEqual(self.dialog.settings['binding_state'], 'approved')
        self.assertIn('已绑定', self.dialog.state_label.text())
        self.assertIn('无法连接', self.dialog.error.text())
        self.client.offline = True
        self.dialog.refresh()
        QTest.qWait(20)
        self.assertFalse(self.dialog.disconnect_button.isEnabled())
        self.assertEqual(self.dialog.settings['binding_state'], 'approved')
        self.client.offline = False
        self.client.settings['error'] = ''
        self.dialog.refresh()
        QTest.qWait(20)
        self.assertTrue(self.dialog.disconnect_button.isEnabled())

    def test_old_poll_cannot_overwrite_connect_response(self):
        self.client.defer_poll = True
        self.dialog.refresh()
        self.dialog.server_url.setText('https://new-oc.example.test')
        self.dialog.connect_service()
        pending = dict(SETTINGS, server_url='https://new-oc.example.test', binding_state='pending')
        self.client.pending_action[0]({'settings': pending})
        self.client.pending_poll[0]({'settings': SETTINGS})
        self.assertEqual(self.dialog.settings['server_url'], pending['server_url'])
        self.assertEqual(self.dialog.settings['binding_state'], 'pending')

    def test_revoked_and_disconnected_can_request_without_editing(self):
        for state, caption in (('revoked', '重新申请'), ('disconnected', '重新连接')):
            self.client.settings['binding_state'] = state
            self.dialog.refresh()
            QTest.qWait(20)
            self.assertTrue(self.dialog.connect_button.isEnabled())
            self.assertIn(caption, self.dialog.connect_button.text())

    def test_close_ignores_late_action_response(self):
        self.dialog.disconnect_service()
        changes = []
        self.dialog.binding_changed.connect(changes.append)
        self.dialog.close()
        self.client.pending_action[0]({'settings': dict(SETTINGS, binding_state='disconnected')})
        self.assertEqual(changes, [])
        self.assertFalse(self.dialog.timer.isActive())


if __name__ == '__main__':
    unittest.main()
