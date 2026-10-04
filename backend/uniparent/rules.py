"""Pure decision logic: given the stored intent and the time, is a group/device off, why, and until when.

No I/O here so the whole policy is unit-testable.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

# Stand-in for "until someone changes it" on device overrides; cleared whenever the group turns back on.
FOREVER = 2**31 - 1


@dataclass(frozen=True)
class Schedule:
    id: int
    group_id: int
    days: str       # weekday digits the window starts on, Mon=0
    start: str      # "HH:MM"
    end: str        # "HH:MM"
    enabled: bool = True
    label: str = ""


@dataclass(frozen=True)
class State:
    off: bool
    reason: str = ""            # off: manual | pause | schedule | group; on: bonus | ""
    until: int | None = None    # epoch seconds when this state is expected to end, None = until changed
    detail: str = ""            # e.g. schedule label


ON = State(False)


def parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    t = dtime(int(h), int(m))
    return t


def validate_schedule(days: str, start: str, end: str) -> None:
    if not days or any(c not in "0123456" for c in days) or len(set(days)) != len(days):
        raise ValueError("days must be distinct digits 0-6 (Mon=0)")
    if parse_hhmm(start) == parse_hhmm(end):
        raise ValueError("start and end must differ")


def _window_on(day: datetime, s: Schedule, tz: ZoneInfo) -> tuple[datetime, datetime]:
    d = day.date()
    start = datetime.combine(d, parse_hhmm(s.start), tz)
    end = datetime.combine(d, parse_hhmm(s.end), tz)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def active_window(schedules: list[Schedule], now: int, tz: ZoneInfo) -> tuple[int, Schedule] | None:
    """If any enabled schedule covers `now`, return (latest end, that schedule)."""
    local = datetime.fromtimestamp(now, tz)
    best = None
    for s in schedules:
        if not s.enabled:
            continue
        for back in (0, 1):  # a window that started yesterday can still be running
            day = local - timedelta(days=back)
            if str(day.weekday()) not in s.days:
                continue
            start, end = _window_on(day, s, tz)
            if start.timestamp() <= now < end.timestamp():
                e = int(end.timestamp())
                if best is None or e > best[0]:
                    best = (e, s)
    return best


def next_window_start(schedules: list[Schedule], now: int, tz: ZoneInfo) -> tuple[int, Schedule] | None:
    """Next schedule start strictly after `now`, looking a week ahead."""
    local = datetime.fromtimestamp(now, tz)
    best = None
    for s in schedules:
        if not s.enabled:
            continue
        for ahead in range(0, 8):
            day = local + timedelta(days=ahead)
            if str(day.weekday()) not in s.days:
                continue
            start, _ = _window_on(day, s, tz)
            ts = int(start.timestamp())
            if ts > now:
                if best is None or ts < best[0]:
                    best = (ts, s)
                break
    return best


def next_window_end(schedules: list[Schedule], now: int, tz: ZoneInfo) -> int | None:
    """Next time a schedule window ends strictly after `now` (the running one included), a week ahead."""
    local = datetime.fromtimestamp(now, tz)
    best = None
    for s in schedules:
        if not s.enabled:
            continue
        for ahead in range(-1, 8):
            day = local + timedelta(days=ahead)
            if str(day.weekday()) not in s.days:
                continue
            _, end = _window_on(day, s, tz)
            ts = int(end.timestamp())
            if ts > now and (best is None or ts < best):
                best = ts
    return best


def next_morning(now: int, tz: ZoneInfo, hour: int = 7) -> int:
    local = datetime.fromtimestamp(now, tz)
    m = datetime.combine(local.date(), dtime(hour), tz)
    if m <= local:
        m = datetime.combine(local.date() + timedelta(days=1), dtime(hour), tz)
    return int(m.timestamp())


def _live(ts: int | None, now: int) -> bool:
    return ts is not None and ts > now


def group_state(group: dict, schedules: list[Schedule], now: int, tz: ZoneInfo) -> State:
    if _live(group.get("bonus_until"), now):
        return State(False, "bonus", group["bonus_until"])  # extra screen time; locks again afterwards
    if group["manual_off"]:
        return State(True, "manual")
    if _live(group["pause_until"], now):
        return State(True, "pause", group["pause_until"])
    win = active_window(schedules, now, tz)
    if win and not _live(group["override_until"], now):
        return State(True, "schedule", win[0], win[1].label)
    return ON


def device_state(device: dict, group: State | None, now: int) -> State:
    if _live(device.get("bonus_until"), now):
        return State(False, "bonus", device["bonus_until"])
    if device["manual_off"]:
        return State(True, "manual")
    if _live(device["pause_until"], now):
        return State(True, "pause", device["pause_until"])
    if group is not None and group.off and not _live(device["override_until"], now):
        return State(True, "group", group.until, group.detail)
    return ON
