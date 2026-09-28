"""Per-day state (snooze count, work time fields), persisted across restarts."""

import json
import logging
import re
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime

from mp_break_timer.config import APP_DIR

log = logging.getLogger(__name__)

STATE_PATH = APP_DIR / "state.json"

_TIME_RE = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


@dataclass
class DayState:
    date: str
    snooze_count: int = 0
    # Raw field texts as entered on the break screen.
    work_start: str = ""
    big_breaks: str = ""
    # Work start is pre-filled once per day; after "Clear fields" it stays empty.
    start_prefilled: bool = False
    # Wrap-up escalation reached (evaluated during breaks).
    escalated: bool = False

    @classmethod
    def for_today(cls) -> "DayState":
        return cls(date=date.today().isoformat())

    @classmethod
    def load(cls) -> "DayState":
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            known = {field.name for field in fields(cls)}
            state = cls(**{key: value for key, value in data.items() if key in known})
        except (OSError, ValueError, TypeError):
            return cls.for_today()
        return state if state.is_today() else cls.for_today()

    def is_today(self) -> bool:
        return self.date == date.today().isoformat()

    def save(self) -> None:
        try:
            STATE_PATH.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            log.exception("Cannot write %s", STATE_PATH)

    def work_minutes(self, now: datetime) -> float | None:
        """Today's work time: now - work start - bigger breaks; None without a valid start time."""
        match = _TIME_RE.fullmatch(self.work_start.strip())
        if not match:
            return None
        start = now.replace(hour=int(match[1]), minute=int(match[2]), second=0, microsecond=0)
        breaks = self.big_breaks.strip()
        breaks_min = int(breaks) if breaks.isdigit() else 0
        return max(0.0, (now - start).total_seconds() / 60 - breaks_min)


def format_hm(minutes: float) -> str:
    hours, mins = divmod(int(minutes), 60)
    return f"{hours}:{mins:02d}"
