import time
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from conftest import H, KID_PHONE, KID_TABLET, KID_TV, PLUG


def status(c):
    r = c.get("/api/status")
    assert r.status_code == 200, r.text
    return r.json()


def devs(c):
    return {d["mac"]: d for g in status(c)["groups"] for d in g["devices"]}


# ---- auth -----------------------------------------------------------------------------------------

def test_requires_login(app):
    c = TestClient(app)
    assert c.get("/api/status").status_code == 401
    assert c.post("/api/groups/1/off", headers=H).status_code == 401


def test_wrong_password_and_rate_limit(app):
    c = TestClient(app)
    for _ in range(5):
        assert c.post("/api/login", json={"username": "amy", "password": "nope"}, headers=H).status_code == 401
    r = c.post("/api/login", json={"username": "amy", "password": "battery staple"}, headers=H)
    assert r.status_code == 429


def test_csrf_header_required(parent, kid):
    assert parent.post(f"/api/groups/{kid}/off").status_code == 403
    assert parent.post(f"/api/groups/{kid}/off", headers=H).status_code == 200


def test_session_cookie_flags(app):
    c = TestClient(app)
    r = c.post("/api/login", json={"username": "amy", "password": "battery staple"}, headers=H)
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc and "max-age=31536000" in sc


def test_logout(parent):
    assert parent.post("/api/logout", headers=H).status_code == 200
    assert parent.get("/api/me").status_code == 401


def test_parent_cannot_admin(parent, kid):
    assert parent.get("/api/admin/clients").status_code == 403
    assert parent.put(f"/api/admin/devices/{PLUG}", json={"label": "x"}, headers=H).status_code == 403
    assert parent.post("/api/admin/unblock-all", headers=H).status_code == 403


def test_password_change_signs_out_sessions(admin, parent, app):
    uid = [u for u in admin.get("/api/admin/users").json() if u["username"] == "amy"][0]["id"]
    assert admin.put(f"/api/admin/users/{uid}", json={"password": "new password!"}, headers=H).status_code == 200
    assert parent.get("/api/me").status_code == 401


# ---- on / off ---------------------------------------------------------------------------------------

def test_group_off_blocks_wireless_only(parent, kid, fake):
    parent.post(f"/api/groups/{kid}/off", headers=H)
    assert fake.c[KID_PHONE].blocked and fake.c[KID_TABLET].blocked
    assert not fake.c[KID_TV].blocked, "wired devices can't be blocked without a UniFi gateway"
    assert not fake.c[PLUG].blocked, "unmanaged devices are never touched"
    g = status(parent)["groups"][0]
    assert g["state"]["off"] and g["state"]["reason"] == "manual"
    parent.post(f"/api/groups/{kid}/on", headers=H)
    assert not fake.c[KID_PHONE].blocked and not fake.c[KID_TABLET].blocked


def test_device_off_and_exception_while_group_off(parent, kid, fake):
    parent.post(f"/api/devices/{KID_TABLET}/off", headers=H)
    assert fake.c[KID_TABLET].blocked and not fake.c[KID_PHONE].blocked
    parent.post(f"/api/devices/{KID_TABLET}/on", headers=H)
    parent.post(f"/api/groups/{kid}/off", headers=H)
    # let the tablet on for homework while the rest stay off
    parent.post(f"/api/devices/{KID_TABLET}/on", headers=H)
    assert not fake.c[KID_TABLET].blocked and fake.c[KID_PHONE].blocked
    # turning the group back on and off again resets that exception
    parent.post(f"/api/groups/{kid}/on", headers=H)
    parent.post(f"/api/groups/{kid}/off", headers=H)
    assert fake.c[KID_TABLET].blocked


def test_pause_expires(app, parent, kid, fake):
    r = parent.post(f"/api/groups/{kid}/pause", json={"minutes": 30}, headers=H)
    assert r.status_code == 200
    d = devs(parent)[KID_PHONE]
    assert d["state"]["reason"] == "group" and d["state"]["until"] > time.time() + 29 * 60
    assert fake.c[KID_PHONE].blocked
    # jump past the pause
    import asyncio
    asyncio.run(app.state.svc.reconcile(int(time.time()) + 31 * 60))
    assert not fake.c[KID_PHONE].blocked
    log = parent.get("/api/log").json()
    assert log[0]["actor"] == "Timer" and log[0]["action"] == "WiFi back on"


def test_pause_validation(parent, kid):
    assert parent.post(f"/api/groups/{kid}/pause", json={"until": 5}, headers=H).status_code == 400
    assert parent.post(f"/api/groups/{kid}/pause", json={"minutes": 0}, headers=H).status_code == 422


