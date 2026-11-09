"""Assistant 的原生控件主题、状态文案与应用图标。"""
from datetime import datetime
from pathlib import Path
import math

from PySide6.QtCore import Qt, QRectF, QSize, QSettings, QTimer
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetrics, QIcon, QIconEngine,
                          QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate


ACTIVE_STATES = {'preparing', 'running', 'stopping'}
STATE_LABELS = {'preparing': '准备环境', 'running': '运行中', 'stopping': '停止中',
                'succeeded': '已完成', 'failed': '失败', 'stopped': '已停止',
                'interrupted': '中断待核实'}


def display_time(timestamp):
    return datetime.fromtimestamp(timestamp).strftime('%m/%d %H:%M:%S') if timestamp else '—'


def make_app_icon():
    pixmap = QPixmap(256, 256)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    gradient = QLinearGradient(20, 4, 110, 128)
    gradient.setColorAt(0, QColor('#59B5FF'))
    gradient.setColorAt(0.5, QColor('#1684FF'))
    gradient.setColorAt(1, QColor('#0064DA'))
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(4, 4, 120, 120), 30, 30)
    painter.setPen(QPen(QColor('#FFFFFF'), 9, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(31, 42)
    for x, y in ((43, 86), (64, 55), (85, 86), (97, 42)):
        path.lineTo(x, y)
    painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


def _symbol_pixmap(name, color='#007AFF', background='#EAF3FF'):
    """用同一线宽绘制列表与按钮图标，避免依赖平台字体里的符号。"""
    pixmap = QPixmap(96, 96)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(background))
    painter.drawRoundedRect(QRectF(0, 0, 48, 48), 16, 16)
    if QColor(background).alpha() == 0:
        painter.translate(24, 24)
        painter.scale(1.5, 1.5)
        painter.translate(-24, -24)
    painter.setPen(QPen(QColor(color), 2.1, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    if name == 'back':
        path.moveTo(28, 16)
        path.lineTo(20, 24)
        path.lineTo(28, 32)
    elif name == 'minimize':
        path.moveTo(17, 24)
        path.lineTo(31, 24)
    elif name in ('maximize', 'restore'):
        painter.drawRect(QRectF(17, 17, 14, 14))
        if name == 'restore':
            path.moveTo(21, 17)
            path.lineTo(21, 13)
            path.lineTo(35, 13)
            path.lineTo(35, 27)
            path.lineTo(31, 27)
    elif name == 'close':
        path.moveTo(17, 17)
        path.lineTo(31, 31)
        path.moveTo(31, 17)
        path.lineTo(17, 31)
    elif name == 'automation':
        painter.drawRoundedRect(QRectF(12, 12, 24, 24), 6, 6)
        path.moveTo(21, 18)
        path.lineTo(29, 24)
        path.lineTo(21, 30)
        path.closeSubpath()
    elif name == 'history':
        painter.drawEllipse(QRectF(13, 13, 22, 22))
        path.moveTo(24, 17)
        path.lineTo(24, 24)
        path.lineTo(29, 27)
    elif name == 'play':
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        path.moveTo(19, 15)
        path.lineTo(33, 24)
        path.lineTo(19, 33)
        path.closeSubpath()
    elif name == 'import':
        path.moveTo(24, 12)
        path.lineTo(24, 28)
        path.moveTo(18, 22)
        path.lineTo(24, 28)
        path.lineTo(30, 22)
        path.moveTo(14, 29)
        path.lineTo(14, 35)
        path.lineTo(34, 35)
        path.lineTo(34, 29)
    elif name == 'search':
        painter.drawEllipse(QRectF(13, 13, 18, 18))
        path.moveTo(29, 29)
        path.lineTo(36, 36)
    elif name == 'refresh':
        painter.drawArc(QRectF(13, 13, 22, 22), 35 * 16, 290 * 16)
        path.moveTo(29, 14)
        path.lineTo(35, 15)
        path.lineTo(35, 9)
    elif name == 'chevron':
        path.moveTo(21, 17)
        path.lineTo(28, 24)
        path.lineTo(21, 31)
    elif name == 'check':
        path.moveTo(14, 24)
        path.lineTo(21, 31)
        path.lineTo(34, 17)
    elif name == 'error':
        painter.drawEllipse(QRectF(13, 13, 22, 22))
        path.moveTo(24, 18)
        path.lineTo(24, 25)
        path.moveTo(24, 29)
        path.lineTo(24, 29.5)
    elif name == 'stop':
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(16, 16, 16, 16), 3, 3)
    elif name == 'settings':
        for index in range(32):
            angle = -math.pi / 2 + index * math.tau / 32
            radius = 14 if index % 4 in (1, 2) else 11
            x, y = 24 + radius * math.cos(angle), 24 + radius * math.sin(angle)
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        painter.drawEllipse(QRectF(19, 19, 10, 10))
    else:
        painter.end()
        raise ValueError(f'未定义的 Assistant 图标：{name}')
    painter.drawPath(path)
    painter.end()
    return pixmap


class SymbolIconEngine(QIconEngine):
    def __init__(self, name, foreground, background):
        super().__init__()
        self.name, self.foreground, self.background = name, foreground, background

    def clone(self):
        return SymbolIconEngine(self.name, self.foreground, self.background)

    def pixmap(self, size, mode, state):
        foreground = self.foreground
        if self.background == 'transparent':
            foreground = color('on_brand' if foreground == '#FFFFFF' else 'brand' if foreground == '#007AFF' else 'muted')
        return _symbol_pixmap(self.name, foreground, self.background).scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    def paint(self, painter, rect, mode, state):
        painter.drawPixmap(rect, self.pixmap(rect.size(), mode, state))


def make_symbol_icon(name, color='#007AFF', background='#EAF3FF'):
    return QIcon(SymbolIconEngine(name, color, background))


class CardItemDelegate(QStyledItemDelegate):
    """保留原生列表的选择和键盘操作，只绘制卡片的视觉层级。"""
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(option.rect).adjusted(1, 3, -1, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setBrush(QColor(color('selected' if selected else 'hover' if hovered else 'surface')))
        painter.setPen(QPen(QColor(color('focus' if option.state & QStyle.StateFlag.State_HasFocus else 'brand' if selected else 'border')), 1))
        painter.drawRoundedRect(card, 20, 20)
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(color('focus')), 2, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(card.adjusted(3, 3, -3, -3), 17, 17)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        left = card.left() + 16
        if isinstance(icon, QIcon) and not icon.isNull():
            icon.paint(painter, int(left), int(card.center().y() - 21), 42, 42)
            left += 56
        lines = str(index.data(Qt.ItemDataRole.DisplayRole) or '').split('\n', 1)
        title_font = QFont(option.font)
        title_font.setPixelSize(14)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(color('text')))
        text_width = max(0, int(card.right() - left - 36))
        title = QFontMetrics(title_font).elidedText(lines[0], Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(QRectF(left, card.center().y() - 22, text_width, 23),
                         Qt.AlignmentFlag.AlignVCenter, title)
        if len(lines) > 1:
            detail_font = QFont(option.font)
            detail_font.setPixelSize(12)
            detail_font.setWeight(QFont.Weight.Normal)
            painter.setFont(detail_font)
            painter.setPen(QColor(color('muted')))
            detail = QFontMetrics(detail_font).elidedText(lines[1], Qt.TextElideMode.ElideRight, text_width)
            painter.drawText(QRectF(left, card.center().y() + 3, text_width, 20),
                             Qt.AlignmentFlag.AlignVCenter, detail)
        painter.setPen(QPen(QColor(color('brand' if selected else 'muted')), 1.6,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        arrow = QPainterPath()
        arrow.moveTo(card.right() - 23, card.center().y() - 4)
        arrow.lineTo(card.right() - 19, card.center().y())
        arrow.lineTo(card.right() - 23, card.center().y() + 4)
        painter.drawPath(arrow)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(220, 88)


LIGHT = dict(background='#F5F5F7', surface='#FFFFFF', text='#1D1D1F', muted='#60616A', border='#D2D3DA', hover='#ECEEF3', selected='#E6F0FF', brand='#0064D9', brand_hover='#0056BC', on_brand='#FFFFFF', focus='#0056BC', disabled='#737681', disabled_surface='#E4E6EC', danger='#B52A25', danger_surface='#FFF0EE', warning='#79520D', warning_surface='#FFF7E8', log='#222225', log_text='#F1F2F6')
DARK = dict(background='#15161A', surface='#202126', text='#F1F2F6', muted='#B6B9C4', border='#565A67', hover='#30333C', selected='#243F60', brand='#91C5FF', brand_hover='#B8DAFF', on_brand='#10243B', focus='#91C5FF', disabled='#9A9EAA', disabled_surface='#30323A', danger='#FFAAA5', danger_surface='#492927', warning='#F3CE8C', warning_surface='#40351F', log='#111216', log_text='#F1F2F6')


def color(role):
    return getattr(QApplication.instance(), '_wbot_colors', LIGHT)[role]


def theme_mode(application):
    return getattr(application, '_wbot_theme_mode', 'system')


def reduced_motion(application):
    return getattr(application, '_wbot_reduced_motion', False)


def set_reduced_motion(application, enabled):
    application._wbot_reduced_motion = bool(enabled)
    settings = getattr(application, '_wbot_theme_settings', None)
    if settings is not None:
        settings.setValue('appearance/reduced_motion', bool(enabled))
        settings.sync()


def set_theme_mode(application, mode):
    if mode not in ('light', 'dark', 'system', 'contrast'):
        raise ValueError('未知外观模式')
    application._wbot_theme_mode = mode
    settings = getattr(application, '_wbot_theme_settings', None)
    if settings is not None:
        settings.setValue('appearance/mode', mode)
        settings.sync()
    _render_theme(application)


def _render_theme(application):
    mode = theme_mode(application)
    dark = mode == 'dark' or (mode == 'system' and application.styleHints().colorScheme() == Qt.ColorScheme.Dark)
    colors = dict(DARK if dark else LIGHT)
    high_contrast = mode == 'contrast' or (mode == 'system' and application._wbot_accessibility.contrastPreference() == Qt.ContrastPreference.HighContrast)
    if high_contrast:
        colors.update(background='#000000', surface='#000000', text='#FFFFFF', muted='#FFFFFF', border='#FFFFFF', hover='#252525', selected='#103D65', brand='#FFFF00', brand_hover='#FFFFFF', on_brand='#000000', focus='#FFFFFF', disabled='#BDBDBD', disabled_surface='#252525')
    application._wbot_colors = colors
    palette = QPalette()
    roles = dict(Window='background', WindowText='text', Base='surface', AlternateBase='hover', Text='text', Button='surface', ButtonText='text', Highlight='selected', HighlightedText='text', PlaceholderText='muted', ToolTipBase='surface', ToolTipText='text', Link='brand')
    for name, role in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, name), QColor(colors[role]))
    for name in ('Text', 'ButtonText', 'WindowText'):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, name), QColor(colors['disabled']))
    application.setPalette(palette)
    stylesheet = STYLESHEET
    for role, value in colors.items():
        stylesheet = stylesheet.replace('@' + role + '@', value)
    application.setStyleSheet(stylesheet)
    for widget in application.allWidgets():
        widget.update()


def apply_theme(application, state_dir=None):
    if not hasattr(application, '_wbot_accessibility'):
        application._wbot_style_hints = application.styleHints()
        application._wbot_accessibility = application._wbot_style_hints.accessibility()
    application.setStyle('Fusion')
    families = QFontDatabase.families()
    family = next((name for name in ('Segoe UI Variable Text', 'Segoe UI', 'Microsoft YaHei UI') if name in families), application.font().family())
    application.setFont(QFont(family, 10))
    if state_dir is not None:
        application._wbot_theme_settings = QSettings(str(Path(state_dir).resolve() / 'appearance.ini'), QSettings.Format.IniFormat)
        mode = application._wbot_theme_settings.value('appearance/mode', 'system')
        application._wbot_theme_mode = mode if mode in ('light', 'dark', 'system', 'contrast') else 'system'
        application._wbot_reduced_motion = application._wbot_theme_settings.value('appearance/reduced_motion', False, type=bool)
    if not getattr(application, '_wbot_theme_connected', False):
        application.styleHints().colorSchemeChanged.connect(lambda _: QTimer.singleShot(0, lambda: _render_theme(application)))
        application._wbot_accessibility.contrastPreferenceChanged.connect(lambda _: QTimer.singleShot(0, lambda: _render_theme(application)))
        application._wbot_theme_connected = True
    _render_theme(application)


STYLESHEET = '''
QMainWindow, QDialog { background: @background@; }
QWidget { font-size: 13px; }
QLabel { color: @text@; background: transparent; }
QLabel#brand { font-size: 21px; font-weight: 600; }
QLabel#brandCaption { color: @muted@; font-size: 12px; }
QLabel#pageTitle { font-size: 28px; font-weight: 700; }
QLabel#dialogTitle { font-size: 22px; font-weight: 600; }
QLabel#subtitle { color: @muted@; font-size: 12px; }
QLabel#hint { color: @muted@; font-size: 12px; }
QLabel#fieldLabel { color: @muted@; font-size: 12px; font-weight: 600; }
QLabel#emptyTitle { color: @text@; font-size: 16px; font-weight: 600; }
QLabel#footerStatus { color: @muted@; font-size: 12px; }
QLabel#connection { border: 1px solid @border@; border-radius: 16px; padding: 5px 9px; color: @muted@; font-size: 10px; background: @surface@; }
QLabel#connection[offline="true"] { color: @warning@; background: @warning_surface@; border-color: @warning_surface@; }
QLabel#message { padding: 11px; border-radius: 16px; background: @selected@; color: @brand@; font-size: 12px; }
QLabel#message[error="true"] { color: @danger@; background: @danger_surface@; }
QLabel#stateBadge { background: @selected@; color: @brand@; border-radius: 16px; min-height: 16px; padding: 8px 12px; font-size: 12px; }
QLabel#stateBadge[failed="true"] { background: @danger_surface@; color: @danger@; }
QFrame#emptyState, QFrame#settingsCard { background: @surface@; border: 1px solid @border@; border-radius: 20px; }
QLabel#transportHint { color: @warning@; background: @warning_surface@; border-radius: 16px; padding: 12px; font-size: 12px; }
QLabel#verificationCode { color: @brand@; background: @selected@; border-radius: 16px; padding: 12px; font-size: 21px; font-weight: 600; }
QFrame#footer { background: transparent; border: none; border-top: 1px solid @border@; }
QWidget#parameterFields { background: @surface@; border: 1px solid @border@; border-radius: 20px; }
QLineEdit, QComboBox, QPlainTextEdit { color: @text@; border: 1px solid @border@; border-radius: 16px; background: @surface@; padding: 9px 12px; selection-background-color: @selected@; selection-color: @text@; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: @focus@; }
QWidget#parameterFields QLineEdit, QWidget#parameterFields QComboBox { background: @background@; border-color: @disabled_surface@; }
QWidget#parameterFields QLineEdit:focus, QWidget#parameterFields QComboBox:focus { background: @surface@; border-color: @focus@; }
QLineEdit:disabled, QComboBox:disabled { color: @disabled@; background: @background@; }
QComboBox { min-height: 22px; padding-right: 34px; border-radius: 12px; }
QComboBox:hover:enabled { background: @hover@; border-color: @muted@; }
QComboBox:on, QComboBox:focus { background: @surface@; border: 2px solid @focus@; }
QComboBox::drop-down { width: 26px; border: none; }
QComboBox::down-arrow { image: none; }
QFrame#comboPopup { background: @surface@; border: 1px solid @border@; border-radius: 12px; }
QComboBox QAbstractItemView { color: @text@; background: @surface@; border: 1px solid @border@; border-radius: 12px; selection-background-color: @selected@; selection-color: @text@; padding: 6px; outline: 0; }
QListView#comboOptions::item { padding: 7px 10px; border: 1px solid transparent; border-radius: 8px; }
QListView#comboOptions::item:hover, QListView#comboOptions::item:selected { color: @brand@; background: @selected@; }
QListView#comboOptions::item:focus { border-color: @focus@; }
QListView#comboOptions::item:disabled { color: @disabled@; background: transparent; }
QCheckBox { color: @text@; spacing: 8px; padding: 4px 0; }
QCheckBox:focus { color: @brand@; }
QProgressBar { color: @text@; background: @hover@; border: none; border-radius: 6px; min-height: 12px; text-align: center; }
QProgressBar::chunk { background: @brand@; border-radius: 6px; }
QPushButton { background: @surface@; color: @text@; border: 1px solid @border@; border-radius: 16px; padding: 8px 15px; }
QPushButton:hover { border-color: @border@; background: @hover@; }
QPushButton:pressed { background: @disabled_surface@; }
QPushButton:disabled { color: @disabled@; background: @disabled_surface@; border-color: @border@; }
QPushButton#primary { background: @brand@; color: @on_brand@; border-color: @brand@; font-size: 14px; font-weight: 600; padding: 0 16px; }
QPushButton#primary:hover { background: @brand_hover@; border-color: @brand_hover@; }
QPushButton#primary:pressed { background: @brand_hover@; border-color: @brand_hover@; }
QPushButton#primary:disabled { background: @disabled_surface@; border-color: @disabled_surface@; color: @disabled@; }
QPushButton#secondary { color: @brand@; }
QPushButton#danger { color: @danger@; background: @surface@; border-color: @danger_surface@; }
QPushButton#iconButton { padding: 0; }
QTabWidget::pane { border: none; padding-top: 14px; }
QTabBar { background: @hover@; border-radius: 19px; }
QTabBar::tab { color: @muted@; background: transparent; padding: 8px 13px; margin: 3px; border: 1px solid transparent; border-radius: 16px; font-size: 12px; }
QTabBar::tab:selected { color: @text@; background: @surface@; border-color: @border@; font-weight: 600; }
QTabBar::tab:hover:!selected { color: @text@; background: @hover@; }
QListWidget { background: transparent; border: none;  padding: 0; }
QListWidget::item { background: transparent; border: none; padding: 0; }
QListWidget::item:selected { background: transparent; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget { background: transparent; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 2px 0; }
QScrollBar::handle:vertical { background: #CCCCD2; border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: #AEAEB4; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QPlainTextEdit { font-family: Consolas; font-size: 12px; padding: 14px; }
QPlainTextEdit#log { background: @log@; color: @log_text@; border: 1px solid @log@; border-radius: 18px; }
QMenu { background: @surface@; border: 1px solid @border@; padding: 5px; }
QMenu::item { padding: 8px 20px; border-radius: 6px; }
QMenu::item:selected { background: @selected@; color: @brand@; }
QPushButton:focus, QPushButton#primary:focus, QPushButton#secondary:focus, QPushButton#danger:focus, QTabBar::tab:focus { border: 2px solid @focus@; }
QWidget#parameterFields QLineEdit[invalid="true"], QWidget#parameterFields QComboBox[invalid="true"], QLineEdit[invalid="true"], QComboBox[invalid="true"] { border: 2px solid @danger@; }
QLabel#fieldError { color: @danger@; font-size: 12px; }
QPushButton#ocConnection { text-align: left; color: @muted@; padding: 8px 12px; }
QPushButton#ocConnection[offline="true"] { color: @warning@; background: @warning_surface@; }
QToolTip { color: @text@; background: @surface@; border: 1px solid @border@; }
QFrame#titleBar { background: @background@; border: none; }
QLabel#captionTitle { color: @text@; font-size: 12px; }
QFrame#titleBar[windowActive="false"] QLabel#captionTitle { color: @muted@; }
QToolButton#captionButton, QToolButton#captionClose { background: transparent; color: @text@; border: 2px solid transparent; border-radius: 0; padding: 0; }
QToolButton#captionButton:hover, QToolButton#captionButton[nativeHover="true"] { background: @hover@; }
QToolButton#captionButton:pressed { background: @selected@; }
QToolButton#captionClose:hover, QToolButton#captionClose:pressed { background: @danger_surface@; }
QToolButton#captionButton:focus, QToolButton#captionClose:focus { border-color: @focus@; }
'''
