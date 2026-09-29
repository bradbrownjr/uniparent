"""Demo mode (UNIPARENT_DEMO=1): a pretend UniFi controller with made-up devices, for trying the app
and taking screenshots without a real network. Sign in as admin / demo1234 or parent / demo1234.
"""
import random
import time

from . import auth
from .db import DB
from .unifi import Client

# Documentation-range IPs (192.0.2.0/24) and locally-administered MACs: nothing here is real.
_DEVICES = [
    # mac, controller name, vendor, ap, signal, wired, busy
    ("02:00:00:00:01:01", "Galaxy-A15", "Samsung", "Upstairs", -52, False, True),
    ("02:00:00:00:01:02", "Fire-HD-10", "Amazon", "Upstairs", -61, False, False),
    ("02:00:00:00:01:03", "Nintendo Switch", "Nintendo", "Living Room", -58, False, True),
    ("02:00:00:00:01:04", "Chromebook", "Acer", "Upstairs", -55, False, False),
    ("02:00:00:00:01:05", "Roku-Ultra", "Roku", "", None, True, False),
    ("02:00:00:00:02:01", "Pixel-9", "Google", "Living Room", -48, False, True),
    ("02:00:00:00:02:02", "Galaxy-S24", "Samsung", "Living Room", -57, False, False),
    ("02:00:00:00:03:01", "HS200", "TP-Link", "Living Room", -54, False, False),
    ("02:00:00:00:03:02", "HS105", "TP-Link", "Upstairs", -71, False, False),
    ("02:00:00:00:03:03", "Google-Home-Mini", "Google", "Living Room", -63, False, False),
    ("02:00:00:00:04:01", "android-7f3a", "Motorola", "Upstairs", -66, False, True),
]


class DemoUniFi:
    def __init__(self):
        now = int(time.time())
        self.c: dict[str, Client] = {}
        self.busy: set[str] = set()
        for i, (mac, name, oui, ap, sig, wired, busy) in enumerate(_DEVICES):
            first = now - 3600 * 5 if mac.endswith("04:01") else now - 86400 * 60
            self.c[mac] = Client(mac, name, f"192.0.2.{20 + i}", True, wired, False, ap, sig,
                                 random.randint(10**6, 10**8), now, first, oui)
            if busy:
                self.busy.add(mac)

    async def clients(self):
        for mac, c in self.c.items():
            if c.total_bytes is not None and not c.blocked:
                c.total_bytes += random.randint(10**6, 10**7) if mac in self.busy else random.randint(0, 20_000)
            c.online = not c.blocked
            c.last_seen = int(time.time()) if c.online else c.last_seen
        return {k: Client(**vars(v)) for k, v in self.c.items()}

    async def block(self, mac):
        self.c[mac].blocked = True

    async def unblock(self, mac):
        self.c[mac].blocked = False

    async def close(self):
        pass


def seed(db: DB) -> None:
    """Fill an empty database with a family setup."""
    if db.one("SELECT 1 FROM users"):
        return
    admin = auth.create_user(db, "admin", "Alex", "demo1234", "admin")
    auth.create_user(db, "parent", "Sam", "demo1234", "parent")
    kid = db.x("INSERT INTO groups (name) VALUES ('Riley')")
    for mac, label, kind, gid in [
        ("02:00:00:00:01:01", "Riley's phone", "phone", kid),
        ("02:00:00:00:01:02", "Riley's tablet", "tablet", kid),
        ("02:00:00:00:01:03", "Nintendo Switch", "console", kid),
        ("02:00:00:00:01:04", "School Chromebook", "laptop", kid),
        ("02:00:00:00:01:05", "Bedroom TV", "tv", kid),
    ]:
        db.x("INSERT INTO devices (mac, label, kind, group_id) VALUES (?,?,?,?)", (mac, label, kind, gid))
    db.x("INSERT INTO schedules (group_id, days, start, end, label) VALUES (?,?,?,?,?)",
         (kid, "01236", "21:00", "07:00", "Bedtime"))
    db.x("INSERT INTO schedules (group_id, days, start, end, label) VALUES (?,?,?,?,?)",
         (kid, "01234", "15:30", "16:30", "Homework"))
    now = int(time.time())
    for mac, *_rest, busy in _DEVICES:
        for t in range(now - 86400, now, 300):
            hour = time.localtime(t).tm_hour
            awake = 7 <= hour < 21
            b = random.randint(3 * 10**6, 8 * 10**7) if busy and awake and random.random() < 0.5 else random.randint(0, 50_000)
            db.x("INSERT OR IGNORE INTO traffic (mac, ts, bytes) VALUES (?,?,?)", (mac, t, b))
    for dt, actor, action, target in [
        (-86400 + 3600 * 2, "Schedule", "WiFi off — Bedtime", "Riley"),
        (-86400 + 3600 * 12, "Schedule", "WiFi back on", "Riley"),
        (-3600 * 6, "Sam", "Paused WiFi until 5:00 PM", "Riley"),
        (-3600 * 5, "Timer", "WiFi back on", "Riley"),
        (-3600 * 2, "Alex", "Turned WiFi on (while the rest stay off)", "School Chromebook"),
        (-1800, "Alex", "Added device", "Nintendo Switch"),
    ]:
        db.x("INSERT INTO log (ts, user_id, actor, action, target) VALUES (?,?,?,?,?)",
             (now + dt, admin if actor == "Alex" else None, actor, action, target))
