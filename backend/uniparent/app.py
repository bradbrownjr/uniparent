"""HTTP API + static PWA."""
import asyncio
import os
import sqlite3
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth
from .config import Settings
from .db import DB
from .rules import State, validate_schedule
from .service import Service, norm_mac
from .unifi import UniFi

# pause: {minutes} or {until}; bonus (extra screen time, locks again after): {minutes}
ACTIONS = ("on", "off", "hold", "pause", "bonus", "endbonus")  # hold: devices only, off until turned on
KINDS = ("phone", "tablet", "laptop", "computer", "tv", "console", "watch", "speaker", "other")


# ---- request bodies ------------------------------------------------------------------------------

class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class Pause(BaseModel):
    minutes: int | None = Field(default=None, ge=1, le=7 * 24 * 60)
    until: int | None = None


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class DeviceIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    kind: str = "other"
    group_id: int | None = None
    notes: str = Field(default="", max_length=500)


class ScheduleIn(BaseModel):
    group_id: int
    days: str
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    enabled: bool = True
    label: str = Field(default="", max_length=40)


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: str = "parent"


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    role: str | None = None


def mac_or_400(mac: str) -> str:
    try:
        return norm_mac(mac)
    except ValueError as e:
        raise HTTPException(400, str(e))


def state_json(st: State) -> dict:
    return {"off": st.off, "reason": st.reason, "until": st.until, "detail": st.detail}


