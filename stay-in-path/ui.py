"""Visual language and animated widgets for Stay in Path.

Everything here is dependency-free apart from Qt: the goal is a calm, dark,
"control room" look with restrained motion rather than decoration for its own sake.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from PySide6.QtCore import (
    Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize,
    Qt, QTimer, QVariantAnimation,
)
from PySide6.QtGui import (
    QBrush, QColor, QConicalGradient, QFont, QFontMetrics, QLinearGradient,
    QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QToolTip, QVBoxLayout, QWidget,
)

# --------------------------------------------------------------------- palette
BG = '#05090d'
CARD = '#0b151d'
CARD_HI = '#0e1e27'
BORDER = '#162b34'
MINT = '#65e6a0'
MINT_SOFT = '#3fbf85'
CYAN = '#56d4ff'
VIOLET = '#8f7bff'
TEXT = '#e9f7f2'
MUTED = '#7d95a1'
FAINT = '#4d6371'
DANGER = '#ff7b8a'
EMPTY_CELL = '#101f27'
HEAT = ['#10242c', '#1b5546', '#2c8a5f', '#48c78c', '#8dffc8']

DAY_COLORS = HEAT  # kept for backwards compatibility with older code

STYLESHEET = f"""
QWidget {{ background: transparent; color: {TEXT}; font: 10.5pt 'Segoe UI'; }}
QMainWindow {{ background: {BG}; }}
QFrame#sidebar {{ background: rgba(6,12,17,0.82); border-right: 1px solid rgba(101,230,160,0.14); }}
QPushButton {{
    padding: 9px 14px; background: rgba(22,40,50,0.85);
    border: 1px solid rgba(92,140,150,0.28); border-radius: 10px;
    font-weight: 600; color: {TEXT};
}}
QPushButton:hover {{ background: rgba(34,64,68,0.92); border-color: rgba(101,230,160,0.45); }}
QPushButton:pressed {{ background: rgba(14,28,34,0.95); }}
QPushButton[primary="true"] {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {MINT}, stop:1 {CYAN});
    color: #04211a; border: 1px solid rgba(160,255,214,0.65);
}}
QPushButton[primary="true"]:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #8bf3bd, stop:1 #8ce6ff);
}}
QPushButton:disabled {{
    color: #5d7480; background: rgba(16,28,34,0.75);
    border-color: rgba(70,100,110,0.25);
}}
QPushButton[primary="true"]:disabled {{
    background: rgba(38,71,65,0.55); color: #7ba294;
    border-color: rgba(101,230,160,0.22);
}}
QLineEdit, QSpinBox, QComboBox {{
    background: rgba(8,17,23,0.94); border: 1px solid rgba(92,140,150,0.32);
    border-radius: 9px; padding: 8px; min-height: 20px;
    selection-background-color: {MINT_SOFT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {MINT}; }}
QComboBox QAbstractItemView {{
    background: #0a131a; border: 1px solid rgba(101,230,160,0.28);
    selection-background-color: rgba(101,230,160,0.18);
}}
QToolTip {{
    background: #0a131a; color: {TEXT}; border: 1px solid rgba(101,230,160,0.32);
    padding: 6px 8px; border-radius: 6px;
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: rgba(101,230,160,0.22); border-radius: 5px; min-height: 44px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(101,230,160,0.42); }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QMenu {{ background: #0a131a; border: 1px solid rgba(101,230,160,0.18); padding: 6px; }}
QMenu::item {{ padding: 8px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: rgba(101,230,160,0.16); }}
QDialog, QMessageBox {{ background: {BG}; }}
QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{
    width: 19px; height: 19px; border-radius: 6px;
    border: 1px solid rgba(92,140,150,0.5); background: rgba(8,17,23,0.9);
}}
QCheckBox::indicator:checked {{ background: {MINT}; border-color: {MINT}; }}
QCheckBox::indicator:hover {{ border-color: {MINT}; }}
"""


# --------------------------------------------------------------------- helpers
def qc(value, alpha: int | None = None) -> QColor:
    color = QColor(value)
    if alpha is not None:
        color.setAlpha(max(0, min(255, alpha)))
    return color


def mix(a, b, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    ca, cb = QColor(a), QColor(b)
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue() + (cb.blue() - ca.blue()) * t),
    )


def heat_color(value: float | None) -> QColor:
    if value is None:
        return qc(EMPTY_CELL)
    if value <= 0:
        return qc(HEAT[0])
    return qc(HEAT[min(4, max(1, int(value * 4 + 0.999)))])


def display_font(size: int, weight: int = 600, spacing: float = 0.0) -> QFont:
    font = QFont('Segoe UI Variable Display')
    if not font.exactMatch():
        font = QFont('Segoe UI')
    font.setPixelSize(size)
    font.setWeight(QFont.Weight(weight))
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


class HoverMixin:
    """Shared hover animation setup (the Qt property lives on each widget class)."""

    def _init_hover(self):
        self._hover = 0.0
        self._hover_anim = QPropertyAnimation(self, b'hover', self)
        self._hover_anim.setDuration(190)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _animate_hover(self, target: float):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def enterEvent(self, event):
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        super().leaveEvent(event)


# --------------------------------------------------------------------- surface
class Aurora(QWidget):
    """Slow-drifting neon light behind the whole app. Pauses when hidden."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(55)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._phase += 0.035
        self.update()

    def showEvent(self, event):
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        painter.fillRect(rect, qc(BG))
        w, h = rect.width(), rect.height()
        t = self._phase
        blobs = (
            (w * 0.16 + 70 * math.sin(t), h * 0.18 + 45 * math.cos(t * 0.8), max(w, h) * 0.55, MINT, 34),
            (w * 0.82 + 80 * math.cos(t * 0.7), h * 0.10 + 55 * math.sin(t * 1.1), max(w, h) * 0.50, CYAN, 26),
            (w * 0.62 + 90 * math.sin(t * 0.45), h * 0.92 + 40 * math.cos(t * 0.9), max(w, h) * 0.52, VIOLET, 18),
        )
        for cx, cy, radius, color, alpha in blobs:
            gradient = QRadialGradient(QPointF(cx, cy), radius)
            gradient.setColorAt(0.0, qc(color, alpha))
            gradient.setColorAt(0.55, qc(color, alpha // 4))
            gradient.setColorAt(1.0, qc(color, 0))
            painter.fillRect(rect, gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qc(CYAN, 11))
        step = 36
        for x in range(0, int(w), step):
            for y in range(0, int(h), step):
                painter.drawEllipse(QPointF(x, y), 1.0, 1.0)


class GlowCard(HoverMixin, QFrame):
    """Rounded glass card with a hover-reactive neon edge."""

    def __init__(self, parent=None, radius: int = 20, accent: str = MINT):
        super().__init__(parent)
        self.radius = radius
        self.accent = accent
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._init_hover()

    @Property(float)
    def hover(self) -> float:
        return self._hover

    @hover.setter
    def hover(self, value: float):
        self._hover = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2)
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        body = QLinearGradient(rect.topLeft(), rect.bottomRight())
        body.setColorAt(0.0, qc(CARD_HI, 236))
        body.setColorAt(1.0, qc(CARD, 242))
        painter.fillPath(path, QBrush(body))
        sheen = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + 90))
        sheen.setColorAt(0.0, qc('#ffffff', int(9 + 12 * self._hover)))
        sheen.setColorAt(1.0, qc('#ffffff', 0))
        painter.fillPath(path, QBrush(sheen))
        edge = mix(BORDER, self.accent, self._hover * 0.7)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(qc(edge, 190 + int(60 * self._hover)), 1.1))
        painter.drawRoundedRect(rect, self.radius, self.radius)
        # futuristic corner ticks, brighter on hover
        alpha = int(60 + 150 * self._hover)
        painter.setPen(QPen(qc(self.accent, alpha), 1.6))
        tick = 14
        for x, y, dx, dy in ((rect.left(), rect.top(), 1, 1),
                             (rect.right(), rect.top(), -1, 1),
                             (rect.left(), rect.bottom(), 1, -1),
                             (rect.right(), rect.bottom(), -1, -1)):
            painter.drawLine(QPointF(x + dx * 8, y + dy * 2), QPointF(x + dx * (8 + tick), y + dy * 2))
            painter.drawLine(QPointF(x + dx * 2, y + dy * 8), QPointF(x + dx * 2, y + dy * (8 + tick)))


class SidePanel(QWidget):
    """Left rail with a soft top glow."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        painter.fillRect(rect, qc('#060c11', 218))
        glow = QRadialGradient(QPointF(rect.left(), rect.top()), rect.width() * 1.5)
        glow.setColorAt(0.0, qc(MINT, 26))
        glow.setColorAt(1.0, qc(MINT, 0))
        painter.fillRect(rect, glow)
        painter.setPen(QPen(qc(MINT, 26), 1))
        painter.drawLine(QPointF(rect.right(), rect.top()), QPointF(rect.right(), rect.bottom()))


# --------------------------------------------------------------------- controls
class NavButton(HoverMixin, QAbstractButton):
    """Sidebar item that paints its own animated active pill."""

    def __init__(self, glyph: str, text: str, parent=None):
        super().__init__(parent)
        self.glyph = glyph
        self.caption = text
        self._active = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._init_hover()
        self._active_anim = QPropertyAnimation(self, b'active', self)
        self._active_anim.setDuration(240)
        self._active_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def sizeHint(self) -> QSize:
        return QSize(170, 46)

    @Property(float)
    def hover(self) -> float:
        return self._hover

    @hover.setter
    def hover(self, value: float):
        self._hover = value
        self.update()

    @Property(float)
    def active(self) -> float:
        return self._active

    @active.setter
    def active(self, value: float):
        self._active = value
        self.update()

    def set_active(self, active: bool):
        self._active_anim.stop()
        self._active_anim.setStartValue(self._active)
        self._active_anim.setEndValue(1.0 if active else 0.0)
        self._active_anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 3, -2, -3)
        strength = max(self._active, self._hover * 0.55)
        if strength > 0.01:
            body = QLinearGradient(rect.topLeft(), rect.topRight())
            body.setColorAt(0.0, qc(MINT, int(38 * strength)))
            body.setColorAt(1.0, qc(MINT, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(body))
            painter.drawRoundedRect(rect, 12, 12)
            bar = QRectF(rect.left(), rect.top() + 9, 3, rect.height() - 18)
            painter.setBrush(qc(MINT, int(90 + 150 * strength)))
            painter.drawRoundedRect(bar, 1.5, 1.5)
        glyph_font = display_font(15, 600)
        text_font = display_font(14, 600)
        painter.setFont(glyph_font)
        painter.setPen(qc(MINT if self._active > 0.4 else FAINT))
        painter.drawText(QRectF(rect.left() + 15, rect.top(), 26, rect.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.glyph)
        painter.setFont(text_font)
        painter.setPen(qc(TEXT if self._active > 0.4 else mix(MUTED, TEXT, self._hover)))
        painter.drawText(QRectF(rect.left() + 44, rect.top(), rect.width() - 52, rect.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.caption)


class Switch(QAbstractButton):
    """Animated toggle used instead of a checkbox for daily habits."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(50, 24)
        self._knob = 0.0
        self._anim = QPropertyAnimation(self, b'knob', self)
        self._anim.setDuration(190)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate_toggle)

    @Property(float)
    def knob(self) -> float:
        return self._knob

    @knob.setter
    def knob(self, value: float):
        self._knob = value
        self.update()

    def _animate_toggle(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._knob)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        self._knob = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(2, 3, 46, 18)
        painter.setPen(QPen(qc(mix('#3d5c68', MINT, self._knob), 220), 1))
        painter.setBrush(qc(mix('#1d323c', MINT_SOFT, self._knob), 235))
        painter.drawRoundedRect(track, 9, 9)
        knob_x = 4 + 28 * self._knob
        if self._knob > 0.02:
            halo = QRadialGradient(QPointF(knob_x + 7, 12), 16)
            halo.setColorAt(0.0, qc(MINT, int(90 * self._knob)))
            halo.setColorAt(1.0, qc(MINT, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(QPointF(knob_x + 7, 12), 16, 16)
        knob = QRectF(knob_x, 5, 14, 14)
        knob_grad = QLinearGradient(knob.topLeft(), knob.bottomRight())
        knob_grad.setColorAt(0.0, mix('#7b8e99', '#ffffff', self._knob))
        knob_grad.setColorAt(1.0, mix('#57686f', '#c9f7e2', self._knob))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(knob_grad))
        painter.drawEllipse(knob)


class AnimatedNumber(QLabel):
    """Counts up/down to a value instead of jumping."""

    def __init__(self, value: float = 0.0, suffix: str = '', decimals: int = 0,
                 size: int = 26, color: str = MINT, parent=None):
        super().__init__(parent)
        self.suffix = suffix
        self.decimals = decimals
        self._value = float(value)
        font = display_font(size, 700, 0.4)
        self.setFont(font)
        self.setStyleSheet(f'color:{color}; background:transparent;')
        self._render(self._value)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(620)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_step)

    def _format(self, value: float) -> str:
        return f'{value:.{self.decimals}f}{self.suffix}'

    def _render(self, value: float):
        self.setText(self._format(value))

    def _on_step(self, value):
        self._value = float(value)
        self._render(self._value)

    def set_value(self, value: float, animate: bool = True):
        target = float(value)
        if not animate or abs(target - self._value) < 1e-9:
            self._anim.stop()
            self._value = target
            self._render(target)
            return
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(target)
        self._anim.start()


