"""参数填写与运行详情；所有后台通信通过异步客户端完成。"""
import json
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
                               QTabWidget, QVBoxLayout, QWidget)

from app.automation_package import resolve_parameters
from .protocol import MAX_REQUEST_BYTES
from .qt_theme import ACTIVE_STATES, STATE_LABELS, display_time, make_symbol_icon


def label(text='', name='', wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


class _ParameterComboBox(QComboBox):
    """样式化后补绘下拉指示，弹出列表仍由原生控件处理。"""
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#86868B' if self.isEnabled() else '#B8B8BE'), 1.5,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        arrow = QPainterPath()
        arrow.moveTo(self.width() - 25, self.height() / 2 - 2)
        arrow.lineTo(self.width() - 21, self.height() / 2 + 2)
        arrow.lineTo(self.width() - 17, self.height() / 2 - 2)
        painter.drawPath(arrow)


class ParameterDialog(QDialog):
    submitted = Signal(dict)

    def __init__(self, client, package, parent=None):
        super().__init__(parent)
        self.client = client
        self.package = package
        self.fields = {}
        self.closed = False
        self.busy = False
        self.online = True
        self._pending_signature = None
        self._request_id = None
        self.setWindowTitle('运行自动化 · WBot Assistant')
        self.resize(460, 560)
        self.setMinimumWidth(380)
        self.setModal(False)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 26, 24, 24)
        layout.setSpacing(18)
        manifest = self.package['manifest']
        header = QHBoxLayout()
        header.setSpacing(14)
        icon = QLabel()
        icon.setPixmap(make_symbol_icon('automation').pixmap(48, 48))
        icon.setFixedSize(48, 48)
        header.addWidget(icon)
        heading = QVBoxLayout()
        heading.setSpacing(5)
        heading.addWidget(label(manifest['name'], 'dialogTitle', True))
        heading.addWidget(label(f'版本 {manifest["version"]} · 在本机运行', 'subtitle'))
        header.addLayout(heading, 1)
        layout.addLayout(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName('parameterFields')
        fields_layout = QVBoxLayout(content)
        fields_layout.setContentsMargins(18, 18, 18, 18)
        fields_layout.setSpacing(8)
        for name, definition in manifest.get('parameters', {}).items():
            caption = name + (' *' if definition.get('required') else '')
            fields_layout.addWidget(label(caption, 'fieldLabel'))
            field = self._make_field(definition)
            field.setMinimumHeight(42)
            field.setAccessibleName(name)
            field.setObjectName('parameter_' + name)
            self.fields[name] = field
            fields_layout.addWidget(field)
            if definition.get('description'):
                fields_layout.addWidget(label(definition['description'], 'hint', True))
            fields_layout.addSpacing(10)
        if not self.fields:
            fields_layout.addWidget(label('这个自动化无需填写参数。', 'hint'))
        fields_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.error = label('', 'message', True)
        self.error.setProperty('error', True)
        self.error.hide()
        layout.addWidget(self.error)
        layout.addWidget(label('任务由后台执行，关闭窗口不会中断运行。', 'hint', True))
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.cancel_button = QPushButton('取消')
        self.cancel_button.setFixedSize(96, 48)
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)
        self.run_button = QPushButton('开始运行')
        self.run_button.setObjectName('primary')
        self.run_button.setFixedSize(152, 48)
        self.run_button.setIcon(make_symbol_icon('play', '#FFFFFF', 'transparent'))
        self.run_button.setIconSize(QSize(18, 18))
        self.run_button.setDefault(True)
        self.run_button.clicked.connect(self.submit)
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.run_button)
        layout.addLayout(buttons)

    @staticmethod
    def _make_field(definition):
        default = definition.get('default')
        if definition['type'] == 'boolean':
            field = _ParameterComboBox()
            field.addItem('不指定，使用默认值', None)
            field.addItem('是', True)
            field.addItem('否', False)
            field.setCurrentIndex(1 if default is True else 2 if default is False else 0)
            return field
        field = QLineEdit()
        field.setMaxLength(MAX_REQUEST_BYTES)
        field.setText('' if default is None else str(default))
        if definition['type'] == 'integer':
            field.setPlaceholderText('请输入整数')
        elif definition['type'] == 'number':
            field.setPlaceholderText('请输入数值')
        return field

    def parameters(self):
        values = {}
        for name, definition in self.package['manifest']['parameters'].items():
            field = self.fields[name]
            kind = definition['type']
            if kind == 'boolean':
                value = field.currentData()
                if value is not None:
                    values[name] = value
                continue
            value = field.text()
            if kind == 'string':
                values[name] = value
            elif value.strip():
                try:
                    values[name] = int(value) if kind == 'integer' else float(value)
                except ValueError as exc:
                    raise ValueError(f'{name} 必须是' + ('整数' if kind == 'integer' else '数值')) from exc
        return resolve_parameters(self.package['manifest'], values)

    def set_online(self, online):
        self.online = online
        self._update_enabled()

    def _update_enabled(self):
        if self.closed:
            return
        self.run_button.setEnabled(self.online and not self.busy)
        self.run_button.setText('正在提交…' if self.busy else '开始运行')
        for field in self.fields.values():
            field.setEnabled(not self.busy)

    def submit(self):
        if self.closed or self.busy or not self.online:
            return
        try:
            parameters = self.parameters()
        except ValueError as exc:
            self._failed(str(exc))
            return
        signature = json.dumps(parameters, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if signature != self._pending_signature:
            self._pending_signature = signature
            self._request_id = uuid4().hex
        self.busy = True
        self.error.hide()
        self._update_enabled()
        self.client.request('POST', '/api/jobs',
            {'package_id': self.package['id'], 'parameters': parameters, 'request_id': self._request_id},
            on_success=self._submitted, on_error=self._failed)

    def _submitted(self, response):
        if self.closed:
            return
        self.busy = False
        self.submitted.emit(response['job'])
        self.accept()

    def _failed(self, message):
        if self.closed:
            return
        self.busy = False
        self.error.setText(message)
        self.error.show()
        self._update_enabled()

    def done(self, result):
        self.closed = True
        super().done(result)


class JobDialog(QDialog):
    def __init__(self, client, job, parent=None):
        super().__init__(parent)
        self.client = client
        self.job = job
        self.closed = False
        self.online = False
        self.stopping = False
        self._pending = 0
        self._round_failed = False
        self._log_text = None
        self._result_text = None
        self._parameters_text = None
        self._job_revision = 0
        self.setWindowTitle('运行详情 · WBot Assistant')
        self.resize(620, 650)
        self.setMinimumSize(460, 440)
        self._build()
        self._render_job()
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        QTimer.singleShot(0, self.refresh)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 26, 24, 24)
        layout.setSpacing(16)
        header = QHBoxLayout()
        header.setSpacing(14)
        icon = QLabel()
        icon.setPixmap(make_symbol_icon('history').pixmap(44, 44))
        icon.setFixedSize(44, 44)
        header.addWidget(icon)
        header.addWidget(label(self.job['package_id'], 'dialogTitle', True), 1)
        layout.addLayout(header)
        status_row = QHBoxLayout()
        self.state_label = label('', 'stateBadge')
        status_row.addWidget(self.state_label)
        status_row.addStretch()
        self.stop_button = QPushButton('停止任务')
        self.stop_button.setObjectName('danger')
        self.stop_button.setFixedHeight(38)
        self.stop_button.clicked.connect(self.stop_job)
        status_row.addWidget(self.stop_button)
        layout.addLayout(status_row)
        identity = label('作业 ' + self.job['id'], 'hint', True)
        identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(identity)
        self.times = label('', 'hint', True)
        layout.addWidget(self.times)
        self.error = label('', 'message', True)
        self.error.setProperty('error', True)
        self.error.hide()
        layout.addWidget(self.error)
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.tabBar().setExpanding(True)
        tabs.tabBar().setDrawBase(False)
        tabs.tabBar().setFixedHeight(42)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName('log')
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(20000)
        self.log_view.setPlaceholderText('等待日志…')
        self.result_view = QPlainTextEdit()
        self.result_view.setReadOnly(True)
        self.parameters_view = QPlainTextEdit()
        self.parameters_view.setReadOnly(True)
        tabs.addTab(self.log_view, '执行日志')
        tabs.addTab(self.result_view, '运行结果')
        tabs.addTab(self.parameters_view, '输入参数')
        layout.addWidget(tabs, 1)
        layout.addWidget(label('界面最多显示最近 20000 行；本机日志按服务容量限制保留。', 'hint', True))

    def _render_job(self):
        state = self.job['state']
        self.state_label.setText(STATE_LABELS.get(state, state))
        self.state_label.setProperty('failed', state in ('failed', 'interrupted'))
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)
        self.times.setText('创建 ' + display_time(self.job.get('created_at')) +
                           '    完成 ' + display_time(self.job.get('finished_at')))
        self.stop_button.setVisible(state in ACTIVE_STATES)
        self.stop_button.setEnabled(self.online and not self.stopping and state != 'stopping')
        self.stop_button.setText('正在停止…' if self.stopping or state == 'stopping' else '停止任务')
        result_text = ('尚无返回结果' if self.job.get('result') is None else
                       json.dumps(self.job['result'], ensure_ascii=False, indent=2))
        if result_text != self._result_text:
            self.result_view.setPlainText(result_text)
            self._result_text = result_text
        parameters_text = json.dumps(self.job.get('parameters', {}), ensure_ascii=False, indent=2)
        if parameters_text != self._parameters_text:
            self.parameters_view.setPlainText(parameters_text)
            self._parameters_text = parameters_text
        if self.job.get('error'):
            self.error.setText(self.job['error'])
            self.error.show()

    def refresh(self):
        if self.closed or self._pending or self.stopping:
            return
        self._pending = 2
        self._round_failed = False
        path = '/api/jobs/' + self.job['id']
        revision = self._job_revision
        self.client.request('GET', path, on_success=lambda response: self._received_job(response, revision),
                            on_error=self._refresh_failed)
        self.client.request('GET', path + '/log', on_success=self._received_log, on_error=self._refresh_failed)

    def _received_job(self, response, revision):
        if self.closed:
            return
        # 停止请求发出前的轮询不能覆盖已经接受的停止状态。
        if revision == self._job_revision:
            self.job = response['job']
        self._finish_refresh()

    def _received_log(self, response):
        if self.closed:
            return
        content = response['log']
        if content != self._log_text:
            scrollbar = self.log_view.verticalScrollBar()
            position = scrollbar.value()
            at_bottom = position >= scrollbar.maximum() - 2
            self.log_view.setPlainText(content)
            scrollbar.setValue(scrollbar.maximum() if at_bottom else position)
            self._log_text = content
        self._finish_refresh()

    def _refresh_failed(self, message):
        if self.closed:
            return
        self._round_failed = True
        self.error.setText(message + '；保留最后一次读取的记录。')
        self.error.show()
        self._finish_refresh()

    def _finish_refresh(self):
        self._pending -= 1
        if self._pending:
            return
        self.online = not self._round_failed
        if self.online and not self.job.get('error'):
            self.error.hide()
        self._render_job()

    def stop_job(self):
        if self.closed or self.stopping or not self.online or self.job['state'] not in ACTIVE_STATES:
            return
        self.stopping = True
        self._job_revision += 1
        self._render_job()
        self.client.request('POST', '/api/jobs/' + self.job['id'] + '/stop', {},
                            on_success=self._stopped, on_error=self._stop_failed)

    def _stopped(self, response):
        if self.closed:
            return
        self.stopping = False
        self.job = response['job']
        self._render_job()

    def _stop_failed(self, message):
        if self.closed:
            return
        self.stopping = False
        self.error.setText('停止结果未确认：' + message)
        self.error.show()
        self._render_job()

    def done(self, result):
        self.closed = True
        self.timer.stop()
        super().done(result)
