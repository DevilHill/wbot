"""Guided browser extension setup, independent of OC binding."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout

from .qt_dialogs import label, ThemedComboBox


class BrowserExtensionCard(QFrame):
    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.closed = False
        self.setObjectName('settingsCard')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.addWidget(label('浏览器扩展', 'fieldLabel'))
        layout.addWidget(label('抓取网页元素前，请在使用的浏览器中加载 WBot 扩展。', 'hint', True))
        row = QHBoxLayout()
        self.browser = ThemedComboBox()
        self.browser.setAccessibleName('安装扩展的浏览器')
        self.browser.addItem('Google Chrome', 'chrome')
        self.browser.addItem('Microsoft Edge', 'edge')
        row.addWidget(self.browser, 1)
        self.install = QPushButton('安装浏览器扩展')
        self.install.setObjectName('secondary')
        self.install.clicked.connect(self.prepare)
        row.addWidget(self.install)
        layout.addLayout(row)
        self.directory = QLineEdit()
        self.directory.setReadOnly(True)
        self.directory.setAccessibleName('浏览器扩展目录')
        self.directory.hide()
        layout.addWidget(self.directory)
        actions = QHBoxLayout()
        self.copy = QPushButton('复制目录')
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.directory.text()))
        self.reveal = QPushButton('打开目录')
        self.reveal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.directory.text())))
        self.check = QPushButton('检测扩展连接')
        self.check.clicked.connect(self.check_connection)
        for button in (self.copy, self.reveal, self.check):
            button.setObjectName('secondary')
            actions.addWidget(button)
        self.copy.setEnabled(False)
        self.reveal.setEnabled(False)
        layout.addLayout(actions)
        self.instructions = label('', 'hint', True)
        layout.addWidget(self.instructions)
        self.status = label('', 'message', True)
        layout.addWidget(self.status)

    def prepare(self):
        if self.closed or not self.install.isEnabled():
            return
        self.install.setEnabled(False)
        self.browser.setEnabled(False)
        self.status.setText('正在准备扩展…')
        self.client.request('POST', '/api/browser',
            {'path': '/api/extension/install', 'body': {'browser': self.browser.currentData()}},
            on_success=self.prepared, on_error=self.failed)

    def prepared(self, response):
        if self.closed:
            return
        self.install.setEnabled(True)
        self.browser.setEnabled(True)
        self.directory.setText(response['directory'])
        self.directory.show()
        self.copy.setEnabled(True)
        self.reveal.setEnabled(True)
        QApplication.clipboard().setText(response['directory'])
        page = response['management_url']
        self.instructions.setText(f'1. 在 {page} 开启“开发者模式”。\n'
            '2. 点击“加载已解压的扩展程序”，选择上方目录。\n'
            '3. 启用扩展，刷新要抓取的网页，再检测连接。\n'
            '更新扩展后请在扩展页重新加载；多个浏览器个人资料需要分别加载。')
        self.status.setText('已打开扩展管理页，目录已复制；请按步骤完成加载。' if response['opened'] else
                            f'未找到所选浏览器，目录已复制；请手动打开 {page} 完成加载。')

    def failed(self, message):
        if self.closed:
            return
        self.install.setEnabled(True)
        self.browser.setEnabled(True)
        self.check.setEnabled(True)
        self.status.setText(message)

    def check_connection(self):
        if self.closed or not self.check.isEnabled():
            return
        self.check.setEnabled(False)
        self.client.request('POST', '/api/browser', {'path': '/api/health'},
                            on_success=self.checked, on_error=self.failed)

    def checked(self, response):
        if self.closed:
            return
        self.check.setEnabled(True)
        count = response.get('bridge', {}).get('extensions', 0)
        self.status.setText(f'检测到 {count} 个扩展连接（所有浏览器合计）；可回到 VS Code 抓取元素。' if count else
                            '尚未检测到扩展连接，请检查扩展是否已启用并刷新网页。')

    def closeEvent(self, event):
        self.closed = True
        super().closeEvent(event)