def create_app(settings: Settings | None = None, unifi: UniFi | None = None) -> FastAPI:
    settings = settings or Settings()
    db = DB(settings.db_path)
    if unifi is None and settings.demo:
        from .demo import DemoUniFi, seed
        unifi = DemoUniFi()
        seed(db)
    unifi = unifi or UniFi(settings.unifi_host, settings.unifi_api_key, settings.unifi_site,
                           settings.unifi_verify_tls)
    svc = Service(settings, db, unifi)
    limiter = auth.RateLimit()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(svc.run_forever()) if settings.background else None
        yield
        if task:
            task.cancel()
        await unifi.close()

    app = FastAPI(title="UniParent", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.svc, app.state.db, app.state.settings = svc, db, settings

    # ---- auth plumbing -----------------------------------------------------------------------

    @app.middleware("http")
    async def csrf(request: Request, call_next):
        # Browsers can't add a custom header cross-site without a CORS preflight we never grant,
        # so requiring it on every write blocks cross-site form posts. The session cookie is SameSite=Strict too.
        if (request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS")
                and request.headers.get("x-uniparent") != "1"):
            return JSONResponse({"detail": "missing X-UniParent header"}, status_code=403)
        return await call_next(request)

    def client_ip(request: Request) -> str:
        if settings.trust_proxy and (fwd := request.headers.get("x-forwarded-for")):
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "?"

    def current_user(request: Request) -> dict:
        u = auth.session_user(db, request.cookies.get(auth.COOKIE))
        if u is None:
            raise HTTPException(401, "not signed in")
        return dict(u)

    def admin_user(user: dict = Depends(current_user)) -> dict:
        if user["role"] != "admin":
            raise HTTPException(403, "admins only")
        return user

    def me_json(u: dict) -> dict:
        return {"id": u["id"], "username": u["username"], "display_name": u["display_name"], "role": u["role"]}

    @app.post("/api/login")
    async def login(body: Login, request: Request, response: Response):
        key = f"{client_ip(request)}|{body.username.lower()}"
        if limiter.blocked(key):
            raise HTTPException(429, "Too many tries. Wait 15 minutes and try again.")
        u = auth.check_password(db, body.username, body.password)
        if u is None:
            limiter.fail(key)
            raise HTTPException(401, "Wrong username or password.")
        limiter.reset(key)
        token = auth.new_session(db, u["id"], settings.session_days)
        response.set_cookie(auth.COOKIE, token, max_age=settings.session_days * 86400, httponly=True,
                            secure=settings.cookie_secure, samesite="strict", path="/")
        return me_json(dict(u))

    @app.post("/api/logout")
    async def logout(request: Request, response: Response):
        auth.end_session(db, request.cookies.get(auth.COOKIE))
        response.delete_cookie(auth.COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/me")
    async def me(user: dict = Depends(current_user)):
        return me_json(user)

    @app.get("/api/health")
    async def health():
        return {"ok": True, "controller_error": svc.last_error}

    # ---- parent view ---------------------------------------------------------------------------

    def device_json(d, st: State, clients, active) -> dict:
        c = clients.get(d["mac"])
        return {
            "mac": d["mac"], "label": d["label"], "kind": d["kind"], "group_id": d["group_id"],
            "notes": d["notes"], "state": state_json(st),
            "online": bool(c and c.online), "blocked": bool(c and c.blocked), "wired": bool(c and c.wired),
            "known": c is not None, "ap": c.ap if c else "", "signal": c.signal if c else None,
            "ip": c.ip if c else "", "last_active": active.get(d["mac"]),
            "last_seen": c.last_seen if c else None,
            # Our last change isn't confirmed on the controller yet / let back on, waiting for it to rejoin WiFi.
            "pending": d["pending_since"] is not None, "waiting": d["unblocked_at"] is not None,
        }

    @app.get("/api/status")
    async def status(user: dict = Depends(current_user)):
        now = int(time.time())
        clients = await svc.refresh_clients()
        active = svc.last_active()
        gstates = svc.group_states(now)
        dstates = svc.device_states(now, gstates)
        devices = db.q("SELECT * FROM devices ORDER BY label COLLATE NOCASE")
        groups = []
        for g in db.q("SELECT * FROM groups ORDER BY name COLLATE NOCASE"):
            nxt = svc.next_off(g["id"], now)
            groups.append({
                "id": g["id"], "name": g["name"], "state": state_json(gstates[g["id"]]),
                "next_off": {"ts": nxt[0], "label": nxt[1]} if nxt else None,
                "devices": [device_json(d, dstates[d["mac"]], clients, active)
                            for d in devices if d["group_id"] == g["id"]],
            })
        return {
            "now": now, "me": me_json(user), "controller_error": svc.last_error, "groups": groups,
            "ungrouped": [device_json(d, dstates[d["mac"]], clients, active)
                          for d in devices if d["group_id"] is None],
        }

    def pause_until(body: Pause | None) -> int | None:
        if body is None:
            return None
        if body.minutes:
            return int(time.time()) + body.minutes * 60
        return body.until

    @app.post("/api/groups/{gid}/{action}")
    async def group_action(gid: int, action: str, body: Pause | None = None, user: dict = Depends(current_user)):
        if action not in ACTIONS:
            raise HTTPException(404)
        try:
            await svc.set_group(gid, action, user, pause_until(body), body.minutes if body else None)
        except KeyError:
            raise HTTPException(404, "no such child")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "controller_error": svc.last_error}

    @app.post("/api/devices/{mac}/{action}")
    async def device_action(mac: str, action: str, body: Pause | None = None,
                            user: dict = Depends(current_user)):
        if action not in ACTIONS:
            raise HTTPException(404)
        try:
            await svc.set_device(mac_or_400(mac), action, user, pause_until(body), body.minutes if body else None)
        except KeyError:
            raise HTTPException(404, "no such device")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "controller_error": svc.last_error}

    @app.get("/api/log")
    async def activity(limit: int = 100, user: dict = Depends(current_user)):
        limit = max(1, min(limit, 500))
        return [dict(r) for r in db.q("SELECT id, ts, actor, action, target FROM log ORDER BY id DESC LIMIT ?",
                                      (limit,))]

    # ---- admin: devices --------------------------------------------------------------------------

    @app.get("/api/admin/clients")
    async def all_clients(user: dict = Depends(admin_user)):
        """Every client the controller knows, with our label/group if managed. Newest unlabeled first."""
        now = int(time.time())
        clients = await svc.refresh_clients()
        active = svc.last_active()
        managed = {d["mac"]: d for d in db.q("SELECT * FROM devices")}
        hour = {r["mac"]: r["b"] for r in db.q("SELECT mac, SUM(bytes) AS b FROM traffic WHERE ts>=? GROUP BY mac",
                                                (now - 3600,))}
        out = []
        for mac, c in clients.items():
            d = managed.get(mac)
            out.append({
                "mac": mac, "name": c.name, "hostname": c.hostname, "oui": c.oui, "ip": c.ip, "online": c.online, "wired": c.wired,
                "blocked": c.blocked, "ap": c.ap, "signal": c.signal, "first_seen": c.first_seen,
                "last_seen": c.last_seen, "last_active": active.get(mac), "bytes_last_hour": hour.get(mac, 0),
                "randomized_mac": bool(int(mac[:2], 16) & 2),
                "new": d is None and (c.first_seen or 0) > now - 7 * 86400,
                "managed": d is not None, "label": d["label"] if d else None, "kind": d["kind"] if d else None,
                "group_id": d["group_id"] if d else None, "notes": d["notes"] if d else "",
            })
        for mac, d in managed.items():  # managed but the controller has forgotten it
            if mac not in clients:
                out.append({"mac": mac, "name": d["label"], "oui": "", "ip": "", "online": False, "wired": False,
                            "blocked": False, "ap": "", "signal": None, "first_seen": None, "last_seen": None,
                            "last_active": active.get(mac), "bytes_last_hour": 0, "randomized_mac": False,
                            "new": False, "managed": True, "label": d["label"], "kind": d["kind"],
                            "group_id": d["group_id"], "notes": d["notes"]})
        out.sort(key=lambda r: (not r["new"], r["managed"], not r["online"], (r["label"] or r["name"]).lower()))
        return out

    @app.put("/api/admin/devices/{mac}")
    async def save_device(mac: str, body: DeviceIn, user: dict = Depends(admin_user)):
        mac = mac_or_400(mac)
        if body.kind not in KINDS:
            raise HTTPException(400, f"kind must be one of {KINDS}")
        if body.group_id is not None and not db.one("SELECT 1 FROM groups WHERE id=?", (body.group_id,)):
            raise HTTPException(400, "no such child")
        existed = db.one("SELECT 1 FROM devices WHERE mac=?", (mac,))
        db.x("INSERT INTO devices (mac, label, kind, group_id, notes) VALUES (?,?,?,?,?) "
             "ON CONFLICT(mac) DO UPDATE SET label=excluded.label, kind=excluded.kind, "
             "group_id=excluded.group_id, notes=excluded.notes",
             (mac, body.label.strip(), body.kind, body.group_id, body.notes))
        db.log(user["display_name"], "Updated device" if existed else "Added device", body.label, user["id"])
        await svc.reconcile()
        return {"ok": True}

    @app.delete("/api/admin/devices/{mac}")
    async def forget_device(mac: str, user: dict = Depends(admin_user)):
        mac = mac_or_400(mac)
        d = db.one("SELECT * FROM devices WHERE mac=?", (mac,))
        if d is None:
            raise HTTPException(404)
        db.x("DELETE FROM devices WHERE mac=?", (mac,))
        c = (await svc.refresh_clients(max_age=0)).get(mac)
        if c and c.blocked and d["applied_off"]:  # we blocked it and stop managing it: don't strand it offline
            await svc.unifi.unblock(mac)
        db.log(user["display_name"], "Stopped managing device", d["label"], user["id"])
        return {"ok": True}

    @app.get("/api/admin/traffic/{mac}")
    async def traffic(mac: str, hours: int = 24, user: dict = Depends(admin_user)):
        hours = max(1, min(hours, 24 * 7))
        return svc.traffic(mac_or_400(mac), int(time.time()) - hours * 3600)

    @app.post("/api/admin/unblock-all")
    async def unblock_all(user: dict = Depends(admin_user)):
        n = await svc.unblock_all(user["display_name"], user["id"])
        return {"ok": True, "unblocked": n}

    # ---- admin: groups & schedules ----------------------------------------------------------------

    @app.get("/api/admin/groups")
    async def list_groups(user: dict = Depends(current_user)):
        return [dict(g) for g in db.q("SELECT id, name FROM groups ORDER BY name COLLATE NOCASE")]

    @app.post("/api/admin/groups")
    async def add_group(body: GroupIn, user: dict = Depends(admin_user)):
        if db.one("SELECT 1 FROM groups WHERE name=?", (body.name.strip(),)):
            raise HTTPException(400, "there is already a child with that name")
        gid = db.x("INSERT INTO groups (name) VALUES (?)", (body.name.strip(),))
        db.log(user["display_name"], "Added child", body.name, user["id"])
        return {"id": gid}

    @app.put("/api/admin/groups/{gid}")
    async def rename_group(gid: int, body: GroupIn, user: dict = Depends(admin_user)):
        db.x("UPDATE groups SET name=? WHERE id=?", (body.name.strip(), gid))
        return {"ok": True}

    @app.delete("/api/admin/groups/{gid}")
    async def delete_group(gid: int, user: dict = Depends(admin_user)):
        g = db.one("SELECT name FROM groups WHERE id=?", (gid,))
        if g is None:
            raise HTTPException(404)
        db.x("DELETE FROM groups WHERE id=?", (gid,))  # devices fall back to ungrouped, schedules go
        db.log(user["display_name"], "Removed child", g["name"], user["id"])
        await svc.reconcile()
        return {"ok": True}

    @app.get("/api/admin/schedules")
    async def list_schedules(user: dict = Depends(current_user)):
        return [dict(r) for r in db.q("SELECT * FROM schedules ORDER BY group_id, start")]

    def check_schedule(body: ScheduleIn):
        try:
            validate_schedule(body.days, body.start, body.end)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not db.one("SELECT 1 FROM groups WHERE id=?", (body.group_id,)):
            raise HTTPException(400, "no such child")

    @app.post("/api/admin/schedules")
    async def add_schedule(body: ScheduleIn, user: dict = Depends(admin_user)):
        check_schedule(body)
        sid = db.x("INSERT INTO schedules (group_id, days, start, end, enabled, label) VALUES (?,?,?,?,?,?)",
                   (body.group_id, body.days, body.start, body.end, int(body.enabled), body.label))
        db.log(user["display_name"], f"Added schedule {body.label or ''} {body.start}–{body.end}".replace("  ", " "),
               "", user["id"])
        svc._mark_seen(int(time.time()))
        await svc.reconcile()
        return {"id": sid}

    @app.put("/api/admin/schedules/{sid}")
    async def edit_schedule(sid: int, body: ScheduleIn, user: dict = Depends(admin_user)):
        check_schedule(body)
        db.x("UPDATE schedules SET group_id=?, days=?, start=?, end=?, enabled=?, label=? WHERE id=?",
             (body.group_id, body.days, body.start, body.end, int(body.enabled), body.label, sid))
        db.log(user["display_name"], f"Changed schedule {body.label}".strip(), "", user["id"])
        svc._mark_seen(int(time.time()))
        await svc.reconcile()
        return {"ok": True}

    @app.delete("/api/admin/schedules/{sid}")
    async def delete_schedule(sid: int, user: dict = Depends(admin_user)):
        db.x("DELETE FROM schedules WHERE id=?", (sid,))
        db.log(user["display_name"], "Deleted schedule", "", user["id"])
        svc._mark_seen(int(time.time()))
        await svc.reconcile()
        return {"ok": True}

    # ---- admin: users ------------------------------------------------------------------------------

    @app.get("/api/admin/users")
    async def list_users(user: dict = Depends(admin_user)):
        return [dict(r) for r in db.q("SELECT id, username, display_name, role, created FROM users ORDER BY id")]

    @app.post("/api/admin/users")
    async def add_user(body: UserIn, user: dict = Depends(admin_user)):
        try:
            uid = auth.create_user(db, body.username, body.display_name, body.password, body.role)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "that username is taken")
        db.log(user["display_name"], "Added user", body.username, user["id"])
        return {"id": uid}

    @app.put("/api/admin/users/{uid}")
    async def edit_user(uid: int, body: UserPatch, user: dict = Depends(admin_user)):
        if body.role is not None:
            if body.role not in auth.ROLES:
                raise HTTPException(400, "bad role")
            if uid == user["id"] and body.role != "admin":
                raise HTTPException(400, "you can't remove your own admin role")
            db.x("UPDATE users SET role=? WHERE id=?", (body.role, uid))
        if body.display_name:
            db.x("UPDATE users SET display_name=? WHERE id=?", (body.display_name.strip(), uid))
        if body.password:
            auth.set_password(db, uid, body.password)
        return {"ok": True}

    @app.delete("/api/admin/users/{uid}")
    async def delete_user(uid: int, user: dict = Depends(admin_user)):
        if uid == user["id"]:
            raise HTTPException(400, "you can't delete yourself")
        db.x("DELETE FROM users WHERE id=?", (uid,))
        return {"ok": True}

    # ---- PWA ---------------------------------------------------------------------------------------

    if os.path.isdir(settings.static_dir):
        app.mount("/assets", StaticFiles(directory=os.path.join(settings.static_dir, "assets"), check_dir=False),
                  name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = os.path.realpath(os.path.join(settings.static_dir, path))
            if path and f.startswith(os.path.realpath(settings.static_dir)) and os.path.isfile(f):
                headers = {"Cache-Control": "no-cache"} if path in ("sw.js", "manifest.webmanifest") else None
                return FileResponse(f, headers=headers)
            return FileResponse(os.path.join(settings.static_dir, "index.html"),
                                headers={"Cache-Control": "no-cache"})

    return app
