"""User configuration, read from config.toml in the app data folder."""

import json
import logging
import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

APP_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "mp_break_timer"
CONFIG_PATH = APP_DIR / "config.toml"


@dataclass(frozen=True)
class Config:
    break_interval_min: float = 27
    break_duration_min: float = 3
    snooze_min: float = 3
    hold_seconds: float = 2
    max_work_time_min: float = 300
    wrap_up_before_max_min: float = 15
    escalated_break_interval_min: float = 15
    pre_break_warning_sec: float = 60
    lock_counts_as_break_min: float = 10
    reenable_after_lock_min: float = 10
    back_to_work_message: str = "Mind your FEET position and work PACE"


_COMMENTS = {
    "break_interval_min": 'Minutes of work between breaks, counted from "Back to work".',
    "break_duration_min": "Length of a break in minutes.",
    "snooze_min": "Minutes a snooze postpones the break (only one snooze per break).",
    "hold_seconds": "Seconds the snooze and disable buttons must be held down.",
    "max_work_time_min": "Maximum work time per day in minutes (300 = 5 h).",
    "wrap_up_before_max_min": (
        "Minutes before the maximum at which the wrap-up escalation starts (15 -> at 4:45):\n"
        "# wrap-up message on the break screen, shorter break interval."
    ),
    "escalated_break_interval_min": "Minutes between breaks once the wrap-up escalation has started.",
    "pre_break_warning_sec": "Seconds before a break at which the corner warning appears (0 = no warning).",
    "lock_counts_as_break_min": "Minutes the laptop must be locked or asleep to count as a break.",
    "reenable_after_lock_min": "Minutes the laptop must be locked or asleep to re-enable disabled breaks.",
    "back_to_work_message": 'Message shown next to "Back to work" when the break is over ("" = none).',
}

# Numeric settings for which 0 makes sense; the other numbers must be positive.
_ZERO_ALLOWED = {"hold_seconds", "wrap_up_before_max_min", "pre_break_warning_sec"}


def _default_config_text() -> str:
    lines = [
        "# MP Break Timer configuration.",
        '# Changes take effect after "Restart" in the tray menu.',
        "",
    ]
    for field in fields(Config):
        value = json.dumps(field.default) if isinstance(field.default, str) else f"{field.default:g}"
        lines += [f"# {_COMMENTS[field.name]}", f"{field.name} = {value}", ""]
    return "\n".join(lines)


def load_config() -> tuple[Config, str | None]:
    """Load the config, creating it with defaults on first run.

    Returns the config and an error message if (parts of) the file were invalid.
    Invalid values fall back to their defaults.
    """
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(_default_config_text(), encoding="utf-8")
    try:
        data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.error("Cannot read %s: %s", CONFIG_PATH, exc)
        return Config(), "Config file unreadable, using defaults"

    known = {field.name for field in fields(Config)}
    problems = [f"unknown setting '{key}'" for key in data if key not in known]
    values = {}
    defaults = Config()
    for name in known & data.keys():
        value = data[name]
        if isinstance(getattr(defaults, name), str):
            valid = isinstance(value, str)
        else:
            is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            valid = is_number and (value >= 0 if name in _ZERO_ALLOWED else value > 0)
        if valid:
            values[name] = value
        else:
            problems.append(f"invalid value for '{name}'")
    if problems:
        log.error("Config problems in %s: %s", CONFIG_PATH, "; ".join(problems))
        return Config(**values), "Config has errors, see log (defaults used for those)"
    return Config(**values), None
