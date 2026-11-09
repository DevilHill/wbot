"""Inline update status; network and installation work stays in the service."""
import os

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QProgressBar, QPushButton, QVBoxLayout

from .qt_dialogs import label
from .version import VERSION


class UpdateCard(QFrame):
    restart_requested = Signal()

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self._pending = False
        self._quitting = False
        self._closed = False
        self._action_error = ''
        self.setObjectName('settingsCard')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(label('软件更新', 'fieldLabel'))
        self.version = label(f'Assistant {VERSION}', 'emptyTitle')
        layout.addWidget(self.version)
        self.message = label('从已绑定的 OC 获取管理员发布的版本。', 'hint', True)
        layout.addWidget(self.message)
        self.notes = label('', 'subtitle', True)
        self.notes.hide()
        layout.addWidget(self.notes)
        self.progress = QProgressBar()
        self.progress.setAccessibleName('更新包下载进度')
        self.progress.hide()
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.check_button = QPushButton('检查更新')
        self.check_button.setMinimumHeight(40)
        self.check_button.clicked.connect(lambda: self._action('check'))
        self.action_button = QPushButton('下载更新')
        self.action_button.setMinimumHeight(40)
        self.action_button.setObjectName('primary')
        self.action_button.hide()
        self.action_button.clicked.connect(self._download_or_install)
        self._ready = False
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.action_button)
        layout.addLayout(buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        self.refresh()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._closed = True
        self.timer.stop()
        super().closeEvent(event)

    def refresh(self):
        if self._pending or self._closed:
            return
        self._pending = True
        self.client.request('GET', '/api/updates', on_success=self._received, on_error=self._failed)

    def _action(self, action):
        if self._pending:
            return
        self._pending = True
        self.check_button.setEnabled(False)
        self.action_button.setEnabled(False)
        self.message.setText('正在处理…')
        self._action_error = ''
        body = {'desktop_pid': os.getpid()} if action == 'install' else {}
        self.client.request('POST', '/api/updates/' + action, body,
                            on_success=self._received, on_error=lambda message: self._failed(message, action=True))

    def _download_or_install(self):
        self._action('install' if self._ready else 'download')

    def _failed(self, message, action=False):
        self._pending = False
        if self._closed:
            return
        if action:
            self._action_error = message
        self.message.setText(self._action_error or message)
        self.check_button.setEnabled(True)
        self.action_button.setEnabled(True)

    def _received(self, payload):
        self._pending = False
        if self._closed:
            return
        update = payload.get('update', {})
        status = update.get('status', 'idle')
        release = update.get('release')
        busy = status in ('checking', 'downloading', 'installing') or update.get('updating', False)
        self._ready = status == 'ready'
        self.check_button.setEnabled(not busy)
        self.action_button.setEnabled(not busy)
        self.action_button.setVisible(bool(release) and update.get('install_supported', False))
        self.action_button.setText('更新并重启' if self._ready else '下载更新')
        self.version.setText(f'Assistant {update.get("version", VERSION)}')
        if release:
            self.notes.setText(f'新版本 {release["version"]}\n{release["notes"]}')
        self.notes.setVisible(bool(release))
        messages = {'idle': '从已绑定的 OC 获取管理员发布的版本。', 'checking': '正在检查更新…',
                    'available': '有新版本可用，可先下载，任务结束后再安装。',
                    'downloading': '正在下载并校验更新包…', 'installing': '正在更新并重启…'}
        message = update.get('message') or messages.get(status, '')
        if not update.get('install_supported', False):
            message += '\n源码运行仅检查版本；安装更新请使用便携版。'
        result = update.get('last_result')
        if result and status == 'idle':
            message = result.get('message', message)
        self.message.setText(self._action_error or message)
        self.progress.setVisible(status == 'downloading')
        if release:
            self.progress.setRange(0, release['size'])
            self.progress.setValue(update.get('received', 0))
        if status == 'installing' and update.get('desktop_pid') == os.getpid() and not self._quitting:
            self._quitting = True
            self.restart_requested.emit()
