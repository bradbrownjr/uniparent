"""Extra screen time: WiFi on for N minutes, then it locks again to whatever was in force."""
import asyncio
import sqlite3
import time
from datetime import datetime, timedelta

from conftest import H, KID_PHONE, KID_TABLET
from uniparent.db import DB
from uniparent.rules import State, device_state, group_state


def group_json(c):
    return c.get("/api/status").json()["groups"][0]


def test_rules_bonus_beats_everything():
    now = 1_000
    g = {"manual_off": 1, "pause_until": None, "override_until": None, "bonus_until": now + 60}
    st = group_state(g, [], now, None)
    assert not st.off and st.reason == "bonus" and st.until == now + 60
    assert group_state(g, [], now + 61, None).off  # locks again
    d = {"manual_off": 1, "pause_until": None, "override_until": None, "bonus_until": now + 60}
    assert not device_state(d, State(True, "manual"), now).off


def test_extra_time_then_locks_again(app, parent, kid, fake):
    parent.post(f"/api/groups/{kid}/off", headers=H)
    assert fake.c[KID_PHONE].blocked
    r = parent.post(f"/api/groups/{kid}/bonus", json={"minutes": 60}, headers=H)
    assert r.status_code == 200, r.text
    assert not fake.c[KID_PHONE].blocked and not fake.c[KID_TABLET].blocked
    g = group_json(parent)
    assert g["state"]["reason"] == "bonus" and g["state"]["until"] > time.time() + 59 * 60
    # time runs out -> back to off (manual off is still in force)
    asyncio.run(app.state.svc.reconcile(int(time.time()) + 61 * 60))
    assert fake.c[KID_PHONE].blocked
    log = parent.get("/api/log").json()
    assert (log[0]["actor"], log[0]["action"]) == ("Timer", "Extra time is up — WiFi off")
    assert "Added 1 hour of screen time" in log[1]["action"]


def test_extra_time_stacks(parent, kid):
    parent.post(f"/api/groups/{kid}/off", headers=H)
    parent.post(f"/api/groups/{kid}/bonus", json={"minutes": 30}, headers=H)
    first = group_json(parent)["state"]["until"]
    parent.post(f"/api/groups/{kid}/bonus", json={"minutes": 15}, headers=H)
    assert group_json(parent)["state"]["until"] == first + 15 * 60


def test_end_extra_time_early(parent, kid, fake):
    parent.post(f"/api/groups/{kid}/off", headers=H)
    parent.post(f"/api/groups/{kid}/bonus", json={"minutes": 30}, headers=H)
    assert not fake.c[KID_PHONE].blocked
    parent.post(f"/api/groups/{kid}/endbonus", headers=H)
    assert fake.c[KID_PHONE].blocked
    assert group_json(parent)["state"]["reason"] == "manual"


def test_extra_time_during_schedule(app, admin, parent, kid, fake):
    tz = app.state.settings.tz
    now = datetime.now(tz)
    admin.post("/api/admin/schedules", json={
        "group_id": kid, "days": str((now - timedelta(minutes=5)).weekday()),
        "start": (now - timedelta(minutes=5)).strftime("%H:%M"),
        "end": (now + timedelta(minutes=120)).strftime("%H:%M"), "label": "Bedtime"}, headers=H)
    assert fake.c[KID_PHONE].blocked
    parent.post(f"/api/groups/{kid}/bonus", json={"minutes": 15}, headers=H)
    assert not fake.c[KID_PHONE].blocked
    asyncio.run(app.state.svc.reconcile(int(time.time()) + 16 * 60))
    assert fake.c[KID_PHONE].blocked, "schedule still running, so it locks again"


def test_device_extra_time(app, parent, kid, fake):
    parent.post(f"/api/groups/{kid}/off", headers=H)
    parent.post(f"/api/devices/{KID_TABLET}/bonus", json={"minutes": 60}, headers=H)
    assert not fake.c[KID_TABLET].blocked and fake.c[KID_PHONE].blocked
    asyncio.run(app.state.svc.reconcile(int(time.time()) + 61 * 60))
    assert fake.c[KID_TABLET].blocked


def test_group_extra_time_keeps_device_exception(app, parent, kid, fake):
    parent.post(f"/api/groups/{kid}/off", headers=H)
    parent.post(f"/api/devices/{KID_TABLET}/on", headers=H)   # homework laptop allowed while group is off
    parent.post(f"/api/groups/{kid}/bonus", json={"minutes": 30}, headers=H)
    asyncio.run(app.state.svc.reconcile(int(time.time()) + 31 * 60))
    assert fake.c[KID_PHONE].blocked
    assert not fake.c[KID_TABLET].blocked, "the device exception survives the group's extra time"


def test_bonus_needs_minutes(parent, kid):
    assert parent.post(f"/api/groups/{kid}/bonus", json={}, headers=H).status_code == 400


def test_old_database_is_migrated(tmp_path):
    p = str(tmp_path / "old.db")
    con = sqlite3.connect(p)
    con.executescript("""
        CREATE TABLE groups (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, manual_off INTEGER NOT NULL DEFAULT 0,
            pause_until INTEGER, override_until INTEGER);
        CREATE TABLE devices (mac TEXT PRIMARY KEY, label TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'other',
            group_id INTEGER, manual_off INTEGER NOT NULL DEFAULT 0, pause_until INTEGER, override_until INTEGER,
            notes TEXT NOT NULL DEFAULT '');
        INSERT INTO groups (name) VALUES ('Riley');
    """)
    con.close()
    db = DB(p)
    assert {"bonus_until"} <= {r[1] for r in db.q("PRAGMA table_info(groups)")}
    assert {"bonus_until", "applied_off"} <= {r[1] for r in db.q("PRAGMA table_info(devices)")}
    assert db.one("SELECT name FROM groups")["name"] == "Riley"
