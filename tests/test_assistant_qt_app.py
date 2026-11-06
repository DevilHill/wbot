"""同一数据目录仅保留一个界面，并把后续启动转为唤起请求。"""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtCore import QEventLoop, QProcess, QTimer
    from PySide6.QtWidgets import QApplication
    from app.assistant.qt_app import DesktopInstance


@unittest.skipUnless(HAS_QT, '未安装可选 PySide6-Essentials')
class DesktopInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_second_launch_activates_existing_window_and_does_not_own_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            primary = DesktopInstance(directory)
            replacement = DesktopInstance(directory)
            try:
                self.assertTrue(primary.acquire_or_notify())
                self._notify_from_child(directory, primary)
                # 第二个启动进程退出后，不能释放仍在使用的主实例锁。
                self._notify_from_child(directory, primary)
                primary.close()
                self.assertTrue(replacement.acquire_or_notify())
            finally:
                primary.close()
                replacement.close()

    def _notify_from_child(self, directory, primary):
        script = '''
import sys
from PySide6.QtCore import QCoreApplication
from app.assistant.qt_app import DesktopInstance
application = QCoreApplication([])
instance = DesktopInstance(sys.argv[1])
try:
    assert instance.acquire_or_notify() is False, 'secondary unexpectedly owns the lock'
finally:
    instance.close()
'''
        process = QProcess()
        process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        activated = []

        def finish_when_ready():
            if process.state() == QProcess.ProcessState.NotRunning and activated:
                loop.quit()

        def on_activation():
            activated.append(True)
            finish_when_ready()

        primary.activation_requested.connect(on_activation)
        process.finished.connect(finish_when_ready)
        process.errorOccurred.connect(loop.quit)
        try:
            process.start(sys.executable, ['-c', script, str(directory)])
            timeout.start(10000)
            loop.exec()
            self.assertEqual(process.state(), QProcess.ProcessState.NotRunning, 'secondary process timed out')
            self.assertEqual(process.exitCode(), 0, bytes(process.readAllStandardError()).decode('utf-8', 'replace'))
            self.assertEqual(activated, [True])
        finally:
            timeout.stop()
            primary.activation_requested.disconnect(on_activation)
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(1000)

    def test_different_state_directories_can_have_separate_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            first = DesktopInstance(Path(directory) / 'one')
            second = DesktopInstance(Path(directory) / 'two')
            try:
                self.assertTrue(first.acquire_or_notify())
                self.assertTrue(second.acquire_or_notify())
            finally:
                first.close()
                second.close()


if __name__ == '__main__':
    unittest.main()
