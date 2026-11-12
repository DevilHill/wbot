import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtCore import QEvent, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.assistant.qt_updates import UpdateCard


class Client:
    def __init__(self):
        self.calls = []
        self.update = {'status': 'ready', 'version': '0.7.0', 'install_supported': True,
                       'release': {'version': '0.8.0', 'notes': '改进', 'size': 100}, 'received': 100}

    def request(self, method, path, body=None, on_success=None, on_error=None):
        self.calls.append((method, path, body))
        if path.endswith('/install'):
            QTimer.singleShot(0, lambda: on_error('当前有任务执行，请等待任务结束后再更新'))
        else:
            QTimer.singleShot(0, lambda: on_success({'update': self.update}))


@unittest.skipUnless(HAS_QT, '未安装可选 PySide6')
class UpdateCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def dispose(self, card):
        card.close()
        card.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_install_busy_error_survives_poll_and_does_not_exit_gui(self):
        client = Client()
        card = UpdateCard(client)
        self.addCleanup(self.dispose, card)
        requested = []
        card.restart_requested.connect(lambda: requested.append(True))
        card.show()
        QTest.qWait(20)
        self.assertEqual(card.action_button.text(), '更新并重启')
        card.action_button.click()
        card.action_button.click()
        QTest.qWait(20)
        self.assertEqual(len([call for call in client.calls if call[0] == 'POST']), 1)
        card.refresh()
        QTest.qWait(20)
        self.assertIn('当前有任务执行', card.message.text())
        self.assertFalse(requested)

    def test_only_accepted_install_for_this_gui_requests_exit_once(self):
        client = Client()
        card = UpdateCard(client)
        self.addCleanup(self.dispose, card)
        requested = []
        card.restart_requested.connect(lambda: requested.append(True))
        card.show()
        QTest.qWait(20)
        client.update.update(status='installing', desktop_pid=os.getpid())
        card.refresh()
        QTest.qWait(20)
        card.refresh()
        QTest.qWait(20)
        self.assertEqual(requested, [True])
        self.assertFalse(card.action_button.isEnabled())

    def test_restart_signal_allows_clean_process_exit(self):
        result = subprocess.run([sys.executable, '-m', 'unittest',
            'tests.test_assistant_qt_updates.UpdateCardTests.test_only_accepted_install_for_this_gui_requests_exit_once',
            '-q'], cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))

    def test_sources_size_plain_text_notes_and_failed_check(self):
        card = UpdateCard(Client())
        self.addCleanup(self.dispose, card)
        release = {'version': '0.10.0', 'notes': '<b>更新说明</b>', 'size': 2 * 1024 * 1024}
        card._received({'update': {'status': 'available', 'source': 'github',
                                   'install_supported': True, 'release': release}})
        self.assertIn('GitHub', card.source.text())
        self.assertIn('2.0 MiB', card.notes.text())
        self.assertIn('<b>更新说明</b>', card.notes.text())
        card._received({'update': {'status': 'failed', 'source': 'oc', 'release': None,
                                   'install_supported': True, 'message': 'OC 连接失败，请重试'}})
        self.assertIn('OC', card.source.text())
        self.assertIn('连接失败', card.message.text())
        self.assertTrue(card.action_button.isHidden())
        self.assertTrue(card.check_button.isEnabled())
