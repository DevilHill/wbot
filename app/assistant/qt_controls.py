"""Qt-native dropdowns and interruptible segmented navigation."""
from PySide6.QtCore import QEasingCurve, QPoint, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import (QApplication, QComboBox, QGraphicsOpacityEffect,
                               QListView, QStyle, QStyledItemDelegate,
                               QStyleOptionTab, QStyleOptionViewItem, QStylePainter,
                               QTabBar, QTabWidget)

from .qt_theme import color, make_symbol_icon, reduced_motion


class _ComboItemDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.decorationPosition = QStyleOptionViewItem.Position.Right
        option.decorationSize = QSize(18, 18)
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration
        option.icon = (make_symbol_icon('check', '#007AFF', 'transparent')
                       if index.row() == self.parent().currentIndex() else QIcon())

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(38, size.height()))


class ThemedComboBox(QComboBox):
    """Keep Qt's popup, selection model and keyboard handling."""
    def __init__(self, parent=None):
        super().__init__(parent)
        view = QListView()
        view.setObjectName('comboOptions')
        view.setSpacing(2)
        view.setMouseTracking(True)
        view.setTextElideMode(Qt.TextElideMode.ElideRight)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setView(view)
        self.view().window().setObjectName('comboPopup')
        self.setItemDelegate(_ComboItemDelegate(self))
        self.setMaxVisibleItems(8)

    def showPopup(self):
        available = self.screen().availableGeometry()
        popup = self.view().window()
        popup.setFixedWidth(min(self.width(), available.width()))
        super().showPopup()
        below = self.mapToGlobal(QPoint(0, self.height() + 6))
        top = below.y()
        if top + popup.height() > available.bottom():
            top = max(available.top(), self.mapToGlobal(QPoint(0, -6)).y() - popup.height())
        left = max(available.left(), min(below.x(), available.right() - popup.width() + 1))
        popup.move(left, top)
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(popup.rect()), 12, 12)
        popup.setMask(QRegion(outline.toFillPolygon().toPolygon()))
        self.update()

    def hidePopup(self):
        super().hidePopup()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        role = 'brand' if self.view().isVisible() else 'muted'
        painter.setPen(QPen(QColor(color(role if self.isEnabled() else 'disabled')), 1.6,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        direction = -1 if self.view().isVisible() else 1
        center = self.height() / 2
        arrow = QPainterPath()
        arrow.moveTo(self.width() - 25, center - 2 * direction)
        arrow.lineTo(self.width() - 21, center + 2 * direction)
        arrow.lineTo(self.width() - 17, center - 2 * direction)
        painter.drawPath(arrow)


class _SlidingTabBar(QTabBar):
    """Paint only the moving pill; Qt still owns tab labels and navigation."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._indicator = QRectF()
        self._motion = QVariantAnimation(self)
        self._motion.setDuration(200)
        self._motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._motion.valueChanged.connect(self._move_indicator)
        self.currentChanged.connect(self._select_tab)

    def _target_rect(self):
        return QRectF(self.tabRect(self.currentIndex())).adjusted(3, 3, -3, -3)

    def _move_indicator(self, rect):
        self._indicator = rect
        self.update()

    def _select_tab(self, index):
        self._motion.stop()
        if not self.isVisible() or self._indicator.isEmpty() or reduced_motion(QApplication.instance()):
            self.finish_motion()
            return
        self._motion.setStartValue(self._indicator)
        self._motion.setEndValue(self._target_rect())
        self._motion.start()

    def finish_motion(self):
        self._motion.stop()
        self._move_indicator(self._target_rect())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.finish_motion()

    def hideEvent(self, event):
        self.finish_motion()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QStylePainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color('hover')))
        painter.drawRoundedRect(QRectF(self.rect()), 19, 19)
        painter.setPen(QPen(QColor(color('border')), 1))
        painter.setBrush(QColor(color('surface')))
        painter.drawRoundedRect(self._indicator, 16, 16)
        for index in range(self.count()):
            option = QStyleOptionTab()
            self.initStyleOption(option, index)
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabLabel, option)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(color('focus')), 2))
            painter.drawRoundedRect(self._target_rect().adjusted(2, 2, -2, -2), 13, 13)


class AnimatedTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(_SlidingTabBar(self))
        self._fading_page = None
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(180)
        self._fade.setStartValue(0.35)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(self._set_opacity)
        self._fade.finished.connect(self._finish_fade)
        self.currentChanged.connect(self._animate_page)

    def _set_opacity(self, opacity):
        if self._fading_page is not None:
            self._fading_page.graphicsEffect().setOpacity(opacity)

    def _finish_fade(self):
        self._fade.stop()
        if self._fading_page is not None:
            self._fading_page.setGraphicsEffect(None)
            self._fading_page = None

    def _animate_page(self, index):
        self._finish_fade()
        if index < 0 or not self.isVisible() or reduced_motion(QApplication.instance()):
            return
        self._fading_page = self.widget(index)
        effect = QGraphicsOpacityEffect(self._fading_page)
        effect.setOpacity(0.35)
        self._fading_page.setGraphicsEffect(effect)
        self._fade.start()

    def hideEvent(self, event):
        self._finish_fade()
        super().hideEvent(event)

    def resizeEvent(self, event):
        self._finish_fade()
        super().resizeEvent(event)
