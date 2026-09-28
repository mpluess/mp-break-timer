"""Full-screen break overlay covering all screens; controls on the screen with the mouse cursor."""

import math

from PySide6.QtCore import QObject, QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QPalette, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mp_break_timer.config import Config
from mp_break_timer.widgets import BACKGROUND, CountdownRing, HoldButton
from mp_break_timer.winapi import force_foreground, foreground_is_own_process

_STYLE = """
QWidget { color: #e8ecf1; font-family: "Segoe UI"; font-size: 12pt; }
QLabel#title { font-size: 44pt; font-weight: 600; }
QLabel#wrapHeadline { font-size: 28pt; font-weight: 700; color: #ffb454; }
QLabel#wrapDetail { font-size: 22pt; font-weight: 600; }
QLabel#workTime { font-size: 16pt; font-weight: 600; }
QLabel#muted { color: #9aa5b4; font-size: 11pt; }
QLineEdit {
    background: rgba(255, 255, 255, 20); border: 1px solid rgba(255, 255, 255, 70);
    border-radius: 8px; padding: 6px 10px; font-size: 13pt; min-width: 90px; max-width: 110px;
}
QLineEdit:focus { border-color: #2a9d8f; }
QPushButton {
    background: rgba(255, 255, 255, 25); border: 1px solid rgba(255, 255, 255, 80);
    border-radius: 8px; padding: 8px 18px;
}
QPushButton:hover { background: rgba(255, 255, 255, 45); }
QPushButton#backButton {
    background: #2a9d8f; border: none; border-radius: 14px;
    font-size: 18pt; font-weight: 600; padding: 16px 56px;
}
QPushButton#backButton:hover { background: #33b3a3; }
"""

_COLOR_LEFT = "#ffb454"
_COLOR_OVER = "#ff6b6b"


def _label(text: str = "", name: str | None = None) -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if name:
        label.setObjectName(name)
    return label


class _OverlayWindow(QWidget):
    def __init__(self, screen, config: Config, overlay: "BreakOverlay", with_controls: bool):
        super().__init__(
            None,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.allow_close = False
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, BACKGROUND)
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setStyleSheet(_STYLE)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.addStretch(1)
        layout.addWidget(_label("Time for a break", "title"))
        self.ring = CountdownRing()
        if not with_controls:
            layout.addWidget(self.ring, alignment=Qt.AlignmentFlag.AlignCenter)
            layout.addStretch(1)
            return

        self.wrap_headline = _label("Enough work for today, time to wrap up!", "wrapHeadline")
        self.wrap_detail = _label(name="wrapDetail")
        layout.addWidget(self.wrap_headline)
        layout.addWidget(self.wrap_detail)
        layout.addSpacing(8)
        layout.addWidget(self.ring, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(8)

        self.back_button = QPushButton("Back to work")
        self.back_button.setObjectName("backButton")
        self.back_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(overlay.back_to_work_requested)
        layout.addWidget(self.back_button, alignment=Qt.AlignmentFlag.AlignCenter)

        self.actions = QWidget()
        actions_layout = QHBoxLayout(self.actions)
        actions_layout.setSpacing(40)
        actions_layout.addStretch(1)
        snooze_column = QVBoxLayout()
        self.snooze_button = HoldButton(f"I need {config.snooze_min:g} more min", config.hold_seconds)
        self.snooze_button.held.connect(overlay.snooze_requested)
        self.snooze_note = _label(name="muted")
        self.snooze_note.setMinimumSize(self.snooze_button.minimumWidth(), self.snooze_button.height())
        self.snooze_count = _label(name="muted")
        snooze_column.addWidget(self.snooze_button)
        snooze_column.addWidget(self.snooze_note)
        snooze_column.addWidget(self.snooze_count)
        actions_layout.addLayout(snooze_column)
        disable_column = QVBoxLayout()
        disable_button = HoldButton("Disable (meeting, discussion)", config.hold_seconds)
        disable_button.held.connect(overlay.disable_requested)
        disable_column.addWidget(disable_button)
        disable_column.addWidget(_label(" ", "muted"))
        actions_layout.addLayout(disable_column)
        actions_layout.addStretch(1)
        layout.addWidget(self.actions)
        layout.addSpacing(24)

        fields = QGridLayout()
        fields.setHorizontalSpacing(12)
        fields.setVerticalSpacing(8)
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("08:30")
        self.start_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"([01]?\d|2[0-3]):[0-5]\d"))
        )
        self.breaks_edit = QLineEdit()
        self.breaks_edit.setPlaceholderText("0")
        self.breaks_edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,3}")))
        clear_button = QPushButton("Clear fields")
        clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_button.clicked.connect(self._clear_fields)
        for edit in (self.start_edit, self.breaks_edit):
            # Click focus only, so text typed while the overlay appears doesn't land in a field.
            edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            edit.textChanged.connect(
                lambda _text: overlay.fields_changed.emit(self.start_edit.text(), self.breaks_edit.text())
            )
        fields.addWidget(QLabel("Work start (HH:MM)"), 0, 0)
        fields.addWidget(self.start_edit, 0, 1)
        fields.addWidget(QLabel("Bigger breaks, e.g. lunch (min)"), 0, 2)
        fields.addWidget(self.breaks_edit, 0, 3)
        fields.addWidget(clear_button, 0, 4)
        fields_row = QHBoxLayout()
        fields_row.addStretch(1)
        fields_row.addLayout(fields)
        fields_row.addStretch(1)
        layout.addLayout(fields_row)
        self.work_label = _label(name="workTime")
        layout.addWidget(self.work_label)
        layout.addStretch(1)

    def set_fields(self, work_start: str, big_breaks: str) -> None:
        for edit, text in ((self.start_edit, work_start), (self.breaks_edit, big_breaks)):
            if edit.text() != text:
                edit.blockSignals(True)
                edit.setText(text)
                edit.blockSignals(False)

    def _clear_fields(self) -> None:
        self.start_edit.clear()
        self.breaks_edit.clear()

    def closeEvent(self, event):
        if not self.allow_close:
            event.ignore()