class AnimatedBar(QWidget):
    """Progress bar with a gradient fill, glow head and animated value."""

    def __init__(self, value: float = 0.0, height: int = 9, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._target = 0.0
        self.height_px = height
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._anim = QPropertyAnimation(self, b'value', self)
        self._anim.setDuration(620)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.set_value(value, animate=False)

    @Property(float)
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, value: float):
        self._value = value
        self.update()

    def set_value(self, value: float, animate: bool = True):
        self._target = max(0.0, min(1.0, float(value)))
        if not animate:
            self._anim.stop()
            self.value = self._target
            return
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(self._target)
        self._anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = self.height_px / 2
        rect = QRectF(0, 0, self.width(), self.height_px)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qc('#132630', 220))
        painter.drawRoundedRect(rect, radius, radius)
        filled = max(0.0, min(1.0, self._value)) * self.width()
        if filled <= 0.5:
            return
        fill = QRectF(0, 0, filled, self.height_px)
        gradient = QLinearGradient(fill.topLeft(), fill.topRight())
        gradient.setColorAt(0.0, qc(MINT_SOFT))
        gradient.setColorAt(0.55, qc(MINT))
        gradient.setColorAt(1.0, qc(CYAN))
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(fill, radius, radius)
        head = QPointF(filled - radius, self.height_px / 2)
        halo = QRadialGradient(head, self.height_px * 2.2)
        halo.setColorAt(0.0, qc(CYAN, 130))
        halo.setColorAt(1.0, qc(CYAN, 0))
        painter.setBrush(QBrush(halo))
        painter.drawEllipse(head, self.height_px * 2.2, self.height_px * 2.2)


