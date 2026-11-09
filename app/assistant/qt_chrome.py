"""Integrated Qt caption; window movement and resizing remain OS operations."""
import ctypes
import os
import sys

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget

from .qt_theme import color, make_symbol_icon
from .qt_windows_title import WindowsSnapLayoutAdapter, WindowsSnapLayoutWindowMixin


class CaptionWindowMixin(WindowsSnapLayoutWindowMixin):
    def paintEvent(self, event):
        super().paintEvent(event)
        if not getattr(self, 'title_bar', None) or self.isMaximized() or self.isFullScreen():
            return
        painter = QPainter(self)
        painter.setPen(QPen(QColor(color('border' if self.isActiveWindow() else 'muted')), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class ResizeHandle(QWidget):
    def __init__(self, window, edges, cursor):
        super().__init__(window)
        self.edges = edges
        self.setCursor(cursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle and handle.startSystemResize(self.edges):
                event.accept()
                return
        super().mousePressEvent(event)


class TitleBar(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.setObjectName('titleBar')
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(0)
        self.title = QLabel(window.windowTitle())
        self.title.setObjectName('captionTitle')
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.title, 1)
        self.minimize_button = self._button('最小化', 'minimize', window.showMinimized)
        self.maximize_button = self._button('最大化', 'maximize', self.toggle_maximize)
        self.close_button = self._button('关闭窗口', 'close', window.close)
        self.close_button.setObjectName('captionClose')
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            layout.addWidget(button)
        top, bottom, left, right = Qt.Edge.TopEdge, Qt.Edge.BottomEdge, Qt.Edge.LeftEdge, Qt.Edge.RightEdge
        self.resize_handles = [ResizeHandle(window, edge, cursor) for edge, cursor in (
            (top | left, Qt.CursorShape.SizeFDiagCursor), (top, Qt.CursorShape.SizeVerCursor),
            (top | right, Qt.CursorShape.SizeBDiagCursor), (left, Qt.CursorShape.SizeHorCursor),
            (right, Qt.CursorShape.SizeHorCursor), (bottom | left, Qt.CursorShape.SizeBDiagCursor),
            (bottom, Qt.CursorShape.SizeVerCursor), (bottom | right, Qt.CursorShape.SizeFDiagCursor))]
        self.system_menu = QMenu(window)
        self.restore_action = self.system_menu.addAction('还原(&R)', window.showNormal)
        self.system_menu.addAction('移动(&M)', lambda: self._system_command(0xF010))
        self.system_menu.addAction('调整大小(&S)', lambda: self._system_command(0xF000))
        self.system_menu.addAction('最小化(&N)', window.showMinimized)
        self.maximize_action = self.system_menu.addAction('最大化(&X)', window.showMaximized)
        self.system_menu.addSeparator()
        self.system_menu.addAction('关闭(&C)', window.close)
        self.system_menu.aboutToShow.connect(self._menu_state)
        self.menu_shortcut = QShortcut(QKeySequence('Alt+Space'), window)
        self.menu_shortcut.activated.connect(lambda: self.system_menu.popup(self.mapToGlobal(QPoint(0, self.height()))))
        window.installEventFilter(self)
        window.windowTitleChanged.connect(self._title_changed)
        self._sync()

    def _button(self, title, symbol, callback):
        button = QToolButton(self)
        button.setObjectName('captionButton')
        button.setFixedSize(44, 38)
        button.setAccessibleName(title)
        button.setToolTip(title)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setIcon(make_symbol_icon(symbol, '#6E6E73', 'transparent'))
        button.clicked.connect(callback)
        return button

    def _menu_state(self):
        self.restore_action.setEnabled(self.owner.isMaximized() or self.owner.isMinimized())
        self.maximize_action.setEnabled(not self.owner.isMaximized())

    def _system_command(self, command):
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            ctypes.windll.user32.PostMessageW(ctypes.c_void_p(int(self.owner.winId())), 0x112, command, 0)

    def toggle_maximize(self):
        if self.owner.isMaximized():
            self.owner.showNormal()
        else:
            self.owner.showMaximized()
        self._sync()

    def _title_changed(self, text):
        self.title.setToolTip(text)
        self.title.setText(self.title.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(0, self.width() - 156)))

    def _sync(self):
        maximized = self.owner.isMaximized() or self.owner.isFullScreen()
        self.owner.setContentsMargins(*(0 if maximized else 1 for _ in range(4)))
        self.maximize_button.setAccessibleName('还原' if maximized else '最大化')
        self.maximize_button.setToolTip(self.maximize_button.accessibleName())
        self.maximize_button.setIcon(make_symbol_icon('restore' if maximized else 'maximize', '#6E6E73', 'transparent'))
        self.setProperty('windowActive', self.owner.isActiveWindow())
        self.style().unpolish(self)
        self.style().polish(self)
        width, height, edge, corner = self.owner.width(), self.owner.height(), 5, 10
        rectangles = [(0,0,corner,corner), (corner,0,width-2*corner,edge), (width-corner,0,corner,corner),
                      (0,corner,edge,height-2*corner), (width-edge,corner,edge,height-2*corner),
                      (0,height-corner,corner,corner), (corner,height-edge,width-2*corner,edge),
                      (width-corner,height-corner,corner,corner)]
        for handle, rect in zip(self.resize_handles, rectangles):
            handle.setGeometry(*rect)
            handle.setVisible(not maximized and self.owner.isVisible())
            handle.raise_()
        self.owner.update()

    def eventFilter(self, watched, event):
        if watched is self.owner and event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.WindowStateChange,
                                                      QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate):
            self._sync()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._title_changed(self.owner.windowTitle())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.owner.windowHandle():
            if self.owner.windowHandle().startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        self.system_menu.popup(event.globalPos())


def install_title_bar(window):
    window.title_bar = None
    if os.environ.get('WBOT_NATIVE_TITLE_BAR') == '1':
        return
    window.setWindowFlags(window.windowFlags() | Qt.WindowType.FramelessWindowHint |
                          Qt.WindowType.WindowMinMaxButtonsHint)
    title = TitleBar(window)
    window.title_bar = title
    if hasattr(window, 'centralWidget'):
        content = window.takeCentralWidget()
        shell = QWidget(window)
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(title)
        layout.addWidget(content, 1)
        window.setCentralWidget(shell)
    else:
        window.layout().setMenuBar(title)
    if sys.platform == 'win32' and QApplication.platformName() == 'windows':
        window.windows_snap_layout_adapter = WindowsSnapLayoutAdapter(window, title.maximize_button)
        window.destroyed.connect(window.windows_snap_layout_adapter.dispose)
        # Windows 11 draws the outer rounded corners without a translucent client surface.
        preference = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(int(window.winId())), 33,
                                                ctypes.byref(preference), ctypes.sizeof(preference))
