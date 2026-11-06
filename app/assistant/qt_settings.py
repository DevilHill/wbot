"""管理平台连接设置；批准凭据只由本机服务持有。"""
import ipaddress
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .qt_dialogs import label
from .qt_theme import display_time, make_symbol_icon


BINDING_LABELS = {'unconfigured': '尚未连接', 'connecting': '正在提交申请',
                  'pending': '等待管理员批准', 'approved': '已绑定',
                  'rejected': '申请被拒绝', 'revoked': '授权已撤销',
                  'disconnected': '已断开', 'offline': '连接异常'}
BINDING_HINTS = {
    'unconfigured': '填写 OC 所在电脑的服务地址，申请绑定这台设备。',
    'connecting': '正在向 OC 提交绑定申请，状态会自动更新。',
    'pending': '请管理员在 OC 中核对下方确认码，并批准这台设备。',
    'approved': '管理员已批准此设备，连接状态会自动更新。',
    'rejected': '管理员拒绝了本次申请，请核对信息后重新申请。',
    'revoked': '设备授权已被管理员撤销，需要重新申请并获得批准。',
    'disconnected': '已暂停与 OC 的连接。重新连接可继续使用现有授权。',
    'offline': '暂时无法连接 OC，请检查地址及网络，状态会自动更新。',
}


