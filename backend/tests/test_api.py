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
