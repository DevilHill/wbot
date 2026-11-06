"""Assistant 的原生控件主题、状态文案与应用图标。"""
from datetime import datetime
import math

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetrics, QIcon,
                          QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap)
from PySide6.QtWidgets import QStyle, QStyledItemDelegate


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


def make_symbol_icon(name, color='#007AFF', background='#EAF3FF'):
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
    if name == 'automation':
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
    return QIcon(pixmap)


class CardItemDelegate(QStyledItemDelegate):
    """保留原生列表的选择和键盘操作，只绘制卡片的视觉层级。"""
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(option.rect).adjusted(1, 3, -1, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setBrush(QColor('#F4F9FF' if selected else '#FAFAFC' if hovered else '#FFFFFF'))
        painter.setPen(QPen(QColor('#A4CCFF' if selected else '#E5E5EA'), 1))
        painter.drawRoundedRect(card, 20, 20)
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
        painter.setPen(QColor('#1D1D1F'))
        text_width = max(0, int(card.right() - left - 36))
        title = QFontMetrics(title_font).elidedText(lines[0], Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(QRectF(left, card.center().y() - 22, text_width, 23),
                         Qt.AlignmentFlag.AlignVCenter, title)
        if len(lines) > 1:
            detail_font = QFont(option.font)
            detail_font.setPixelSize(11)
            detail_font.setWeight(QFont.Weight.Normal)
            painter.setFont(detail_font)
            painter.setPen(QColor('#86868B'))
            detail = QFontMetrics(detail_font).elidedText(lines[1], Qt.TextElideMode.ElideRight, text_width)
            painter.drawText(QRectF(left, card.center().y() + 3, text_width, 20),
                             Qt.AlignmentFlag.AlignVCenter, detail)
        painter.setPen(QPen(QColor('#007AFF' if selected else '#C7C7CC'), 1.6,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        arrow = QPainterPath()
        arrow.moveTo(card.right() - 23, card.center().y() - 4)
        arrow.lineTo(card.right() - 19, card.center().y())
        arrow.lineTo(card.right() - 23, card.center().y() + 4)
        painter.drawPath(arrow)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(220, 88)


def apply_theme(application):
    application.setStyle('Fusion')
    families = QFontDatabase.families()
    family = next((name for name in ('Segoe UI Variable Text', 'Segoe UI', 'Microsoft YaHei UI')
                   if name in families), application.font().family())
    application.setFont(QFont(family, 10))
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, '#F5F5F7'), (QPalette.ColorRole.WindowText, '#1D1D1F'),
        (QPalette.ColorRole.Base, '#FFFFFF'), (QPalette.ColorRole.AlternateBase, '#F5F5F7'),
        (QPalette.ColorRole.Text, '#1D1D1F'), (QPalette.ColorRole.Button, '#FFFFFF'),
        (QPalette.ColorRole.ButtonText, '#1D1D1F'), (QPalette.ColorRole.Highlight, '#D7EAFF'),
        (QPalette.ColorRole.HighlightedText, '#004B9D'), (QPalette.ColorRole.PlaceholderText, '#A1A1A6'),
    ):
        palette.setColor(role, QColor(color))
    application.setPalette(palette)
    application.setStyleSheet(STYLESHEET)


STYLESHEET = '''
QMainWindow, QDialog { background: #F5F5F7; }
QWidget { font-size: 13px; }
QLabel { color: #1D1D1F; background: transparent; }
QLabel#brand { font-size: 21px; font-weight: 600; }
QLabel#brandCaption { color: #86868B; font-size: 11px; }
QLabel#pageTitle { font-size: 28px; font-weight: 700; }
QLabel#dialogTitle { font-size: 22px; font-weight: 600; }
QLabel#subtitle { color: #6E6E73; font-size: 12px; }
QLabel#hint { color: #86868B; font-size: 11px; }
QLabel#fieldLabel { color: #515154; font-size: 12px; font-weight: 600; }
QLabel#emptyTitle { color: #1D1D1F; font-size: 16px; font-weight: 600; }
QLabel#footerStatus { color: #6E6E73; font-size: 11px; }
QLabel#connection { border: 1px solid #E5E5EA; border-radius: 16px; padding: 5px 9px; color: #636366; font-size: 10px; background: #FFFFFF; }
QLabel#connection[offline="true"] { color: #A06416; background: #FFF7E8; border-color: #F1E4C9; }
QLabel#message { padding: 11px; border-radius: 16px; background: #EAF3FF; color: #2467A8; font-size: 12px; }
QLabel#message[error="true"] { color: #B64137; background: #FFF0EE; }
QLabel#stateBadge { background: #EAF3FF; color: #007AFF; border-radius: 16px; min-height: 16px; padding: 8px 12px; font-size: 11px; }
QLabel#stateBadge[failed="true"] { background: #FFF0EE; color: #C74337; }
QFrame#emptyState, QFrame#settingsCard { background: #FFFFFF; border: 1px solid #E5E5EA; border-radius: 20px; }
QLabel#transportHint { color: #946520; background: #FFF8E8; border-radius: 16px; padding: 12px; font-size: 11px; }
QLabel#verificationCode { color: #007AFF; background: #F0F6FF; border-radius: 16px; padding: 12px; font-size: 21px; font-weight: 600; }
QFrame#footer { background: transparent; border: none; border-top: 1px solid #E5E5EA; }
QWidget#parameterFields { background: #FFFFFF; border: 1px solid #E5E5EA; border-radius: 20px; }
QLineEdit, QComboBox, QPlainTextEdit { color: #1D1D1F; border: 1px solid #E5E5EA; border-radius: 16px; background: #FFFFFF; padding: 9px 12px; selection-background-color: #CDE4FF; selection-color: #1D1D1F; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: #80B9FF; }
QWidget#parameterFields QLineEdit, QWidget#parameterFields QComboBox { background: #F5F5F7; border-color: #ECECF0; }
QWidget#parameterFields QLineEdit:focus, QWidget#parameterFields QComboBox:focus { background: #FFFFFF; border-color: #80B9FF; }
QLineEdit:disabled, QComboBox:disabled { color: #A1A1A6; background: #F5F5F7; }
QComboBox { min-height: 20px; padding-right: 26px; }
QComboBox::drop-down { width: 26px; border: none; }
QComboBox QAbstractItemView { background: #FFFFFF; border: 1px solid #E5E5EA; selection-background-color: #EAF3FF; selection-color: #1D1D1F; padding: 4px; }
QPushButton { background: #FFFFFF; color: #1D1D1F; border: 1px solid #E5E5EA; border-radius: 16px; padding: 8px 15px; }
QPushButton:hover { border-color: #D1D1D6; background: #FAFAFC; }
QPushButton:pressed { background: #ECECF0; }
QPushButton:disabled { color: #A1A1A6; background: #ECECF0; border-color: #E5E5EA; }
QPushButton#primary { background: #007AFF; color: #FFFFFF; border-color: #007AFF; font-size: 14px; font-weight: 600; padding: 0 16px; }
QPushButton#primary:hover { background: #0872E5; border-color: #0872E5; }
QPushButton#primary:pressed { background: #0063CC; border-color: #0063CC; }
QPushButton#primary:disabled { background: #DCE8F7; border-color: #DCE8F7; color: #91ABCA; }
QPushButton#secondary { color: #007AFF; }
QPushButton#danger { color: #D64A40; background: #FFFFFF; border-color: #F0DAD7; }
QPushButton#iconButton { padding: 0; }
QTabWidget::pane { border: none; padding-top: 14px; }
QTabBar { background: #E9E9EE; border-radius: 19px; }
QTabBar::tab { color: #6E6E73; background: transparent; padding: 8px 13px; margin: 3px; border: 1px solid transparent; border-radius: 16px; font-size: 12px; }
QTabBar::tab:selected { color: #1D1D1F; background: #FFFFFF; border-color: #E2E2E7; font-weight: 600; }
QTabBar::tab:hover:!selected { color: #1D1D1F; background: #E3E3E9; }
QListWidget { background: transparent; border: none; outline: none; padding: 0; }
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
QPlainTextEdit#log { background: #222225; color: #E5E5EA; border: 1px solid #222225; border-radius: 18px; }
QMenu { background: #FFFFFF; border: 1px solid #E5E5EA; padding: 5px; }
QMenu::item { padding: 8px 20px; border-radius: 6px; }
QMenu::item:selected { background: #EAF3FF; color: #007AFF; }
'''
