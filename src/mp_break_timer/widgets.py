"""Custom widgets: hold-to-activate button, countdown ring and corner pills."""

from PySide6.QtCore import QElapsedTimer, QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

ACCENT = QColor("#2a9d8f")
BACKGROUND = QColor("#1d2433")
TEXT = QColor("#e8ecf1")


class HoldButton(QWidget):
    """Button that only fires after being held down for hold_seconds; releasing early cancels."""

    held = Signal()

    def __init__(self, text: str, hold_seconds: float, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = text
        self._hint = f"hold {hold_seconds:g} s"
        self._hold_ms = max(1, int(hold_seconds * 1000))
        self._progress = 0.0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(76)
        self.setMinimumWidth(max(360, QFontMetrics(self._text_font()).horizontalAdvance(text) + 56))

    def _text_font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(15)
        return font

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._clock.start()
            self._timer.start()

    def mouseReleaseEvent(self, event):
        self._reset()

    def hideEvent(self, event):
        self._reset()

    def _advance(self):
        self._progress = min(1.0, self._clock.elapsed() / self._hold_ms)
        self.update()
        if self._progress >= 1.0:
            self._reset()
            self.held.emit()

    def _reset(self):
        self._timer.stop()
        self._progress = 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        painter.fillPath(path, QColor(255, 255, 255, 25))
        if self._progress > 0:
            painter.save()
            painter.setClipPath(path)
            filled = QRectF(rect.left(), rect.top(), rect.width() * self._progress, rect.height())
            painter.fillRect(filled, ACCENT)
            painter.restore()
        painter.setPen(QPen(QColor(255, 255, 255, 110), 1.5))
        painter.drawPath(path)

        font = self._text_font()
        painter.setFont(font)
        painter.setPen(TEXT)
        painter.drawText(rect.adjusted(12, 6, -12, -24), Qt.AlignmentFlag.AlignCenter, self._text)
        font.setPointSizeF(9.5)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 150))
        painter.drawText(
            rect.adjusted(12, 0, -12, -9),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            self._hint,
        )


class CountdownRing(QWidget):
    """Ring that runs down clockwise, with the remaining time in the middle."""

    def __init__(self, diameter: int = 280, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self._fraction = 1.0
        self._text = ""

    def set_state(self, fraction: float, text: str) -> None:
        if (fraction, text) != (self._fraction, self._text):
            self._fraction, self._text = fraction, text
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = 14
        rect = QRectF(self.rect()).adjusted(width, width, -width, -width)
        painter.setPen(QPen(QColor(255, 255, 255, 35), width))
        painter.drawEllipse(rect)
        if self._fraction > 0:
            pen = QPen(ACCENT, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, -int(self._fraction * 360 * 16))
        font = QFont(self.font())
        font.setPointSizeF(40)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(TEXT)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)


class _Pill(QWidget):
    """Small always-on-top label that never takes focus."""

    clicked = Signal()

    def __init__(self, click_through: bool):
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if click_through:
            flags |= Qt.WindowType.WindowTransparentForInput
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if not click_through:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        font = QFont("Segoe UI")
        font.setPointSizeF(11)
        self.setFont(font)
        self._text = ""
        self._progress: float | None = None

    def set_content(self, text: str, progress: float | None) -> None:
        if (text, progress) == (self._text, self._progress):
            return
        self._text, self._progress = text, progress
        metrics = QFontMetrics(self.font())
        self.resize(metrics.horizontalAdvance(text) + 40, metrics.height() + 24)
        self.update()

    def mousePressEvent(self, event):
        self.clicked.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.fillPath(path, QColor(BACKGROUND.red(), BACKGROUND.green(), BACKGROUND.blue(), 235))
        if self._progress is not None:
            painter.save()
            painter.setClipPath(path)
            bar = QRectF(rect.left(), rect.bottom() - 4, rect.width() * self._progress, 4)
            painter.fillRect(bar, ACCENT)
            painter.restore()
        painter.setPen(QPen(ACCENT, 1.5))
        painter.drawPath(path)
        painter.setPen(TEXT)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)


class CornerPills(QObject):
    """One pill in the bottom-right corner of every screen, showing the same content."""

    clicked = Signal()
    _MARGIN = 16
    _SPACING = 8

    def __init__(self, click_through: bool):
        super().__init__()
        self._click_through = click_through
        self._pills: list[tuple[object, _Pill]] = []

    def show(self, text: str, progress: float | None = None, row: int = 0) -> None:
        """row 0 is the bottom-most position; higher rows stack upwards."""
        screens = QGuiApplication.screens()
        if [screen for screen, _ in self._pills] != screens:
            self.hide()
            for screen in screens:
                pill = _Pill(self._click_through)
                pill.clicked.connect(self.clicked)
                self._pills.append((screen, pill))
        for screen, pill in self._pills:
            pill.set_content(text, progress)
            area = screen.availableGeometry()
            pill.move(
                area.right() - pill.width() - self._MARGIN,
                area.bottom() - pill.height() - self._MARGIN - row * (pill.height() + self._SPACING),
            )
            if not pill.isVisible():
                pill.show()

    def hide(self) -> None:
        for _, pill in self._pills:
            pill.close()
            pill.deleteLater()
        self._pills = []
