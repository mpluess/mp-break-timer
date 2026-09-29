"""Tray icon and break logic."""

import logging
import math
import os
import subprocess
import sys
import time
from datetime import datetime
from enum import Enum, auto
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from mp_break_timer.config import APP_DIR, CONFIG_PATH, Config, load_config
from mp_break_timer.overlay import BreakOverlay
from mp_break_timer.state import DayState, format_hm
from mp_break_timer.widgets import CornerPills
from mp_break_timer.winapi import is_session_locked

log = logging.getLogger(__name__)

TICK_MS = 200
# A gap between two ticks longer than this means the laptop was asleep.
SLEEP_GAP_S = 30

ICON_NORMAL = "#2a9d8f"
ICON_ESCALATED = "#f4a261"
ICON_DISABLED = "#e63946"


class Mode(Enum):
    WORKING = auto()
    BREAK = auto()
    DISABLED = auto()


def _make_icon(color: str) -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(3, 3, 58, 58)
    pen = QPen(QColor("white"), 6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(32, 32, 32, 14)
    painter.drawLine(32, 32, 45, 39)
    painter.end()
    return QIcon(pixmap)


class Controller(QObject):
    def __init__(self, app: QApplication, config: Config, config_error: str | None, lock: QLockFile):
        super().__init__()
        self._app = app
        self._cfg = config
        self._lock = lock
        self._state = DayState.load()
        self._mode = Mode.WORKING
        now = time.time()
        self._next_break_at = now + self._interval_s()
        # The upcoming break was already snoozed once (no second snooze).
        self._snoozed = False
        self._break_started_at = 0.0
        self._disabled_since = 0.0
        self._last_tick = now
        self._away_since: float | None = None

        self._overlay = BreakOverlay(config)
        self._overlay.snooze_requested.connect(self._snooze)
        self._overlay.disable_requested.connect(self._disable)
        self._overlay.back_to_work_requested.connect(lambda: self._resume_work(time.time()))
        self._overlay.fields_changed.connect(self._on_fields_changed)
        self._warning_pills = CornerPills(click_through=True)
        self._start_now_pills = CornerPills(click_through=False)
        self._start_now_pills.clicked.connect(self._start_snoozed_break_now)
        self._disabled_pills = CornerPills(click_through=False)
        self._disabled_pills.clicked.connect(self._enable)

        self._icons = {color: _make_icon(color) for color in (ICON_NORMAL, ICON_ESCALATED, ICON_DISABLED)}
        self._icon_color = ICON_NORMAL
        self._tray = QSystemTrayIcon(self._icons[ICON_NORMAL])
        self._menu = QMenu()
        self._status_action = self._info_action()
        self._work_action = self._info_action()
        if config_error:
            self._info_action().setText(f"⚠ {config_error}")
        self._menu.addSeparator()
        self._toggle_action = self._menu.addAction("Disable breaks")
        self._toggle_action.triggered.connect(self._toggle_enabled)
        self._menu.addSeparator()
        self._menu.addAction("Open config").triggered.connect(self._open_config)
        self._menu.addAction("Restart").triggered.connect(self._restart)
        self._menu.addAction("Quit").triggered.connect(self._quit)
        self._tray.setContextMenu(self._menu)
        self._tray.show()

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        log.info("Started, next break in %.0f min", self._interval_s() / 60)
        self._tick()

    def _info_action(self) -> QAction:
        action = self._menu.addAction("")
        action.setEnabled(False)
        return action

    # --- main loop ---------------------------------------------------------------

    def _tick(self) -> None:
        now = time.time()
        if not self._state.is_today():
            self._state = DayState.for_today()
            self._state.save()
            self._overlay.set_fields("", "")
        if self._check_away(now):
            return
        self._ensure_start_prefilled()

        if self._mode is Mode.WORKING:
            remaining = self._next_break_at - now
            warning = remaining <= self._cfg.pre_break_warning_sec
            if remaining <= 0:
                self._start_break(now)
            elif warning:
                seconds = math.ceil(remaining)
                self._warning_pills.show(
                    f"Break in {seconds // 60}:{seconds % 60:02d}",
                    remaining / self._cfg.pre_break_warning_sec,
                )
            else:
                self._warning_pills.hide()
            if self._mode is Mode.WORKING and self._snoozed:
                self._start_now_pills.show("Start break now", row=1 if warning else 0)
        elif self._mode is Mode.BREAK:
            self._update_overlay(now)
        elif self._mode is Mode.DISABLED:
            minutes = int((now - self._disabled_since) // 60)
            self._disabled_pills.show(f"Breaks off · {minutes} min · click to re-enable")
        self._refresh_tray(now)

    def _check_away(self, now: float) -> bool:
        """Track lock/sleep periods; returns True while the laptop is locked."""
        gap = now - self._last_tick
        self._last_tick = now
        if gap > SLEEP_GAP_S and self._away_since is None:
            self._away_since = now - gap
        if is_session_locked():
            if self._away_since is None:
                self._away_since = now
            return True
        if self._away_since is not None:
            away_s = now - self._away_since
            self._away_since = None
            self._on_return(now, away_s)
        return False

    def _on_return(self, now: float, away_s: float) -> None:
        log.info("Back after %.1f min locked/asleep", away_s / 60)
        if self._mode is Mode.DISABLED:
            if away_s >= self._cfg.reenable_after_lock_min * 60:
                self._enable()
        elif away_s >= self._cfg.lock_counts_as_break_min * 60:
            self._resume_work(now)

    def _ensure_start_prefilled(self) -> None:
        """Pre-fill work start with the first moment the laptop is in use today."""
        if self._state.start_prefilled:
            return
        self._state.work_start = datetime.now().strftime("%H:%M")
        self._state.start_prefilled = True
        self._state.save()
        self._overlay.set_fields(self._state.work_start, self._state.big_breaks)

    # --- breaks --------------------------------------------------------------------

    def _interval_s(self) -> float:
        minutes = self._cfg.escalated_break_interval_min if self._state.escalated else self._cfg.break_interval_min
        return minutes * 60

    def _start_break(self, now: float) -> None:
        log.info("Break started (snoozed before: %s)", self._snoozed)
        self._mode = Mode.BREAK
        self._break_started_at = now
        self._warning_pills.hide()
        self._start_now_pills.hide()
        self._overlay.open(self._state.work_start, self._state.big_breaks)
        self._update_overlay(now)

    def _update_overlay(self, now: float) -> None:
        work = self._state.work_minutes(datetime.now())
        threshold = self._cfg.max_work_time_min - self._cfg.wrap_up_before_max_min
        escalated = work is not None and work >= threshold
        if escalated != self._state.escalated:
            log.info("Wrap-up escalation %s", "started" if escalated else "cleared")
            self._state.escalated = escalated
            self._state.save()

        wrap_up = None
        if escalated:
            left = self._cfg.max_work_time_min - work
            if left > 0:
                wrap_up = (f"{format_hm(math.ceil(left))} left", False)
            else:
                wrap_up = (f"+{format_hm(-left)} over your limit", True)

        if self._snoozed:
            snooze_block = "Snooze already used for this break"
        elif escalated:
            snooze_block = f"No snoozing after {format_hm(threshold)} work time"
        else:
            snooze_block = None

        work_text = (
            f"Today's work time: {format_hm(work)}"
            if work is not None
            else "Today's work time: enter your work start time"
        )
        total = self._cfg.break_duration_min * 60
        self._overlay.update(
            total - (now - self._break_started_at),
            total,
            work_text,
            wrap_up,
            snooze_block,
            self._state.snooze_count,
        )

    def _on_fields_changed(self, work_start: str, big_breaks: str) -> None:
        self._state.work_start = work_start
        self._state.big_breaks = big_breaks
        self._state.save()
        if self._mode is Mode.BREAK:
            self._update_overlay(time.time())

    def _snooze(self) -> None:
        if self._mode is not Mode.BREAK or self._snoozed or self._state.escalated:
            return
        self._state.snooze_count += 1
        self._state.save()
        log.info("Snoozed (%d today)", self._state.snooze_count)
        self._overlay.close()
        self._mode = Mode.WORKING
        self._snoozed = True
        self._next_break_at = time.time() + self._cfg.snooze_min * 60

    def _start_snoozed_break_now(self) -> None:
        if self._mode is Mode.WORKING and self._snoozed:
            log.info("Snoozed break started early")
            self._start_break(time.time())

    def _resume_work(self, now: float) -> None:
        if self._overlay.is_open():
            self._overlay.close()
        self._mode = Mode.WORKING
        self._snoozed = False
        self._next_break_at = now + self._interval_s()
        log.info("Back to work, next break in %.0f min", self._interval_s() / 60)

    def _disable(self) -> None:
        log.info("Breaks disabled")
        if self._overlay.is_open():
            self._overlay.close()
        self._warning_pills.hide()
        self._start_now_pills.hide()
        self._mode = Mode.DISABLED
        self._snoozed = False
        self._disabled_since = time.time()
        self._refresh_tray(time.time())

    def _enable(self) -> None:
        if self._mode is not Mode.DISABLED:
            return
        log.info("Breaks enabled")
        self._disabled_pills.hide()
        self._resume_work(time.time())
        self._refresh_tray(time.time())

    def _toggle_enabled(self) -> None:
        if self._mode is Mode.DISABLED:
            self._enable()
        else:
            self._disable()

    # --- tray ------------------------------------------------------------------------

    def _refresh_tray(self, now: float) -> None:
        if self._mode is Mode.WORKING:
            minutes = max(1, math.ceil((self._next_break_at - now) / 60))
            prefix = "Snoozed, break" if self._snoozed else "Next break"
            status = f"{prefix} in {minutes} min"
        elif self._mode is Mode.BREAK:
            status = "Break in progress"
        else:
            status = f"Breaks disabled for {int((now - self._disabled_since) // 60)} min"
        work = self._state.work_minutes(datetime.now())
        work_text = f"Work time today: {format_hm(work)}" if work is not None else "Work time today: no start time"

        self._status_action.setText(status)
        self._work_action.setText(work_text)
        self._toggle_action.setText("Enable breaks" if self._mode is Mode.DISABLED else "Disable breaks")
        self._tray.setToolTip(f"MP Break Timer\n{status}\n{work_text}")
        if self._mode is Mode.DISABLED:
            color = ICON_DISABLED
        elif self._state.escalated:
            color = ICON_ESCALATED
        else:
            color = ICON_NORMAL
        if color != self._icon_color:
            self._icon_color = color
            self._tray.setIcon(self._icons[color])

    def _open_config(self) -> None:
        try:
            os.startfile(CONFIG_PATH, "edit")
        except OSError:
            subprocess.Popen(["notepad.exe", str(CONFIG_PATH)])

    def _restart(self) -> None:
        log.info("Restarting")
        self._lock.unlock()
        executable = Path(sys.executable)
        windowless = executable.with_name("pythonw.exe")
        subprocess.Popen([str(windowless if windowless.exists() else executable), "-m", "mp_break_timer"])
        self._quit()

    def _quit(self) -> None:
        log.info("Quit")
        self._tray.hide()
        self._app.quit()


def _setup_logging() -> None:
    handlers: list[logging.Handler] = [
        RotatingFileHandler(APP_DIR / "mp_break_timer.log", maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    ]
    if sys.stderr:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    sys.excepthook = lambda *exc_info: log.critical("Unhandled exception", exc_info=exc_info)


def main() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    _setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("MP Break Timer")
    app.setQuitOnLastWindowClosed(False)

    lock = QLockFile(str(APP_DIR / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(500):
        log.info("Already running, exiting")
        return

    config, config_error = load_config()
    controller = Controller(app, config, config_error, lock)  # noqa: F841 (keeps it alive)
    sys.exit(app.exec())