class SettingsDialog(QDialog):
    binding_changed = Signal(str)

    def __init__(self, client, state_dir, parent=None):
        super().__init__(parent)
        self.client = client
        self.state_dir = state_dir
        self.settings = {}
        self.closed = False
        self.busy = False
        self.online = False
        self._poll_pending = False
        self._revision = 0
        self._draft_edited = False
        self._syncing_fields = False
        self._action_error = ''
        self._poll_error = ''
        self.setWindowTitle('连接设置 · WBot Assistant')
        self.resize(520, 700)
        self.setMinimumSize(440, 560)
        self._build()
        self._render_settings()
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        QTimer.singleShot(0, self.refresh)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 26, 24, 22)
        layout.setSpacing(18)
        header = QHBoxLayout()
        header.setSpacing(14)
        icon = QLabel()
        icon.setPixmap(make_symbol_icon('settings').pixmap(48, 48))
        icon.setFixedSize(48, 48)
        header.addWidget(icon)
        title = QVBoxLayout()
        title.setSpacing(5)
        title.addWidget(label('连接管理平台', 'dialogTitle'))
        title.addWidget(label('让企业 OC 管理这台设备的连接与授权。', 'subtitle', True))
        header.addLayout(title, 1)
        layout.addLayout(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        sections = QVBoxLayout(content)
        sections.setContentsMargins(0, 0, 4, 0)
        sections.setSpacing(14)
        sections.addWidget(self._connection_fields())
        self.transport_hint = label('当前地址使用 HTTP。跨电脑连接建议使用 HTTPS，保护传输中的数据。',
                                    'transportHint', True)
        self.transport_hint.hide()
        sections.addWidget(self.transport_hint)
        sections.addWidget(self._binding_card())
        self.error = label('', 'message', True)
        self.error.setProperty('error', True)
        self.error.hide()
        sections.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.error)
        layout.addWidget(label('断开后可重新连接；设备授权由 OC 管理员管理。', 'hint', True))
        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        self.disconnect_button = QPushButton('断开连接')
        self.disconnect_button.setObjectName('danger')
        self.disconnect_button.setFixedHeight(48)
        self.disconnect_button.clicked.connect(self.disconnect_service)
        buttons.addWidget(self.disconnect_button)
        self.connect_button = QPushButton('保存并申请绑定')
        self.connect_button.setObjectName('primary')
        self.connect_button.setFixedHeight(48)
        self.connect_button.clicked.connect(self.connect_service)
        buttons.addWidget(self.connect_button, 1)
        layout.addLayout(buttons)

    def _connection_fields(self):
        card = QFrame()
        card.setObjectName('settingsCard')
        fields = QVBoxLayout(card)
        fields.setContentsMargins(18, 18, 18, 18)
        fields.setSpacing(9)
        fields.addWidget(label('OC 服务地址', 'fieldLabel'))
        self.server_url = QLineEdit()
        self.server_url.setAccessibleName('OC 服务地址')
        self.server_url.setPlaceholderText('例如 http://192.168.1.20:8793')
        self.server_url.setFixedHeight(44)
        self.server_url.textChanged.connect(self._draft_changed)
        fields.addWidget(self.server_url)
        fields.addWidget(label('填写管理平台所在电脑的地址，支持 HTTP 和 HTTPS。', 'hint', True))
        fields.addSpacing(6)
        fields.addWidget(label('设备名称', 'fieldLabel'))
        self.device_name = QLineEdit()
        self.device_name.setAccessibleName('设备名称')
        self.device_name.setPlaceholderText('例如 财务部电脑')
        self.device_name.setFixedHeight(44)
        self.device_name.textChanged.connect(self._draft_changed)
        fields.addWidget(self.device_name)
        return card

    def _binding_card(self):
        card = QFrame()
        card.setObjectName('settingsCard')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        heading.addWidget(label('设备绑定', 'fieldLabel'))
        heading.addStretch()
        self.state_label = label('', 'stateBadge')
        heading.addWidget(self.state_label)
        layout.addLayout(heading)
        self.binding_hint = label('', 'subtitle', True)
        layout.addWidget(self.binding_hint)
        self.verification_code = label('', 'verificationCode')
        self.verification_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.verification_code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.verification_code)
        self.connection_details = label('', 'hint', True)
        self.connection_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.connection_details)
        self.pending_reports_hint = label('', 'message', True)
        self.pending_reports_hint.hide()
        layout.addWidget(self.pending_reports_hint)
        return card

    def _draft_changed(self):
        if not self._syncing_fields:
            self._draft_edited = True
        if not hasattr(self, 'connect_button'):
            return
        self._update_transport_hint()
        self._update_enabled()

    def _set_draft(self):
        self._syncing_fields = True
        try:
            self.server_url.setText(self.settings.get('server_url') or '')
            self.device_name.setText(self.settings.get('device_name') or '')
        finally:
            self._syncing_fields = False
        self._draft_edited = False

    def _draft_differs(self):
        return (self.server_url.text().strip() != (self.settings.get('server_url') or '')
                or self.device_name.text().strip() != (self.settings.get('device_name') or ''))

    def _update_transport_hint(self):
        try:
            address = urlsplit(self.server_url.text().strip())
            hostname = address.hostname or ''
            loopback = hostname.lower() == 'localhost'
            try:
                loopback = loopback or ipaddress.ip_address(hostname).is_loopback
            except ValueError:
                pass
            self.transport_hint.setVisible(address.scheme == 'http' and bool(hostname) and not loopback)
        except ValueError:
            self.transport_hint.hide()

    def _update_enabled(self):
        state = self.settings.get('binding_state', 'unconfigured')
        changed = self._draft_differs()
        retryable = state not in ('connecting', 'pending', 'approved')
        complete = bool(self.server_url.text().strip() and self.device_name.text().strip())
        self.connect_button.setEnabled(self.online and not self.busy and complete and (changed or retryable))
        configured = bool(self.settings.get('server_url')) and state not in ('unconfigured', 'disconnected')
        self.disconnect_button.setEnabled(self.online and not self.busy and configured)
        self.server_url.setEnabled(not self.busy)
        self.device_name.setEnabled(not self.busy)
        if self.busy:
            self.connect_button.setText('正在处理…')
        elif state == 'disconnected' and not changed:
            self.connect_button.setText('重新连接')
        elif state in ('rejected', 'revoked') and not changed:
            self.connect_button.setText('重新申请绑定')
        elif self.settings.get('server_url') and changed:
            self.connect_button.setText('保存并重新申请')
        else:
            self.connect_button.setText('保存并申请绑定')

    def _render_settings(self):
        state = self.settings.get('binding_state', 'unconfigured')
        self.state_label.setText(BINDING_LABELS.get(state, state))
        self.state_label.setProperty('failed', state in ('rejected', 'revoked', 'offline'))
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)
        self.binding_hint.setText(BINDING_HINTS.get(state, '连接状态会自动更新。'))
        code = self.settings.get('verification_code') or ''
        self.verification_code.setText('确认码  ' + str(code))
        self.verification_code.setVisible(bool(code))
        address = self.settings.get('server_url') or ''
        details = (f'当前地址  {address}\n设备名称  {self.settings.get("device_name") or "—"}\n'
                   f'设备标识  {self.settings.get("device_id") or "—"}\n'
                   f'最近连接  {display_time(self.settings.get("last_connected_at"))}')
        self.connection_details.setText(details)
        self.connection_details.setVisible(bool(address))
        pending_reports = self.settings.get('pending_reports', 0)
        self.pending_reports_hint.setText(f'有 {pending_reports} 条结果待同步；连接原 OC 后会继续回传。')
        self.pending_reports_hint.setVisible(pending_reports > 0)
        message = self._action_error or self._poll_error or self.settings.get('error') or ''
        self.error.setText(message)
        self.error.setVisible(bool(message))
        self._update_transport_hint()
        self._update_enabled()
        summary = 'OC：' + BINDING_LABELS.get(state, state)
        if address:
            summary += '\n' + address
        self.binding_changed.emit(summary)

    def refresh(self):
        if self.closed or self.busy or self._poll_pending:
            return
        self._poll_pending = True
        revision = self._revision
        self.client.request('GET', '/api/settings',
                            on_success=lambda response: self._received_settings(response, revision),
                            on_error=lambda message: self._poll_failed(message, revision))

    def _received_settings(self, response, revision):
        if self.closed:
            return
        self._poll_pending = False
        if revision != self._revision:
            return
        self.online = True
        self._poll_error = ''
        self.settings = response['settings']
        if not self._draft_edited:
            self._set_draft()
        self._render_settings()

    def _poll_failed(self, message, revision):
        if self.closed:
            return
        self._poll_pending = False
        if revision != self._revision:
            return
        self.online = False
        self._poll_error = message + '；正在重试，保留上次连接状态。'
        self._render_settings()

    def connect_service(self):
        if self.closed or not self.connect_button.isEnabled():
            return
        body = {'server_url': self.server_url.text().strip(), 'device_name': self.device_name.text().strip()}
        self._perform_action('/api/settings/connect', body)

    def disconnect_service(self):
        if self.closed or not self.disconnect_button.isEnabled():
            return
        self._perform_action('/api/settings/disconnect', {})

    def _perform_action(self, path, body):
        self.busy = True
        self._revision += 1
        self._action_error = ''
        self.error.hide()
        self._update_enabled()
        self.client.request('POST', path, body, on_success=self._action_completed, on_error=self._action_failed)

    def _action_completed(self, response):
        if self.closed:
            return
        self.busy = False
        self.online = True
        self._poll_error = ''
        self.settings = response['settings']
        self._set_draft()
        self._render_settings()

    def _action_failed(self, message):
        if self.closed:
            return
        self.busy = False
        self._action_error = message
        self._render_settings()

    def done(self, result):
        self.closed = True
        self.timer.stop()
        super().done(result)