class Ring(QWidget):
    """Circular progress with a glowing sweep and centred value."""

    def __init__(self, progress: float = 0.0, size: int = 132, thickness: int = 9,
                 caption: str = '', color: str = MINT, parent=None):
        super().__init__(parent)
        self._progress = 0.0
        self.caption = caption
        self.color = color
        self.thickness = thickness
        self._center = ''
        self.setFixedSize(size, size)
        self._anim = QPropertyAnimation(self, b'progress', self)
        self._anim.setDuration(900)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.set_progress(progress, animate=False)

    @Property(float)
    def progress(self) -> float:
        return self._progress

    @progress.setter
    def progress(self, value: float):
        self._progress = value
        self.update()

    def set_progress(self, progress: float, animate: bool = True):
        target = max(0.0, min(1.0, float(progress)))
        if not animate:
            self._anim.stop()
            self.progress = target
            return
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.start()

    def set_center_text(self, text: str):
        self._center = text
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        inset = self.thickness / 2 + 4
        rect = QRectF((self.width() - side) / 2 + inset, (self.height() - side) / 2 + inset,
                      side - inset * 2, side - inset * 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(qc('#122630', 230), self.thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 0, 360 * 16)
        if self._progress <= 0.001:
            return
        span = -int(360 * 16 * self._progress)
        conical = QConicalGradient(rect.center(), 90)
        conical.setColorAt(0.0, qc(self.color))
        conical.setColorAt(0.5, qc(CYAN))
        conical.setColorAt(1.0, qc(self.color))
        # glow pass
        painter.setPen(QPen(qc(self.color, 55), self.thickness + 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 90 * 16, span)
        painter.setPen(QPen(QBrush(conical), self.thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 90 * 16, span)
        painter.setFont(display_font(25, 700, 0.5))
        painter.setPen(qc(TEXT))
        label_rect = QRectF(rect.left(), rect.center().y() - 22, rect.width(), 34)
        painter.drawText(label_rect, int(Qt.AlignmentFlag.AlignCenter), self._center)
        if self.caption:
            painter.setFont(display_font(9, 600, 1.2))
            painter.setPen(qc(FAINT))
            painter.drawText(QRectF(rect.left(), rect.center().y() + 12, rect.width(), 18),
                             int(Qt.AlignmentFlag.AlignCenter), self.caption.upper())


class TimerRing(QWidget):
    """Large elapsed-time ring with a pulse while a session is running."""

    def __init__(self, size: int = 236, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.seconds = 0
        self.status = 'READY WHEN YOU ARE'
        self.running = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_seconds(self, seconds: int):
        self.seconds = max(0, int(seconds))
        self.update()

    def set_status(self, status: str):
        self.status = status
        self.update()

    def set_running(self, running: bool):
        self.running = running
        if running:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.055) % (math.pi * 2)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        inset = 12
        rect = QRectF((self.width() - side) / 2 + inset, (self.height() - side) / 2 + inset,
                      side - inset * 2, side - inset * 2)
        center = rect.center()
        pulse = (math.sin(self._phase) + 1) / 2 if self.running else 0.0
        halo = QRadialGradient(center, rect.width() * 0.62)
        halo.setColorAt(0.0, qc(MINT, int(10 + 26 * pulse)))
        halo.setColorAt(0.7, qc(CYAN, int(4 + 10 * pulse)))
        halo.setColorAt(1.0, qc(CYAN, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(halo))
        painter.drawEllipse(center, rect.width() * 0.62, rect.width() * 0.62)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(qc('#122630', 235), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 0, 360 * 16)
        if self.running:
            start = int((math.degrees(self._phase) * 16) + 90 * 16)
            painter.setPen(QPen(qc(MINT, 70), 17, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(rect, start, -78 * 16)
            gradient = QConicalGradient(center, 90)
            gradient.setColorAt(0.0, qc(CYAN))
            gradient.setColorAt(0.4, qc(MINT))
            gradient.setColorAt(1.0, qc(VIOLET))
            painter.setPen(QPen(QBrush(gradient), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(rect, start, -78 * 16)
        else:
            span = -360 * 16 * (1.0 if self.seconds else 0.0)
            if span:
                painter.setPen(QPen(qc(MINT_SOFT, 190), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawArc(rect, 90 * 16, span)
        secs = self.seconds
        if secs >= 3600:
            text = f'{secs // 3600}:{secs // 60 % 60:02d}:{secs % 60:02d}'
        else:
            text = f'{secs // 60:02d}:{secs % 60:02d}'
        painter.setFont(display_font(56, 700, 1.0))
        painter.setPen(qc(TEXT))
        painter.drawText(QRectF(rect.left(), center.y() - 44, rect.width(), 64),
                         int(Qt.AlignmentFlag.AlignCenter), text)
        painter.setFont(display_font(9, 600, 1.6))
        painter.setPen(qc(MINT if self.running else FAINT))
        painter.drawText(QRectF(rect.left(), center.y() + 26, rect.width(), 20),
                         int(Qt.AlignmentFlag.AlignCenter), self.status.upper())


class Sparkline(QWidget):
    """Tiny animated bar chart for the last N days."""

    def __init__(self, values: list[float | None], height: int = 34, parent=None):
        super().__init__(parent)
        self.values = values
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._t = 0.0
        self._anim = QPropertyAnimation(self, b'reveal', self)
        self._anim.setDuration(700)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    @Property(float)
    def reveal(self) -> float:
        return self._t

    @reveal.setter
    def reveal(self, value: float):
        self._t = value
        self.update()

    def set_values(self, values: list[float | None]):
        if values == self.values:
            return
        self.values = values
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def paintEvent(self, event):
        if not self.values:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        count = len(self.values)
        gap = 3
        width = max(2.0, (self.width() - gap * (count - 1)) / count)
        base = self.height() - 1
        for index, value in enumerate(self.values):
            x = index * (width + gap)
            if value is None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(qc('#16262e', 200))
                painter.drawRoundedRect(QRectF(x, base - 4, width, 4), 2, 2)
                continue
            grow = self._t * (0.35 + 0.65 * value)
            bar_h = max(3.0, (self.height() - 4) * grow)
            bar = QRectF(x, base - bar_h, width, bar_h)
            gradient = QLinearGradient(bar.topLeft(), bar.bottomLeft())
            gradient.setColorAt(0.0, qc(CYAN if value >= 0.999 else MINT, 235))
            gradient.setColorAt(1.0, qc(MINT_SOFT, 90))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(bar, 2, 2)


class Heatmap(QWidget):
    """Contribution grid that animates in and colour-morphs when data changes."""

    def __init__(self, calendar: dict[str, float | None], compact: bool = False, parent=None):
        super().__init__(parent)
        self.data = dict(calendar)
        self._previous = dict(calendar)
        self.compact = compact
        # Fixed height: inside a vertical card layout the widget would otherwise be
        # stretched and paint a large empty band under the grid.
        self.setFixedHeight(116 if compact else 214)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.positions = []
        self._hover_key = None
        self._reveal = 1.0
        self._anim = QPropertyAnimation(self, b'reveal', self)
        self._anim.setDuration(700)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    @Property(float)
    def reveal(self) -> float:
        return self._reveal

    @reveal.setter
    def reveal(self, value: float):
        self._reveal = value
        self.update()

    def set_data(self, calendar: dict[str, float | None]):
        if calendar == self.data:
            return
        self._previous = dict(self.data)
        self.data = dict(calendar)
        self._hover_key = None
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        keys = sorted(self.data.keys())
        if not keys:
            return
        first = date.fromisoformat(keys[0]); last = date.fromisoformat(keys[-1])
        start = first - timedelta(days=first.weekday())
        cols = ((last - start).days // 7) + 1
        if self.compact:
            left, top, gap, cap = 3, 3, 4, 13
            legend_room = 0
        else:
            left, top, gap, cap = 46, 20, 5, 22
            legend_room = 40
        usable_w = max(8, self.width() - left - 6)
        usable_h = max(8, self.height() - top - legend_room)
        # Cells shrink to fit both axes, so the legend can never be clipped and a
        # narrow window still shows the whole grid.
        cell = min(cap,
                   max(4, int(usable_w / cols) - gap),
                   max(4, int((usable_h - 6 * gap) / 7)))
        grid_w = cols * cell + (cols - 1) * gap
        grid_left = left if self.compact else left + max(0, (usable_w - grid_w) // 2)
        self.positions = []
        if not self.compact:
            painter.setPen(qc(FAINT))
            painter.setFont(display_font(9, 500, 0.8))
            label_x = max(4, grid_left - 42)
            for idx, txt in [(0, 'Mon'), (2, 'Wed'), (4, 'Fri')]:
                painter.drawText(label_x, top + idx * (cell + gap) + cell, txt)
        for key in keys:
            d = date.fromisoformat(key)
            col = (d - start).days // 7
            row = d.weekday()
            x = grid_left + col * (cell + gap)
            y = top + row * (cell + gap)
            value = self.data[key]
            colour = heat_color(value)
            previous = heat_color(self._previous.get(key))
            colour = mix(previous, colour, self._reveal)
            alpha = 255
            if self._reveal < 1.0:
                alpha = int(255 * max(0.0, min(1.0, self._reveal * (cols + 1) - col)))
            if value == 0:
                alpha = int(alpha * 0.9)
            rect = QRectF(x, y, cell, cell)
            painter.setBrush(qc(colour.name(), alpha))
            painter.drawRoundedRect(rect, 3.5, 3.5)
            if self._hover_key == key:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(qc('#ffffff', 190), 1.2))
                painter.drawRoundedRect(rect.adjusted(0.4, 0.4, -0.4, -0.4), 3.5, 3.5)
                painter.setPen(Qt.PenStyle.NoPen)
            if key == keys[-1]:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(qc(MINT, 120), 1.0))
                painter.drawRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5), 4.5, 4.5)
                painter.setPen(Qt.PenStyle.NoPen)
            self.positions.append((rect, key, value))
        if not self.compact:
            self._paint_legend(painter, grid_left, top, cell, gap)

    def _paint_legend(self, painter: QPainter, left: int, top: int, cell: int, gap: int):
        y = top + 7 * (cell + gap) + 16
        painter.setFont(display_font(9, 500, 0.8))
        metrics = painter.fontMetrics()
        x = left
        painter.setPen(qc(FAINT))
        painter.drawText(x, y, 'LESS')
        x += metrics.horizontalAdvance('LESS') + 10
        painter.setPen(Qt.PenStyle.NoPen)
        for colour in HEAT:
            painter.setBrush(qc(colour))
            painter.drawRoundedRect(QRectF(x, y - 10, 11, 11), 3, 3)
            x += 15
        painter.setPen(qc(FAINT))
        painter.drawText(x + 4, y, 'MORE')
        x += metrics.horizontalAdvance('MORE') + 22
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qc(EMPTY_CELL))
        painter.drawRoundedRect(QRectF(x, y - 10, 11, 11), 3, 3)
        painter.setPen(qc(FAINT))
        painter.drawText(x + 17, y, 'NOT TRACKED')

    def mouseMoveEvent(self, event):
        position = event.position()
        hover = None
        for rect, day, value in self.positions:
            if rect.contains(position):
                hover = (day, value)
                break
        if hover == self._hover_key:
            return
        self._hover_key = hover[0] if hover else None
        self.update()
        if hover is None:
            QToolTip.hideText()
            return
        day, value = hover
        text = f'{day}  •  Not tracked' if value is None else f'{day}  •  {round(value * 100)}% complete'
        QToolTip.showText(event.globalPosition().toPoint(), text, self)

    def leaveEvent(self, event):
        self._hover_key = None
        self.update()
        QToolTip.hideText()
        super().leaveEvent(event)


class FadeOverlay(QWidget):
    """Paints a snapshot that fades out. Uses painter opacity instead of a
    QGraphicsOpacityEffect, which blocks QApplication.quit() in PySide6."""

    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._opacity = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._anim = QPropertyAnimation(self, b'opacity', self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.deleteLater)

    @Property(float)
    def opacity(self) -> float:
        return self._opacity

    @opacity.setter
    def opacity(self, value: float):
        self._opacity = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        painter.drawPixmap(0, 0, self._pixmap)

    def start(self):
        self.show()
        self.raise_()
        self._anim.start()


class Toast(QWidget):
    """Frameless notification that slides up and fades out."""

    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(340)
        self.accent = MINT
        self.title_text = ''
        self.body_text = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 18, 16)
        layout.setSpacing(4)
        self.title_label = QLabel(); self.title_label.setFont(display_font(13, 700, 0.4))
        self.title_label.setStyleSheet(f'color:{TEXT}; background:transparent;')
        self.body_label = QLabel(); self.body_label.setFont(display_font(12, 400))
        self.body_label.setWordWrap(True)
        self.body_label.setStyleSheet(f'color:{MUTED}; background:transparent;')
        layout.addWidget(self.title_label); layout.addWidget(self.body_label)
        self._fade = QPropertyAnimation(self, b'windowOpacity', self)
        self._fade.setDuration(240)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)
        self._closing = False
        self._fade.finished.connect(self._on_fade_finished)

    def _on_fade_finished(self):
        if self._closing:
            self._closing = False
            self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath(); path.addRoundedRect(rect, 16, 16)
        body = QLinearGradient(rect.topLeft(), rect.bottomRight())
        body.setColorAt(0.0, qc('#0d1b24', 248))
        body.setColorAt(1.0, qc('#081219', 248))
        painter.fillPath(path, QBrush(body))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(qc(self.accent, 190), 1.1))
        painter.drawRoundedRect(rect, 16, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qc(self.accent))
        painter.drawRoundedRect(QRectF(rect.left(), rect.top() + 14, 3, rect.height() - 28), 1.5, 1.5)

    def show_message(self, title: str, body: str, accent: str = MINT, msec: int = 3400):
        self.accent = accent
        self.title_text = title
        self.body_text = body
        self.title_label.setText(title)
        self.body_label.setText(body)
        self.adjustSize()
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else self.rect()
        x = area.right() - self.width() - 26
        y = area.bottom() - self.height() - 26
        self.move(x, y + 18)
        self.setWindowOpacity(0.0)
        self._closing = False
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(0.0); self._fade.setEndValue(1.0)
        self._slide = QPropertyAnimation(self, b'pos', self)
        self._slide.setDuration(240)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.setStartValue(self.pos())
        self._slide.setEndValue(self.pos() - QPointF(0, 18).toPoint())
        self._slide.start()
        self._fade.start()
        self._hide_timer.start(msec)

    def _fade_out(self):
        self._closing = True
        self._fade.stop()
        self._fade.setStartValue(1.0); self._fade.setEndValue(0.0)
        self._fade.start()