def test_schedule_and_skip_tonight(admin, parent, kid, fake, app):
    tz = app.state.settings.tz
    now = datetime.now(tz)
    start = (now - timedelta(minutes=5)).strftime("%H:%M")
    end = (now + timedelta(minutes=60)).strftime("%H:%M")
    day = str((now - timedelta(minutes=5)).weekday())
    r = admin.post("/api/admin/schedules", json={"group_id": kid, "days": day, "start": start, "end": end,
                                                "label": "Homework"}, headers=H)
    assert r.status_code == 200, r.text
    assert fake.c[KID_PHONE].blocked
    g = status(parent)["groups"][0]
    assert g["state"]["reason"] == "schedule" and g["state"]["detail"] == "Homework"
    # "Turn on" during a schedule skips the rest of this window
    parent.post(f"/api/groups/{kid}/on", headers=H)
    assert not fake.c[KID_PHONE].blocked
    assert "schedule skipped" in parent.get("/api/log").json()[0]["action"]


def test_bad_schedule_rejected(admin, kid):
    r = admin.post("/api/admin/schedules", json={"group_id": kid, "days": "9", "start": "21:00", "end": "07:00"},
                   headers=H)
    assert r.status_code == 400
    r = admin.post("/api/admin/schedules", json={"group_id": kid, "days": "0", "start": "25:00", "end": "07:00"},
                   headers=H)
    assert r.status_code == 422


def test_unifi_app_changes_are_respected(app, parent, kid, fake):
    import asyncio
    parent.post(f"/api/groups/{kid}/off", headers=H)
    fake.c[KID_PHONE].blocked = False    # someone allowed it in the UniFi app
    fake.c[KID_TABLET].blocked = False
    asyncio.run(app.state.svc.reconcile())
    assert not fake.c[KID_PHONE].blocked, "the background loop must not undo UniFi app changes"
    d = devs(parent)[KID_PHONE]
    assert d["state"]["off"] and not d["blocked"]  # UI can say "allowed in the UniFi app"
    # ...but pressing a button in UniParent is an explicit request and wins
    parent.post(f"/api/devices/{KID_PHONE}/off", headers=H)
    assert fake.c[KID_PHONE].blocked
    parent.post(f"/api/groups/{kid}/off", headers=H)
    assert fake.c[KID_TABLET].blocked


def test_unifi_app_block_respected_while_on(app, parent, kid, fake):
    import asyncio
    fake.c[KID_PHONE].blocked = True     # blocked in the UniFi app while UniParent says on
    asyncio.run(app.state.svc.reconcile())
    assert fake.c[KID_PHONE].blocked


def test_schedule_edges_still_apply(app, parent, kid, fake):
    import asyncio
    svc = app.state.svc
    until = int(time.time()) + 600
    parent.post(f"/api/groups/{kid}/pause", json={"until": until}, headers=H)
    fake.c[KID_PHONE].blocked = False    # allowed in UniFi app mid-pause: left alone...
    asyncio.run(svc.reconcile())
    assert not fake.c[KID_PHONE].blocked
    fake.c[KID_TABLET].blocked = True    # ...and when the pause ends, our unblock is sent
    asyncio.run(svc.reconcile(until + 1))
    assert not fake.c[KID_TABLET].blocked


def test_new_device_added_to_off_group_is_blocked(admin, kid, fake):
    admin.post(f"/api/groups/{kid}/off", headers=H)
    admin.put(f"/api/admin/devices/{PLUG}", json={"label": "Riley's lamp", "group_id": kid}, headers=H)
    assert fake.c[PLUG].blocked


def test_forget_leaves_unifi_app_block(admin, kid, fake):
    fake.c[KID_PHONE].blocked = True     # blocked in the UniFi app, not by us
    admin.delete(f"/api/admin/devices/{KID_PHONE}", headers=H)
    assert fake.c[KID_PHONE].blocked


def test_controller_down_reported(app, parent, kid, fake):
    fake.down = True
    r = parent.post(f"/api/groups/{kid}/off", headers=H)
    assert r.status_code == 200 and "controller down" in r.json()["controller_error"]
    fake.down = False
    import asyncio
    asyncio.run(app.state.svc.reconcile())
    assert fake.c[KID_PHONE].blocked


def test_log_records_who(parent, kid):
    parent.post(f"/api/groups/{kid}/off", headers=H)
    e = parent.get("/api/log").json()[0]
    assert (e["actor"], e["action"], e["target"]) == ("Amy", "Turned WiFi off", "Riley")


# ---- admin -----------------------------------------------------------------------------------------

