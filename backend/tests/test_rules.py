from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from uniparent.rules import (FOREVER, Schedule, active_window, device_state, group_state, next_window_start,
                             validate_schedule)

TZ = ZoneInfo("America/New_York")


def ts(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp())


# 2026-09-28 is a Monday (weekday 0).
SCHOOL_NIGHTS = Schedule(1, 1, "01236", "21:00", "07:00", label="Bedtime")  # Sun–Thu nights: Mon..Thu + Sun
HOMEWORK = Schedule(2, 1, "01234", "15:30", "17:00", label="Homework")


def group(**kw):
    return {"manual_off": 0, "pause_until": None, "override_until": None, **kw}


def device(**kw):
    return {"manual_off": 0, "pause_until": None, "override_until": None, **kw}


@pytest.mark.parametrize("now,expected_end", [
    (ts(2026, 9, 28, 21, 0), ts(2026, 9, 29, 7, 0)),    # starts Monday 9 PM
    (ts(2026, 9, 29, 6, 59), ts(2026, 9, 29, 7, 0)),    # still Monday's window early Tuesday
    (ts(2026, 9, 28, 16, 0), ts(2026, 9, 28, 17, 0)),   # homework
])
def test_active_window(now, expected_end):
    win = active_window([SCHOOL_NIGHTS, HOMEWORK], now, TZ)
    assert win and win[0] == expected_end


@pytest.mark.parametrize("now", [
    ts(2026, 9, 29, 7, 0),     # window end is exclusive
    ts(2026, 9, 28, 20, 59),
    ts(2026, 10, 2, 22, 0),    # Friday night: '4' not in days
    ts(2026, 10, 3, 6, 0),     # early Saturday: Friday's window doesn't exist
])
def test_inactive(now):
    assert active_window([SCHOOL_NIGHTS], now, TZ) is None


def test_saturday_morning_after_sunday_start_not_listed():
    # Sunday (6) is in days, so early Monday is covered by Sunday's window
    assert active_window([SCHOOL_NIGHTS], ts(2026, 10, 5, 6, 0), TZ)


def test_disabled_schedule_ignored():
    off = Schedule(3, 1, "0123456", "00:00", "23:59", enabled=False)
    assert active_window([off], ts(2026, 9, 28, 12), TZ) is None


def test_next_window_start():
    nxt = next_window_start([SCHOOL_NIGHTS, HOMEWORK], ts(2026, 9, 28, 12), TZ)
    assert nxt[0] == ts(2026, 9, 28, 15, 30) and nxt[1].label == "Homework"
    assert next_window_start([SCHOOL_NIGHTS], ts(2026, 10, 2, 12), TZ)[0] == ts(2026, 10, 4, 21)


def test_dst_fall_back_window_ends_at_local_seven():
    # 2026-11-01 is the US fall-back Sunday; Saturday isn't in SCHOOL_NIGHTS, use every night
    every = Schedule(4, 1, "0123456", "21:00", "07:00")
    win = active_window([every], ts(2026, 11, 1, 3), TZ)
    assert datetime.fromtimestamp(win[0], TZ).hour == 7


def test_validate_schedule():
    validate_schedule("0123", "21:00", "07:00")
    for bad in [("", "21:00", "07:00"), ("7", "21:00", "07:00"), ("00", "21:00", "07:00"),
                ("0", "21:00", "21:00")]:
        with pytest.raises(ValueError):
            validate_schedule(*bad)


def test_group_precedence():
    now = ts(2026, 9, 28, 22)  # inside Bedtime
    assert group_state(group(manual_off=1), [SCHOOL_NIGHTS], now, TZ).reason == "manual"
    assert group_state(group(pause_until=now + 60), [], now, TZ).reason == "pause"
    st = group_state(group(), [SCHOOL_NIGHTS], now, TZ)
    assert st.off and st.reason == "schedule" and st.detail == "Bedtime"
    # "Turn back on" during a schedule sets an override until the window ends
    assert not group_state(group(override_until=ts(2026, 9, 29, 7)), [SCHOOL_NIGHTS], now, TZ).off
    assert not group_state(group(), [SCHOOL_NIGHTS], ts(2026, 9, 28, 12), TZ).off
    # expired pause is ignored
    assert not group_state(group(pause_until=now - 1), [], now, TZ).off


def test_device_precedence():
    now = 1_000_000
    off_group = group_state(group(manual_off=1), [], now, TZ)
    on_group = group_state(group(), [], now, TZ)
    assert device_state(device(), off_group, now).reason == "group"
    assert not device_state(device(override_until=FOREVER), off_group, now).off
    assert device_state(device(manual_off=1), on_group, now).reason == "manual"
    assert device_state(device(pause_until=now + 5), on_group, now).reason == "pause"
    assert not device_state(device(), on_group, now).off
    assert not device_state(device(), None, now).off
    # an individual off wins over an override
    assert device_state(device(manual_off=1, override_until=FOREVER), off_group, now).off
