# MP Break Timer

A Windows break timer: a full-screen break every 27 minutes. Snoozing and disabling are possible, but only on purpose, and there's a daily work time limit.

## Setup

```
powershell .\install_autostart.ps1   # uv sync + shortcut in the Windows Startup folder
.\.venv\Scripts\mp-break-timer.exe   # start it right away (no console window)
```

Remove autostart with `.\install_autostart.ps1 -Uninstall`.
For debugging with log output in the console: `uv run python -m mp_break_timer`.

## Behaviour

- **Break:** 27 min after "Back to work", a full-screen overlay covers all screens and runs down 3 min. Afterwards, "Back to work" appears.
- **Warning:** 60 s before a break, a small click-through pill in the bottom-right corner counts down. It doesn't take focus and isn't a Windows notification, so DND doesn't hide it.
- **Snooze** ("I need 5 more min"): hold for 2 s. One snooze per break. The break screen shows how often you snoozed today.
- **Disable** ("Disable (meeting, discussion)"): hold for 2 s. While disabled, the tray icon is red and a pill in the corner shows "Breaks off · N min". Click the pill to re-enable. Breaks are also re-enabled automatically after the laptop was locked or asleep for ≥ 10 min.
- **Locked / asleep** for ≥ 10 min counts as a break and restarts the 27 min.
- **Work time** = now − work start − bigger breaks. Work start is pre-filled with the first time the laptop is in use each day. The fields reset at midnight.
- **Wrap-up escalation:** from the first break with work time ≥ 4:45, the break screen shows "Enough work for today, time to wrap up!" with the time left or over the 5 h limit. Snoozing is no longer possible, breaks come every 15 min, and the tray icon turns orange.
- **Tray menu:** time to next break, today's work time, disable/enable, open config, restart, quit.

## Files

Everything lives in `%APPDATA%\mp_break_timer\`:

- `config.toml`: settings, created with defaults on first start. Use "Restart" in the tray menu after editing.
- `state.json`: today's snooze count and work time fields.
- `mp_break_timer.log`: log.
