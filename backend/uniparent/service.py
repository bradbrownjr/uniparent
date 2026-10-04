"""Everything that ties stored intent, rules and the controller together."""
import asyncio
import logging
import time
from datetime import datetime

from .config import Settings
from .db import DB
from .rules import (FOREVER, Schedule, State, active_window, device_state, group_state, next_morning,
                    next_window_end, next_window_start)
from .unifi import Client, UniFi, UniFiError

log = logging.getLogger("uniparent")

MAC_CHARS = set("0123456789abcdef:")


def norm_mac(mac: str) -> str:
    m = mac.strip().lower().replace("-", ":")
    if len(m) != 17 or set(m) - MAC_CHARS:
        raise ValueError(f"bad MAC address: {mac!r}")
    return m


class Service:
    def __init__(self, settings: Settings, db: DB, unifi: UniFi):
        self.s = settings
        self.db = db
        self.unifi = unifi
        self.clients: dict[str, Client] = {}
        self.clients_at = 0.0
        self.last_error: str | None = None
        self._lock = asyncio.Lock()
        self._last_group: dict[int, State] = {}
        self._last_device: dict[str, State] = {}

    # ---- reads -------------------------------------------------------------------------------

    def schedules(self, group_id: int | None = None) -> list[Schedule]:
        rows = self.db.q("SELECT * FROM schedules" + (" WHERE group_id=?" if group_id else ""),
                         (group_id,) if group_id else ())
        return [Schedule(r["id"], r["group_id"], r["days"], r["start"], r["end"], bool(r["enabled"]), r["label"])
                for r in rows]

    def group_states(self, now: int) -> dict[int, State]:
        scheds = self.schedules()
        return {g["id"]: group_state(dict(g), [s for s in scheds if s.group_id == g["id"]], now, self.s.tz)
                for g in self.db.q("SELECT * FROM groups")}

    def device_states(self, now: int, groups: dict[int, State]) -> dict[str, State]:
        return {d["mac"]: device_state(dict(d), groups.get(d["group_id"]), now)
                for d in self.db.q("SELECT * FROM devices")}

    async def refresh_clients(self, max_age: float = 10) -> dict[str, Client]:
        if time.time() - self.clients_at > max_age:
            try:
                self.clients = await self.unifi.clients()
                self.clients_at = time.time()
                self.last_error = None
            except UniFiError as e:
                self.last_error = str(e)
                log.warning("controller unreachable: %s", e)
        return self.clients

    # ---- enforcement ---------------------------------------------------------------------------

    # Seconds after letting a device back on before each nudge (block + unblock, like toggling it by hand).
    NUDGE_AFTER = (180, 600)
    NUDGE_GAP = 5      # seconds between the block and the unblock of a nudge
    LATE = 120         # a change confirmed later than this gets an Activity entry saying so

    async def reconcile(self, now: int | None = None, force: set[str] | None = None) -> None:
        """Push rule changes to the controller, confirm them, and tidy expired timers.

        Edge-triggered: a device is only blocked/unblocked when what UniParent wants for it changes
        (button press, schedule start/end, pause running out) — `devices.applied_off` remembers that intent.
        Each change stays pending (`pending_since`) and is re-sent every pass until reading the controller
        back shows it took; that survives the controller being down or restarting. Once confirmed, whatever
        someone sets in the UniFi app is left alone. MACs in `force` (an explicit button press here) are
        pushed even if our intent didn't change.
        """
        force = force or set()
        nudge: list[str] = []
        async with self._lock:
            now = now or int(time.time())
            self._expire(now)
            groups = self.group_states(now)
            # Device overrides only matter while their group is off (extra screen time is temporary, keep them).
            for gid, st in groups.items():
                if not st.off and st.reason != "bonus":
                    self.db.x("UPDATE devices SET override_until=NULL WHERE group_id=? AND override_until IS NOT NULL",
                              (gid,))
            devices = self.device_states(now, groups)
            clients = await self.refresh_clients(max_age=0)
            self._log_transitions(groups, devices, reachable=not self.last_error)
            if self.last_error:
                # Intent changes stay unapplied (applied_off untouched), so the next pass retries; note when
                # they started waiting so the eventual confirmation can say how late it was.
                for mac, st in devices.items():
                    self.db.x("UPDATE devices SET pending_since=? WHERE mac=? AND pending_since IS NULL "
                              "AND applied_off IS NOT NULL AND applied_off != ?", (now, mac, int(st.off)))
                return
            rows = {r["mac"]: r for r in self.db.q("SELECT * FROM devices")}
            sent = False
            for mac, st in devices.items():
                c = clients.get(mac)
                if c is None or c.wired:
                    continue  # unknown to the controller yet, or wired (no UniFi gateway to block it)
                r = rows[mac]
                prev = r["applied_off"]
                if mac not in force:
                    if prev is None and not st.off:
                        # Newly managed and should be on: don't undo a block someone set in the UniFi app.
                        self.db.x("UPDATE devices SET applied_off=0 WHERE mac=?", (mac,))
                        continue
                    if prev is not None and bool(prev) == st.off and r["pending_since"] is None:
                        continue  # confirmed and nothing changed on our side; respect edits in the UniFi app
                if prev is None or bool(prev) != st.off or mac in force:
                    # New intent: remember it as pending until the controller shows it.
                    self.db.x("UPDATE devices SET applied_off=?, pending_since=COALESCE(pending_since, ?) WHERE mac=?",
                              (int(st.off), now, mac))
                    if st.off and not c.blocked:
                        self.db.x("UPDATE devices SET online_at_block=?, unblocked_at=NULL, nudges=0 WHERE mac=?",
                                  (int(c.online), mac))
                    elif not st.off and c.blocked:
                        self.db.x("UPDATE devices SET unblocked_at=?, nudges=0 WHERE mac=?", (now, mac))
                if st.off == c.blocked:
                    continue
                try:
                    await (self.unifi.block(mac) if st.off else self.unifi.unblock(mac))
                    sent = True
                except UniFiError as e:  # still pending, so the next pass retries
                    self.last_error = str(e)
                    log.warning("could not update %s: %s", mac, e)
            if sent:
                clients = await self.refresh_clients(max_age=0)  # read back what the controller now says
                if self.last_error:
                    return
            nudge = self._confirm_and_watch(now, devices, clients)
        for mac in nudge:
            await self._nudge(mac)

    def _confirm_and_watch(self, now: int, devices: dict[str, State], clients: dict[str, Client]) -> list[str]:
        """Clear pending changes the controller now shows, and watch let-back-on devices rejoin WiFi.

        Returns devices due a nudge: ones that were connected when we blocked them (so they're likely at
        home, not at a friend's) and haven't come back. At most len(NUDGE_AFTER) nudges, one log line each time.
        """
        due = []
        for r in self.db.q("SELECT * FROM devices WHERE pending_since IS NOT NULL OR unblocked_at IS NOT NULL"):
            mac, st, c = r["mac"], devices.get(r["mac"]), clients.get(r["mac"])
            if st is None or c is None or c.wired:
                continue
            if r["pending_since"] is not None and c.blocked == bool(r["applied_off"]):
                self.db.x("UPDATE devices SET pending_since=NULL WHERE mac=?", (mac,))
                late = now - r["pending_since"]
                if late > self.LATE:
                    self.db.log("System", f"Controller finally took the change, {round(late / 60)} min late "
                                          f"— WiFi {'off' if r['applied_off'] else 'on'}", r["label"])
            since = r["unblocked_at"]
            if since is None:
                continue
            if st.off or c.blocked:
                self.db.x("UPDATE devices SET unblocked_at=NULL, nudges=0 WHERE mac=?", (mac,))
            elif c.online:
                self.db.x("UPDATE devices SET unblocked_at=NULL, nudges=0 WHERE mac=?", (mac,))
                if r["nudges"]:
                    self.db.log("System", "Back on WiFi after a nudge", r["label"])
            elif not r["online_at_block"]:
                if now - since > self.NUDGE_AFTER[-1]:  # wasn't here at bedtime: just stop waiting
                    self.db.x("UPDATE devices SET unblocked_at=NULL WHERE mac=?", (mac,))
            elif r["nudges"] < len(self.NUDGE_AFTER):
                if now - since >= self.NUDGE_AFTER[r["nudges"]]:
                    self.db.x("UPDATE devices SET nudges=nudges+1 WHERE mac=?", (mac,))
                    due.append(mac)
            elif now - since >= self.NUDGE_AFTER[-1] + 180:
                self.db.x("UPDATE devices SET unblocked_at=NULL WHERE mac=?", (mac,))
                self.db.log("System", f"Didn't rejoin WiFi even after {r['nudges']} nudges "
                                      "— may be switched off or away from home", r["label"])
        return due

    async def _nudge(self, mac: str) -> None:
        """Block then unblock a device that hasn't rejoined: the same kick as toggling it off and on by hand."""
        async with self._lock:
            d = self.db.one("SELECT applied_off FROM devices WHERE mac=?", (mac,))
            if d is None or d["applied_off"]:
                return  # turned off meanwhile
            # Pending first: if anything fails between the two calls, the background loop finishes the unblock.
            self.db.x("UPDATE devices SET pending_since=? WHERE mac=?", (int(time.time()), mac))
            try:
                await self.unifi.block(mac)
                await asyncio.sleep(self.NUDGE_GAP)
                await self.unifi.unblock(mac)
                self.db.x("UPDATE devices SET pending_since=NULL WHERE mac=?", (mac,))
                log.info("nudged %s", mac)
            except UniFiError as e:
                self.last_error = str(e)
                log.warning("could not nudge %s: %s", mac, e)
            self.clients_at = 0

    def _expire(self, now: int):
        for table in ("groups", "devices"):
            for col in ("pause_until", "override_until", "bonus_until"):
                self.db.x(f"UPDATE {table} SET {col}=NULL WHERE {col} IS NOT NULL AND {col}<=?", (now,))

    def _log_transitions(self, groups: dict[int, State], devices: dict[str, State], reachable: bool = True):
        """Log changes nobody pressed a button for: schedules starting/ending, pauses running out."""
        tail = "" if reachable else " — controller not answering, will keep trying"
        names = {g["id"]: g["name"] for g in self.db.q("SELECT id, name FROM groups")}
        for gid, st in groups.items():
            prev = self._last_group.get(gid)
            if prev is not None and prev.off != st.off:
                if st.off and prev.reason == "bonus":
                    self.db.log("Timer", "Extra time is up — WiFi off" + tail, names[gid])
                elif st.off and st.reason == "schedule":
                    self.db.log("Schedule", f"WiFi off{' — ' + st.detail if st.detail else ''}{tail}", names[gid])
                elif not st.off:
                    self.db.log("Schedule" if prev.reason == "schedule" else "Timer",
                                "WiFi back on" + tail, names[gid])
            self._last_group[gid] = st
        labels = {d["mac"]: d["label"] for d in self.db.q("SELECT mac, label FROM devices")}
        for mac, st in devices.items():
            prev = self._last_device.get(mac)
            if prev is not None and prev.off and not st.off and prev.reason == "pause":
                self.db.log("Timer", "WiFi back on" + tail, labels[mac])
            elif prev is not None and not prev.off and st.off and prev.reason == "bonus":
                self.db.log("Timer", "Extra time is up — WiFi off" + tail, labels[mac])
            self._last_device[mac] = st
        for gone in set(self._last_device) - set(devices):
            del self._last_device[gone]

    def _mark_seen(self, now: int):
        """After a user action, record the new state so it isn't re-logged as a schedule change."""
        groups = self.group_states(now)
        self._last_group.update(groups)
        self._last_device.update(self.device_states(now, groups))

    # ---- user actions ------------------------------------------------------------------------

    def _group_macs(self, gid: int) -> set[str]:
        return {r["mac"] for r in self.db.q("SELECT mac FROM devices WHERE group_id=?", (gid,))}

    async def set_group(self, gid: int, action: str, user: dict, until: int | None = None,
                        minutes: int | None = None) -> None:
        g = self.db.one("SELECT * FROM groups WHERE id=?", (gid,))
        if g is None:
            raise KeyError("group")
        now = int(time.time())
        if action == "bonus":
            if not minutes or minutes <= 0:
                raise ValueError("extra time needs a number of minutes")
            # Stack on top of extra time that's still running: "another 30 minutes".
            until = max(now, g["bonus_until"] or 0) + minutes * 60
            self.db.x("UPDATE groups SET bonus_until=? WHERE id=?", (until, gid))
            self.db.log(user["display_name"], f"Added {self.mins(minutes)} of screen time (until {self.fmt(until)})",
                        g["name"], user["id"])
            self._mark_seen(now)
            await self.reconcile(now, force=self._group_macs(gid))
            return
        if action == "endbonus":
            self.db.x("UPDATE groups SET bonus_until=NULL WHERE id=?", (gid,))
            self.db.log(user["display_name"], "Ended extra time early", g["name"], user["id"])
            self._mark_seen(now)
            await self.reconcile(now, force=self._group_macs(gid))
            return
        # Any on/off/pause replaces running extra time.
        self.db.x("UPDATE groups SET bonus_until=NULL WHERE id=?", (gid,))
        if action == "off":
            self.db.x("UPDATE groups SET manual_off=1, pause_until=NULL, override_until=NULL WHERE id=?", (gid,))
            what = "Turned WiFi off"
        elif action == "pause":
            if not until or until <= now:
                raise ValueError("pause needs a future time")
            self.db.x("UPDATE groups SET manual_off=0, pause_until=?, override_until=NULL WHERE id=?", (until, gid))
            what = f"Paused WiFi until {self.fmt(until)}"
        elif action == "on":
            win = active_window(self.schedules(gid), now, self.s.tz)
            self.db.x("UPDATE groups SET manual_off=0, pause_until=NULL, override_until=? WHERE id=?",
                      (win[0] if win else None, gid))
            what = "Turned WiFi on" + (f" (schedule skipped until {self.fmt(win[0])})" if win else "")
        else:
            raise ValueError(action)
        # A whole-group action resets per-device exceptions inside it.
        self.db.x("UPDATE devices SET override_until=NULL WHERE group_id=?", (gid,))
        self.db.log(user["display_name"], what, g["name"], user["id"])
        self._mark_seen(now)
        await self.reconcile(now, force=self._group_macs(gid))

    async def set_device(self, mac: str, action: str, user: dict, until: int | None = None,
                         minutes: int | None = None) -> None:
        d = self.db.one("SELECT * FROM devices WHERE mac=?", (mac,))
        if d is None:
            raise KeyError("device")
        now = int(time.time())
        if action in ("bonus", "endbonus"):
            if action == "bonus":
                if not minutes or minutes <= 0:
                    raise ValueError("extra time needs a number of minutes")
                new = max(now, d["bonus_until"] or 0) + minutes * 60
                what = f"Added {self.mins(minutes)} of screen time (until {self.fmt(new)})"
            else:
                new, what = None, "Ended extra time early"
            self.db.x("UPDATE devices SET bonus_until=? WHERE mac=?", (new, mac))
            self.db.log(user["display_name"], what, d["label"], user["id"])
            self._mark_seen(now)
            await self.reconcile(now, force={mac})
            return
        self.db.x("UPDATE devices SET bonus_until=NULL WHERE mac=?", (mac,))
        if action == "off":
            # Just this device: off until the child's WiFi next comes back by schedule (or 7 AM), so a
            # forgotten or mis-tapped switch can't leave it off for days. "hold" is the until-I-say-so version.
            until = self.next_on(d["group_id"], now)
            self.db.x("UPDATE devices SET manual_off=0, pause_until=?, override_until=NULL WHERE mac=?", (until, mac))
            what = f"Turned WiFi off until {self.fmt(until)}"
        elif action == "hold":
            self.db.x("UPDATE devices SET manual_off=1, pause_until=NULL, override_until=NULL WHERE mac=?", (mac,))
            what = "Turned WiFi off until turned back on"
        elif action == "pause":
            if not until or until <= now:
                raise ValueError("pause needs a future time")
            self.db.x("UPDATE devices SET manual_off=0, pause_until=?, override_until=NULL WHERE mac=?", (until, mac))
            what = f"Paused WiFi until {self.fmt(until)}"
        elif action == "on":
            gst = self.group_states(now).get(d["group_id"])
            override = None
            if gst and gst.off:
                override = gst.until or FOREVER  # let this one device on while the rest of the group stays off
            self.db.x("UPDATE devices SET manual_off=0, pause_until=NULL, override_until=? WHERE mac=?",
                      (override, mac))
            what = "Turned WiFi on" + (" (while the rest stay off)" if override else "")
        else:
            raise ValueError(action)
        self.db.log(user["display_name"], what, d["label"], user["id"])
        self._mark_seen(now)
        await self.reconcile(now, force={mac})

    async def unblock_all(self, actor: str, user_id: int | None = None) -> int:
        """Escape hatch: clear every off/pause and unblock every managed device on the controller."""
        async with self._lock:
            self.db.x("UPDATE groups SET manual_off=0, pause_until=NULL, override_until=NULL, bonus_until=NULL")
            self.db.x("UPDATE devices SET manual_off=0, pause_until=NULL, override_until=NULL, bonus_until=NULL, "
                      "applied_off=0")
            self.db.x("UPDATE schedules SET enabled=0")
            clients = await self.refresh_clients(max_age=0)
            n = 0
            for d in self.db.q("SELECT mac FROM devices"):
                c = clients.get(d["mac"])
                if c and c.blocked:
                    await self.unifi.unblock(d["mac"])
                    c.blocked = False
                    n += 1
            self.db.log(actor, f"Unblocked everything and paused all schedules ({n} devices)", "", user_id)
            self._mark_seen(int(time.time()))
            return n

    # ---- traffic -------------------------------------------------------------------------------

    async def poll_traffic(self, now: int | None = None) -> None:
        now = now or int(time.time())
        clients = await self.refresh_clients(max_age=0)
        if self.last_error:
            return
        prev = {r["mac"]: r["total"] for r in self.db.q("SELECT mac, total FROM counters")}
        for mac, c in clients.items():
            if not c.online or c.total_bytes is None:
                continue
            before = prev.get(mac)
            # Counters restart when a client re-associates; count the new total as this interval's traffic.
            delta = c.total_bytes - before if before is not None and c.total_bytes >= before else c.total_bytes
            if before is not None and delta > 0:
                self.db.x("INSERT OR REPLACE INTO traffic (mac, ts, bytes) VALUES (?,?,?)", (mac, now, delta))
            self.db.x("INSERT OR REPLACE INTO counters (mac, total, ts) VALUES (?,?,?)", (mac, c.total_bytes, now))
        self.db.x("DELETE FROM traffic WHERE ts < ?", (now - self.s.traffic_days * 86400,))

    def last_active(self) -> dict[str, int]:
        return {r["mac"]: r["ts"] for r in self.db.q(
            "SELECT mac, MAX(ts) AS ts FROM traffic WHERE bytes >= ? GROUP BY mac", (self.s.active_bytes,))}

    def traffic(self, mac: str, since: int) -> list[dict]:
        return [dict(r) for r in self.db.q("SELECT ts, bytes FROM traffic WHERE mac=? AND ts>=? ORDER BY ts",
                                            (mac, since))]

    # ---- helpers -------------------------------------------------------------------------------

    @staticmethod
    def mins(m: int) -> str:
        if m % 60 == 0:
            h = m // 60
            return f"{h} hour{'s' if h > 1 else ''}"
        return f"{m} min"

    def fmt(self, ts: int) -> str:
        d = datetime.fromtimestamp(ts, self.s.tz)
        same_day = d.date() == datetime.now(self.s.tz).date()
        return d.strftime("%-I:%M %p" if same_day else "%a %-I:%M %p")

    def next_on(self, gid: int | None, now: int) -> int:
        """When a device switched off by itself comes back: next schedule end for its child, else 7 AM."""
        end = next_window_end(self.schedules(gid), now, self.s.tz) if gid else None
        return end or next_morning(now, self.s.tz)

    def next_off(self, gid: int, now: int) -> tuple[int, str] | None:
        n = next_window_start(self.schedules(gid), now, self.s.tz)
        return (n[0], n[1].label) if n else None

    async def run_forever(self):
        """Background loop: reconcile every RECONCILE_SECONDS, poll traffic every POLL_SECONDS."""
        last_poll = 0.0
        while True:
            try:
                await self.reconcile()
                if time.time() - last_poll >= self.s.poll_seconds:
                    await self.poll_traffic()
                    last_poll = time.time()
            except Exception:  # never let the loop die
                log.exception("background loop error")
            await asyncio.sleep(self.s.reconcile_seconds)
