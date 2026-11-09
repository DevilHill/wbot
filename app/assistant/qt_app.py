"""Qt 桌面入口、当前用户单实例唤起与系统托盘。"""
import hashlib
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QLockFile, QObject, Signal, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .qt_client import AssistantClient


class DesktopInstance(QObject):
    activation_requested = Signal()

    def __init__(self, state_dir, parent=None):
        super().__init__(parent)
        state_dir = Path(state_dir).resolve()
        state_dir.mkdir(parents=True, exist_ok=True)
        identity = os.path.normcase(str(state_dir)).encode('utf-8')
        self.name = 'wbot-assistant-' + hashlib.sha256(identity).hexdigest()[:32]
        self.lock = QLockFile(str(state_dir / '.desktop.lock'))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept_connections)
        self._primary = False

    def acquire_or_notify(self):
        if not self.lock.tryLock(0):
            if self.lock.error() != QLockFile.LockError.LockFailedError:
                raise RuntimeError('无法创建 Assistant 界面锁，请检查数据目录的写入权限')
            socket = QLocalSocket(self)
            socket.connectToServer(self.name)
            try:
                if not socket.waitForConnected(1000):
                    raise RuntimeError('Assistant 界面正在启动或暂未响应，请稍后重试')
                socket.write(b'show\n')
                if socket.bytesToWrite() and not socket.waitForBytesWritten(1000):
                    raise RuntimeError('无法唤起已有 Assistant 窗口，请稍后重试')
                socket.disconnectFromServer()
            finally:
                socket.deleteLater()
            return False
        # 取得同一目录的界面锁后，才可清理崩溃进程留下的本地监听名。
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise RuntimeError(f'无法启动 Assistant 界面通信：{self.server.errorString()}')
        self._primary = True
        return True

    def _accept_connections(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.setReadBufferSize(64)
            socket.readyRead.connect(lambda current=socket: self._read_activation(current))
            socket.disconnected.connect(socket.deleteLater)
            self._read_activation(socket)

    def _read_activation(self, socket):
        if socket.canReadLine():
            if bytes(socket.readLine(64)) == b'show\n':
                self.activation_requested.emit()
            socket.disconnectFromServer()

    def close(self):
        if self._primary:
            self.server.close()
            self.lock.unlock()
            self._primary = False


def open_desktop(state_dir):
    from .qt_theme import apply_theme, make_app_icon
    from .qt_ui import AssistantWindow

    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName('WBot Assistant')
    application.setOrganizationName('WBot')
    apply_theme(application, state_dir)
    icon = make_app_icon()
    application.setWindowIcon(icon)
    instance = DesktopInstance(state_dir, application)
    if not instance.acquire_or_notify():
        return 0
    client = AssistantClient(state_dir, application)
    window = AssistantWindow(client, state_dir)
    window.setWindowIcon(icon)
    instance.activation_requested.connect(window.show_window)
    tray = QSystemTrayIcon(icon, application)
    menu = QMenu()
    menu.addAction('打开 Assistant', window.show_window)
    menu.addAction('连接设置', window.open_settings)
    menu.addSeparator()
    menu.addAction('退出界面（任务继续）', window.shutdown_ui)
    tray.setContextMenu(menu)
    tray.setToolTip('WBot Assistant · 任务由后台服务独立执行')
    tray.activated.connect(lambda reason: window.show_window()
                           if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                                         QSystemTrayIcon.ActivationReason.DoubleClick) else None)
    window.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
    application.setQuitOnLastWindowClosed(not window.tray_available)
    if window.tray_available:
        tray.show()
    application.aboutToQuit.connect(client.close)
    application.aboutToQuit.connect(instance.close)
    window.show_window()
    if os.environ.get('WBOT_UPDATE_TOKEN'):
        from .version import VERSION
        def confirm_ready():
            receipt = {'token': os.environ.pop('WBOT_UPDATE_TOKEN'), 'version': VERSION}
            (Path(state_dir) / 'update-ui-ready.json').write_text(json.dumps(receipt), encoding='utf-8')
        QTimer.singleShot(0, confirm_ready)
    try:
        return application.exec()
    finally:
        client.close()
        tray.hide()
        instance.close()
