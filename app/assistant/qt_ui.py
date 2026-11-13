"""紧凑的 Assistant 原生窗口，后台执行服务拥有独立生命周期。"""
import json

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .qt_chrome import CaptionWindowMixin, install_title_bar
from .qt_controls import AnimatedTabWidget
from .qt_dialogs import JobDialog, ParameterDialog, label
from .qt_settings import SettingsPage, BINDING_LABELS
from .qt_theme import (ACTIVE_STATES, STATE_LABELS, CardItemDelegate,
                       display_time, make_app_icon, make_symbol_icon)


class AssistantWindow(CaptionWindowMixin, QMainWindow):
    def __init__(self, client, state_dir, parent=None):
        super().__init__(parent)
        self.client = client
        self.state_dir = state_dir
        self.tray_available = False
        self.connected = False
        self.packages = []
        self.jobs = []
        self.job_total = 0
        self.active_parameter_dialog = None
        self.settings_page = None
        self._dialogs = []
        self._file_dialog = None
        self._pending_refresh = 0
        self._refresh_errors = []
        self._import_busy = False
        self._closed = False
        self._preferred_package = None
        self._package_snapshot = None
        self._job_snapshot = None
        self.setWindowTitle('WBot Assistant')
        self.setWindowIcon(make_app_icon())
        self.resize(480, 700)
        self.setMinimumSize(420, 560)
        self._build()
        install_title_bar(self)
        self.back_shortcut = QShortcut(QKeySequence('Escape'), self)
        self.back_shortcut.activated.connect(self.show_home)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        QTimer.singleShot(0, self.refresh)

    def _build(self):
        body = QWidget()
        self.home_page = body
        self.pages = QStackedWidget()
        self.pages.addWidget(body)
        self.setCentralWidget(self.pages)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 26, 28, 20)
        layout.setSpacing(18)
        header = QHBoxLayout()
        header.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(self.windowIcon().pixmap(44, 44))
        icon.setFixedSize(44, 44)
        header.addWidget(icon)
        brand = QVBoxLayout()
        brand.setSpacing(3)
        brand.addWidget(label('Assistant', 'brand'))
        brand.addWidget(label('WBot 自动化助手', 'brandCaption'))
        header.addLayout(brand)
        header.addStretch()
        self.connection = label('连接中', 'connection')
        header.addWidget(self.connection)
        self.settings_button = QPushButton()
        self.settings_button.setObjectName('iconButton')
        self.settings_button.setIcon(make_symbol_icon('settings', '#6E6E73', 'transparent'))
        self.settings_button.setIconSize(QSize(22, 22))
        self.settings_button.setFixedSize(40, 40)
        self.settings_button.setAccessibleName('连接设置')
        self.settings_button.setToolTip('连接 OC 管理平台')
        self.settings_button.clicked.connect(self.open_settings)
        header.addWidget(self.settings_button)
        layout.addLayout(header)
        self.oc_connection = QPushButton('OC：读取连接状态…')
        self.oc_connection.setObjectName('ocConnection')
        self.oc_connection.setAccessibleName('OC 连接状态，打开设置')
        self.oc_connection.clicked.connect(self.open_settings)
        layout.addWidget(self.oc_connection)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName('searchField')
        self.search.setFixedHeight(42)
        self.search.setAccessibleName('搜索自动化或运行记录')
        self.search.setPlaceholderText('搜索自动化或运行记录')
        self.search.setClearButtonEnabled(True)
        self.search.addAction(make_symbol_icon('search', '#8E8E93', 'transparent'),
                              QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._filter_lists)
        tools.addWidget(self.search, 1)
        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(make_symbol_icon('refresh', '#6E6E73', 'transparent'))
        self.refresh_button.setIconSize(QSize(18, 18))
        self.refresh_button.setFixedSize(42, 42)
        self.refresh_button.setObjectName('iconButton')
        self.refresh_button.setToolTip('刷新后台状态')
        self.refresh_button.setAccessibleName('刷新后台状态')
        self.refresh_button.clicked.connect(self.refresh)
        tools.addWidget(self.refresh_button)
        layout.addLayout(tools)
        self.message = label('', 'message', True)
        self.message.hide()
        layout.addWidget(self.message)
        self.tabs = AnimatedTabWidget()
        self.tabs.setObjectName('mainTabs')
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setFixedHeight(38)
        self.tabs.addTab(self._packages_page(), '我的自动化')
        self.tabs.addTab(self._history_page(), '运行记录')
        layout.addWidget(self.tabs, 1)
        footer = QFrame()
        footer.setObjectName('footer')
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 12, 0, 0)
        footer_layout.setSpacing(4)
        self.activity = label('本机就绪', 'footerStatus')
        footer_layout.addWidget(self.activity)
        footer_layout.addWidget(label('关闭窗口，任务仍在后台继续。', 'hint'))
        layout.addWidget(footer)
        self._update_enabled()

    @staticmethod
    def _empty_state(title, description, symbol):
        frame = QFrame()
        frame.setObjectName('emptyState')
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 24, 18, 24)
        layout.setSpacing(10)
        layout.addStretch()
        icon = QLabel()
        icon.setPixmap(make_symbol_icon(symbol, '#8C9BB1', '#EEF1F6').pixmap(64, 64))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        title_label = label(title, 'emptyTitle', True)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description_label = label(description, 'hint', True)
        description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        layout.addStretch()
        return frame, title_label, description_label

    def _packages_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        self.package_count = label('0 个自动化', 'hint')
        heading.addWidget(self.package_count)
        heading.addStretch()
        self.host_button = QPushButton('托管流程')
        self.host_button.setObjectName('secondary')
        self.host_button.setAccessibleName('托管自带虚拟环境的流程目录')
        self.host_button.clicked.connect(self.choose_project)
        heading.addWidget(self.host_button)
        self.import_button = QPushButton('导入')
        self.import_button.setObjectName('secondary')
        self.import_button.setIcon(make_symbol_icon('import', '#007AFF', 'transparent'))
        self.import_button.setIconSize(QSize(16, 16))
        self.import_button.setAccessibleName('导入自动化包')
        self.import_button.clicked.connect(self.choose_package)
        heading.addWidget(self.import_button)
        layout.addLayout(heading)
        self.empty_packages, self.empty_package_title, self.empty_package_hint = self._empty_state(
            '添加你的第一个自动化', '选择已准备独立虚拟环境的流程目录，开始托管。', 'automation')
        layout.addWidget(self.empty_packages, 1)
        self.package_list = QListWidget()
        self.package_list.setAccessibleName('自动化列表')
        self.package_list.setSpacing(4)
        self.package_list.setItemDelegate(CardItemDelegate(self.package_list))
        self.package_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.package_list.currentItemChanged.connect(self._update_enabled)
        self.package_list.itemActivated.connect(self.open_run_dialog)
        layout.addWidget(self.package_list, 1)
        self.run_button = QPushButton('运行所选自动化')
        self.run_button.setObjectName('primary')
        self.run_button.setFixedHeight(46)
        self.run_button.setIcon(make_symbol_icon('play', '#FFFFFF', 'transparent'))
        self.run_button.setIconSize(QSize(18, 18))
        self.run_button.clicked.connect(self.open_run_dialog)
        layout.addWidget(self.run_button)
        return page

    def _history_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 20, 0, 0)
        layout.setSpacing(14)
        self.history_count = label('还没有运行记录', 'hint')
        layout.addWidget(self.history_count)
        self.empty_jobs, self.empty_job_title, self.empty_job_hint = self._empty_state(
            '每次运行，都有迹可循', '任务开始后，日志和结果会出现在这里。', 'history')
        layout.addWidget(self.empty_jobs, 1)
        self.job_list = QListWidget()
        self.job_list.setAccessibleName('运行记录列表')
        self.job_list.setSpacing(4)
        self.job_list.setItemDelegate(CardItemDelegate(self.job_list))
        self.job_list.currentItemChanged.connect(self._update_enabled)
        self.job_list.itemActivated.connect(self.open_job_dialog)
        layout.addWidget(self.job_list, 1)
        self.details_button = QPushButton('查看运行详情')
        self.details_button.setFixedHeight(46)
        self.details_button.clicked.connect(self.open_job_dialog)
        layout.addWidget(self.details_button)
        return page

    def _show_message(self, text, error=False):
        self.message.setText(text)
        self.message.setProperty('error', error)
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.setVisible(bool(text))

    def refresh(self):
        if self._closed or self._pending_refresh:
            return
        self._pending_refresh = 3
        self._refresh_errors = []
        self.refresh_button.setEnabled(False)
        self.client.request('GET', '/api/settings', on_success=self._received_connection, on_error=self._connection_failed)
        self.client.request('GET', '/api/packages', on_success=self._received_packages, on_error=self._refresh_failed)
        self.client.request('GET', '/api/jobs/summary', on_success=self._received_jobs, on_error=self._refresh_failed)

    def _received_connection(self, response):
        if self._closed:
            return
        settings = response['settings']
        state = 'offline' if settings.get('error') else settings.get('binding_state', 'unconfigured')
        self.oc_connection.setText('OC：' + BINDING_LABELS.get(state, state) + '  ·  连接设置')
        self.oc_connection.setToolTip(settings.get('server_url') or '填写 OC 地址并申请设备绑定')
        self.oc_connection.setProperty('offline', state in ('offline', 'revoked', 'rejected'))
        self.oc_connection.style().unpolish(self.oc_connection)
        self.oc_connection.style().polish(self.oc_connection)
        self._finish_refresh()

    def _connection_failed(self, message):
        if self._closed:
            return
        self.oc_connection.setText('OC：状态暂不可用  ·  连接设置')
        self.oc_connection.setToolTip(message)
        self._finish_refresh()

    def _received_packages(self, response):
        if self._closed:
            return
        self.packages = response['items']
        snapshot = json.dumps(self.packages, sort_keys=True)
        if snapshot != self._package_snapshot or self._preferred_package:
            self._package_snapshot = snapshot
            self._render_packages()
        self._finish_refresh()

    def _received_jobs(self, response):
        if self._closed:
            return
        self.jobs = response['items']
        self.job_total = response['total']
        snapshot = json.dumps({'items': self.jobs, 'total': self.job_total}, sort_keys=True)
        if snapshot != self._job_snapshot:
            self._job_snapshot = snapshot
            self._render_jobs()
        self._finish_refresh()

    def _refresh_failed(self, message):
        if self._closed:
            return
        self._refresh_errors.append(message)
        self._finish_refresh()

    def _finish_refresh(self):
        self._pending_refresh -= 1
        if self._pending_refresh:
            return
        was_connected = self.connected
        self.connected = not self._refresh_errors
        self.connection.setText('本机就绪' if self.connected else '本机离线')
        self.connection.setProperty('offline', not self.connected)
        self.connection.style().unpolish(self.connection)
        self.connection.style().polish(self.connection)
        self.refresh_button.setEnabled(True)
        if not self.connected:
            self._show_message(self._refresh_errors[0] + '；正在重连，保留上次记录。', True)
        elif not was_connected:
            self._show_message('')
        active = sum(job['state'] in ACTIVE_STATES for job in self.jobs)
        self.activity.setText(f'{active} 个任务正在后台运行' if active else
                              '本机就绪' if self.connected else '等待连接本机服务')
        if self.active_parameter_dialog:
            self.active_parameter_dialog.set_online(self.connected)
        self._update_enabled()

    @staticmethod
    def _selected_id(widget):
        item = widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _filter_lists(self):
        self._render_packages()
        self._render_jobs()

    def _render_packages(self):
        selected = self._preferred_package or self._selected_id(self.package_list)
        self.package_list.clear()
        query = self.search.text().casefold()
        colors = [('#007AFF', '#EAF3FF'), ('#5856D6', '#F0EFFF'), ('#C77813', '#FFF3E2')]
        for index, package in enumerate(self.packages):
            manifest = package['manifest']
            if query not in package['id'].casefold():
                continue
            item = QListWidgetItem(f'{manifest["name"]}\n版本 {manifest["version"]}   ·   {len(manifest.get("parameters", {}))} 项参数')
            item.setData(Qt.ItemDataRole.UserRole, package['id'])
            item.setIcon(make_symbol_icon('automation', *colors[index % len(colors)]))
            item.setSizeHint(QSize(0, 88))
            item.setToolTip(item.text() + '\n' + package['id'] + '\n' +
                            (package.get('project_path') or '尚未登记流程环境，请先托管对应流程目录'))
            self.package_list.addItem(item)
            if package['id'] == selected:
                self.package_list.setCurrentItem(item)
                self._preferred_package = None
        self.package_count.setText(f'{len(self.packages)} 个自动化')
        self.empty_packages.setVisible(not self.package_list.count())
        self.empty_package_title.setText('没有找到自动化' if query else '添加你的第一个自动化')
        self.empty_package_hint.setText('试试其他名称，或清空搜索。' if query else
                                        '选择已准备独立虚拟环境的流程目录，开始托管。')
        self.package_list.setVisible(bool(self.package_list.count()))
        self._update_enabled()

    def _render_jobs(self):
        selected = self._selected_id(self.job_list)
        self.job_list.clear()
        query = self.search.text().casefold()
        for job in self.jobs:
            if query not in (job['package_id'] + ' ' + job['id']).casefold():
                continue
            name = job['package_id'].split('@')[0]
            state = STATE_LABELS.get(job['state'], job['state'])
            item = QListWidgetItem(f'{name}\n{state}   ·   {display_time(job["created_at"])}')
            item.setData(Qt.ItemDataRole.UserRole, job['id'])
            if job['state'] == 'succeeded':
                item.setIcon(make_symbol_icon('check', '#248A3D', '#EBF7EE'))
            elif job['state'] in ('failed', 'interrupted'):
                item.setIcon(make_symbol_icon('error', '#D4433B', '#FFF0EF'))
            else:
                item.setIcon(make_symbol_icon('history', '#007AFF', '#EAF3FF'))
            item.setSizeHint(QSize(0, 88))
            item.setToolTip(item.text() + '\n' + job['package_id'] + '\n' + job['id'])
            self.job_list.addItem(item)
            if job['id'] == selected:
                self.job_list.setCurrentItem(item)
        self.history_count.setText(f'共 {self.job_total} 次运行 · 最近 {len(self.jobs)} 条' if self.job_total > 200 else
                                   f'{self.job_total} 次运行 · 选择记录查看日志和结果')
        self.empty_jobs.setVisible(not self.job_list.count())
        self.empty_job_title.setText('没有找到运行记录' if query else '每次运行，都有迹可循')
        self.empty_job_hint.setText('试试其他名称，或清空搜索。' if query else
                                   '任务开始后，日志和结果会出现在这里。')
        self.job_list.setVisible(bool(self.job_list.count()))
        self._update_enabled()

    def _update_enabled(self, *_args):
        if self._closed or not hasattr(self, 'details_button'):
            return
        busy = any(job['state'] in ACTIVE_STATES for job in self.jobs)
        self.import_button.setEnabled(self.connected and not self._import_busy)
        self.host_button.setEnabled(self.connected and not busy and not self._import_busy)
        selected = next((item for item in self.packages if item['id'] == self._selected_id(self.package_list)), None)
        ready = selected is not None and bool(selected.get('project_path'))
        self.run_button.setEnabled(self.connected and not busy and ready)
        self.run_button.setText('后台任务运行中' if busy else
                               '请先托管流程环境' if selected and not ready else '运行所选自动化')
        self.details_button.setEnabled(self._selected_id(self.job_list) is not None)

    def choose_package(self):
        self._choose_source('导入自动化发布包', QFileDialog.FileMode.ExistingFile,
                            self.import_package, '自动化发布包 (*.wbot.zip)')

    def choose_project(self):
        self._choose_source('选择包含 wbot.json 和 .venv 的流程目录', QFileDialog.FileMode.Directory,
                            self.host_project)

    def _choose_source(self, title, mode, selected, name_filter=None):
        if not self.connected or self._import_busy:
            return
        if self._file_dialog:
            self._file_dialog.raise_()
            return
        self._file_dialog = QFileDialog(self, title)
        if name_filter:
            self._file_dialog.setNameFilter(name_filter)
        self._file_dialog.setFileMode(mode)
        self._file_dialog.fileSelected.connect(selected)
        self._file_dialog.finished.connect(self._file_dialog_closed)
        self._file_dialog.open()

    def _file_dialog_closed(self):
        dialog = self._file_dialog
        self._file_dialog = None
        if dialog:
            dialog.deleteLater()

    def import_package(self, path):
        self._import_source(path, '/api/packages', '正在校验并导入发布包…')

    def host_project(self, path):
        self._import_source(path, '/api/projects', '正在校验流程代码及其独立虚拟环境…')

    def _import_source(self, path, endpoint, message):
        if self._closed or self._import_busy or not self.connected:
            return
        self._import_busy = True
        self._update_enabled()
        self._show_message(message)
        self.client.request('POST', endpoint, {'path': path},
                            on_success=self._package_imported, on_error=self._import_failed)

    def _package_imported(self, response):
        if self._closed:
            return
        self._import_busy = False
        self.search.clear()
        self._preferred_package = response['package']['id']
        self.tabs.setCurrentIndex(0)
        self._show_message('已导入 ' + response['package']['manifest']['name'])
        self._update_enabled()
        self.refresh()

    def _import_failed(self, message):
        if self._closed:
            return
        self._import_busy = False
        self._show_message(message, True)
        self._update_enabled()

    def open_run_dialog(self, *_args):
        if not self.run_button.isEnabled():
            return
        if self.active_parameter_dialog:
            self.active_parameter_dialog.raise_()
            self.active_parameter_dialog.activateWindow()
            return
        selected = self._selected_id(self.package_list)
        package = next((item for item in self.packages if item['id'] == selected), None)
        if package is None:
            return
        dialog = ParameterDialog(self.client, package, self)
        self.active_parameter_dialog = dialog
        dialog.submitted.connect(self._job_submitted)
        self._track_dialog(dialog)

    def _job_submitted(self, job):
        self.tabs.setCurrentIndex(1)
        self.refresh()
        self.open_job_dialog(job)

    def open_job_dialog(self, job=None):
        if not isinstance(job, dict):
            selected = self._selected_id(self.job_list)
            job = next((item for item in self.jobs if item['id'] == selected), None)
        if job is None:
            return
        for dialog in self._dialogs:
            if isinstance(dialog, JobDialog) and dialog.job['id'] == job['id']:
                dialog.raise_()
                dialog.activateWindow()
                return
        self._track_dialog(JobDialog(self.client, job, self))

    def open_settings(self):
        if self._closed:
            return
        if self.settings_page is None:
            self.settings_page = SettingsPage(self.client, self.state_dir, self.pages)
            self.settings_page.back_requested.connect(self.show_home)
            self.settings_page.restart_requested.connect(self.shutdown_ui)
            self.settings_page.binding_changed.connect(self.settings_button.setToolTip)
            self.pages.addWidget(self.settings_page)
        self.pages.setCurrentWidget(self.settings_page)
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        self.settings_page.back_button.setFocus()

    def show_home(self):
        if self._closed or self.pages.currentWidget() is self.home_page:
            return
        self.pages.setCurrentWidget(self.home_page)
        self.settings_button.setFocus()

    def _track_dialog(self, dialog):
        dialog._return_focus = QApplication.focusWidget()
        self._dialogs.append(dialog)
        dialog.finished.connect(lambda _result: self._dialog_closed(dialog))
        dialog.show()

    def _dialog_closed(self, dialog):
        if dialog is self.active_parameter_dialog:
            self.active_parameter_dialog = None
        if dialog in self._dialogs:
            self._dialogs.remove(dialog)
        if not self._closed and dialog._return_focus is not None:
            dialog._return_focus.setFocus()
        dialog.deleteLater()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def shutdown_ui(self):
        self._closed = True
        self.timer.stop()
        if self.settings_page is not None:
            self.settings_page.close()
        for dialog in list(self._dialogs):
            dialog.close()
        if self._file_dialog:
            self._file_dialog.close()
        self.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        if self.tray_available and not self._closed:
            self.hide()
            event.ignore()
            return
        self.shutdown_ui()
        event.accept()