class BreakOverlay(QObject):
    snooze_requested = Signal()
    disable_requested = Signal()
    back_to_work_requested = Signal()
    fields_changed = Signal(str, str)

    def __init__(self, config: Config):
        super().__init__()
        self._config = config
        self._windows: list[_OverlayWindow] = []
        self._main: _OverlayWindow | None = None
        self._focus_timer = QTimer(self)
        self._focus_timer.setInterval(500)
        self._focus_timer.timeout.connect(self._keep_in_front)

    def is_open(self) -> bool:
        return bool(self._windows)

    def open(self, work_start: str, big_breaks: str) -> None:
        main_screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        for screen in QGuiApplication.screens():
            window = _OverlayWindow(screen, self._config, self, with_controls=screen == main_screen)
            self._windows.append(window)
            if screen == main_screen:
                self._main = window
        self._main.set_fields(work_start, big_breaks)
        for window in self._windows:
            window.showFullScreen()
        self._main.activateWindow()
        self._main.setFocus()
        force_foreground(int(self._main.winId()))
        self._focus_timer.start()

    def close(self) -> None:
        self._focus_timer.stop()
        for window in self._windows:
            window.allow_close = True
            window.close()
            window.deleteLater()
        self._windows = []
        self._main = None

    def set_fields(self, work_start: str, big_breaks: str) -> None:
        if self._main:
            self._main.set_fields(work_start, big_breaks)

    def update(
        self,
        remaining_s: float,
        total_s: float,
        work_text: str,
        wrap_up: tuple[str, bool] | None,
        snooze_block_reason: str | None,
        snooze_count: int,
    ) -> None:
        """wrap_up is (detail text, over the limit) or None; snooze_block_reason None = snooze available."""
        if not self._main:
            return
        done = remaining_s <= 0
        seconds = math.ceil(remaining_s)
        ring_text = "Done" if done else f"{seconds // 60}:{seconds % 60:02d}"
        for window in self._windows:
            window.ring.set_state(max(0.0, remaining_s / total_s), ring_text)

        main = self._main
        main.back_button.setVisible(done)
        main.actions.setVisible(not done)
        main.snooze_button.setVisible(snooze_block_reason is None)
        main.snooze_note.setVisible(snooze_block_reason is not None)
        main.snooze_note.setText(snooze_block_reason or "")
        main.snooze_count.setText(f"Snoozed today: {snooze_count}×")
        main.work_label.setText(work_text)
        main.wrap_headline.setVisible(wrap_up is not None)
        main.wrap_detail.setVisible(wrap_up is not None)
        if wrap_up:
            detail, over = wrap_up
            main.wrap_detail.setText(detail)
            style = f"color: {_COLOR_OVER if over else _COLOR_LEFT};"
            if main.wrap_detail.styleSheet() != style:
                main.wrap_detail.setStyleSheet(style)

    def _keep_in_front(self) -> None:
        for window in self._windows:
            if window.isMinimized() or not window.isVisible():
                window.showFullScreen()
        if self._main and not foreground_is_own_process():
            force_foreground(int(self._main.winId()))