def test_clients_list_marks_managed_and_randomized(admin, kid):
    rows = {r["mac"]: r for r in admin.get("/api/admin/clients").json()}
    assert rows[KID_PHONE]["managed"] and rows[KID_PHONE]["label"] == "Riley's phone"
    assert not rows[PLUG]["managed"] and rows[PLUG]["new"]
    assert rows[PLUG]["randomized_mac"]  # 0xaa has the locally-administered bit set


def test_forget_device_unblocks(admin, kid, fake):
    admin.post(f"/api/devices/{KID_PHONE}/off", headers=H)
    assert fake.c[KID_PHONE].blocked
    assert admin.delete(f"/api/admin/devices/{KID_PHONE}", headers=H).status_code == 200
    assert not fake.c[KID_PHONE].blocked


def test_bad_mac(admin):
    assert admin.put("/api/admin/devices/zz", json={"label": "x"}, headers=H).status_code == 400
    assert admin.post("/api/devices/zz/off", headers=H).status_code == 400


def test_unblock_all(admin, parent, kid, fake):
    parent.post(f"/api/groups/{kid}/off", headers=H)
    r = admin.post("/api/admin/unblock-all", headers=H)
    assert r.json()["unblocked"] == 2
    assert not any(c.blocked for c in fake.c.values())
    assert not status(parent)["groups"][0]["state"]["off"]


def test_traffic_and_last_active(app, admin, kid, fake):
    import asyncio
    svc = app.state.svc
    asyncio.run(svc.poll_traffic(1000))                 # baseline counters
    fake.c[KID_PHONE].total_bytes += 5_000_000          # busy
    fake.c[KID_TABLET].total_bytes += 10                # idle chatter
    asyncio.run(svc.poll_traffic(1060))
    fake.c[KID_TABLET].total_bytes = 50                 # re-associated: counter reset
    asyncio.run(svc.poll_traffic(1120))
    assert svc.last_active() == {KID_PHONE: 1060}
    assert [r["bytes"] for r in svc.traffic(KID_TABLET, 0)] == [10, 50]


# ---- confirming changes and getting devices back on WiFi -------------------------------------------

def run(app, now=None):
    import asyncio
    asyncio.run(app.state.svc.reconcile(now))


def test_change_stays_pending_until_controller_shows_it(app, parent, kid, fake):
    fake.ignore = True                    # controller says ok but doesn't apply it
    parent.post(f"/api/groups/{kid}/off", headers=H)
    d = devs(parent)[KID_PHONE]
    assert d["pending"] and not d["blocked"], "UI must not claim it's off until the controller agrees"
    fake.calls.clear()
    run(app)
    assert ("block", KID_PHONE) in fake.calls, "unconfirmed changes are re-sent every pass"
    fake.ignore = False
    run(app)
    d = devs(parent)[KID_PHONE]
    assert d["blocked"] and not d["pending"]
    fake.calls.clear()
    fake.c[KID_PHONE].blocked = False     # once confirmed, a UniFi app change is still respected
    run(app)
    assert fake.calls == []


def test_outage_over_schedule_end_is_applied_and_logged_late(app, parent, kid, fake):
    until = int(time.time()) + 600
    parent.post(f"/api/groups/{kid}/pause", json={"until": until}, headers=H)
    fake.down = True
    run(app, until + 1)                   # pause ends while the controller is down
    log = parent.get("/api/log").json()
    assert log[0]["action"] == "WiFi back on — controller not answering, will keep trying"
    fake.down = False
    run(app, until + 30 * 60)
    assert not fake.c[KID_PHONE].blocked
    assert any("30 min late" in e["action"] for e in parent.get("/api/log").json())


def test_nudge_device_that_does_not_rejoin(app, parent, kid, fake):
    until = int(time.time()) + 600
    parent.post(f"/api/groups/{kid}/pause", json={"until": until}, headers=H)  # phone was online at block
    run(app, until + 1)
    assert not fake.c[KID_PHONE].blocked and devs(parent)[KID_PHONE]["waiting"]
    fake.calls.clear()
    run(app, until + 60)
    assert fake.calls == [], "give it a few minutes on its own first"
    run(app, until + 200)
    assert [c for c in fake.calls if c[1] == KID_PHONE] == [("block", KID_PHONE), ("unblock", KID_PHONE)]
    assert not fake.c[KID_PHONE].blocked
    fake.c[KID_PHONE].online = True       # the kick worked
    run(app, until + 230)
    assert parent.get("/api/log").json()[0]["action"] == "Back on WiFi after a nudge"
    assert not devs(parent)[KID_PHONE]["waiting"]


def test_nudges_are_capped_with_one_log_line(app, parent, kid, fake):
    until = int(time.time()) + 600
    parent.post(f"/api/groups/{kid}/pause", json={"until": until}, headers=H)
    run(app, until + 1)
    before = len(parent.get("/api/log").json())
    fake.calls.clear()
    for t in range(30, 3600, 30):         # an hour of background passes, phone never comes back
        run(app, until + t)
    assert fake.calls.count(("block", KID_PHONE)) == 2
    log = parent.get("/api/log").json()
    phone = [e for e in log[:len(log) - before] if e["target"] == "Riley's phone"]
    assert len(phone) == 1 and "even after 2 nudges" in phone[0]["action"]
    assert not fake.c[KID_PHONE].blocked


def test_no_nudge_for_device_away_at_bedtime(app, parent, kid, fake):
    fake.c[KID_PHONE].online = False      # at a sleepover: not on our WiFi when it was blocked
    until = int(time.time()) + 600
    parent.post(f"/api/groups/{kid}/pause", json={"until": until}, headers=H)
    run(app, until + 1)
    fake.calls.clear()
    before = len(parent.get("/api/log").json())
    for t in range(30, 3600, 30):
        run(app, until + t)
    assert ("block", KID_PHONE) not in fake.calls
    log = parent.get("/api/log").json()
    assert not [e for e in log[:len(log) - before] if e["target"] == "Riley's phone"]


def test_device_switch_off_is_timed_hold_is_not(admin, parent, kid, fake, app):
    parent.post(f"/api/devices/{KID_PHONE}/off", headers=H)
    st = devs(parent)[KID_PHONE]["state"]
    assert st["reason"] == "pause" and st["until"] is not None, "a lone device off must come back by itself"
    assert fake.c[KID_PHONE].blocked
    parent.post(f"/api/devices/{KID_TABLET}/hold", headers=H)
    st = devs(parent)[KID_TABLET]["state"]
    assert st["reason"] == "manual" and st["until"] is None
    assert parent.post(f"/api/groups/{kid}/hold", headers=H).status_code == 400


def test_follow_up_block_after_two_minutes(app, parent, kid, fake):
    t = int(time.time())
    parent.post(f"/api/groups/{kid}/pause", json={"until": t + 3600}, headers=H)
    run(app, t)
    fake.calls.clear()
    run(app, t + 60)
    assert fake.calls == []
    run(app, t + 150)                     # closes the gap a device can slip back on through
    assert sorted(fake.calls) == [("block", KID_PHONE), ("block", KID_TABLET)]
    fake.calls.clear()
    for s in range(180, 1800, 30):
        run(app, t + s)
    assert fake.calls == [], "just the one follow-up"
    assert "kicked" not in parent.get("/api/log").json()[0]["action"]


def test_rekick_when_an_ap_hides_a_station(app, parent, kid, fake):
    t = int(time.time())
    parent.post(f"/api/devices/{KID_PHONE}/off", json={"until": t + 3600}, headers=H)
    run(app, t + 150)                     # follow-up block done
    fake.calls.clear()
    fake.hidden = {"Upstairs": 1}         # the phone got back on; the controller still lists it blocked + offline
    run(app, t + 180)
    assert fake.calls == [], "one odd count could be a roam in progress"
    run(app, t + 210)
    assert fake.calls == [("block", KID_PHONE)]
    fake.hidden = {}                      # the kick took it off
    run(app, t + 240)
    e = parent.get("/api/log").json()[0]
    assert e["action"] == "Got back on WiFi while off — kicked off again" and e["target"] == "Riley's phone"


def test_rekick_is_rate_limited_and_quiet_when_hidden_station_is_not_ours(app, parent, kid, fake):
    t = int(time.time())
    parent.post(f"/api/groups/{kid}/pause", json={"until": t + 3600}, headers=H)
    run(app, t + 150)
    before = len(parent.get("/api/log").json())
    fake.calls.clear()
    fake.hidden = {"Downstairs": 1}       # something someone blocked in the UniFi app, say
    for s in range(180, 1080, 30):
        run(app, t + s)
    assert fake.calls.count(("block", KID_PHONE)) == 3 and fake.calls.count(("block", KID_TABLET)) == 3
    assert ("block", KID_TV) not in fake.calls  # wired
    assert len(parent.get("/api/log").json()) == before


def test_no_rekick_once_back_on(app, parent, kid, fake):
    t = int(time.time())
    parent.post(f"/api/groups/{kid}/pause", json={"until": t + 60}, headers=H)
    run(app, t + 90)                      # pause over before the follow-up was due
    fake.calls.clear()
    fake.hidden = {"Upstairs": 1}
    for s in range(120, 600, 30):
        run(app, t + s)
    for mac in (KID_PHONE, KID_TABLET):   # only nudges (block + unblock), never a re-kick
        assert fake.calls.count(("block", mac)) == fake.calls.count(("unblock", mac)), fake.calls
        assert not fake.c[mac].blocked
