import time

import pytest
from fastapi.testclient import TestClient

from uniparent import auth
from uniparent.app import create_app
from uniparent.config import Settings
from uniparent.unifi import Client

KID_PHONE = "aa:00:00:00:00:01"
KID_TABLET = "aa:00:00:00:00:02"
KID_TV = "aa:00:00:00:00:03"      # wired
PLUG = "aa:00:00:00:00:04"


class FakeUniFi:
    """Stands in for the controller: remembers blocks and counts calls."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.down = False
        self.c = {
            KID_PHONE: Client(KID_PHONE, "Galaxy-A15", "192.0.2.10", True, False, False, "Upstairs", -55,
                              1_000_000, 0, 0, "Samsung"),
            KID_TABLET: Client(KID_TABLET, "Fire HD", "192.0.2.11", True, False, False, "Upstairs", -60,
                               5_000, 0, 0, "Amazon"),
            KID_TV: Client(KID_TV, "Roku", "192.0.2.12", True, True, False, "", None, None, 0, 0, "Roku"),
            PLUG: Client(PLUG, "HS200", "192.0.2.13", True, False, False, "Downstairs", -50, 100, 0,
                         int(time.time()) - 3600, "TP-Link"),  # first seen an hour ago = "new"
        }

    async def clients(self):
        if self.down:
            from uniparent.unifi import UniFiError
            raise UniFiError("controller down")
        return {k: Client(**vars(v)) for k, v in self.c.items()}

    async def block(self, mac):
        self.calls.append(("block", mac))
        self.c[mac].blocked = True

    async def unblock(self, mac):
        self.calls.append(("unblock", mac))
        self.c[mac].blocked = False

    async def close(self):
        pass


H = {"X-UniParent": "1"}


@pytest.fixture
def fake():
    return FakeUniFi()


@pytest.fixture
def app(tmp_path, fake):
    s = Settings(db_path=str(tmp_path / "t.db"), background=False, cookie_secure=False,
                 static_dir=str(tmp_path / "nostatic"))
    a = create_app(s, fake)
    auth.create_user(a.state.db, "brad", "Brad", "correct horse", "admin")
    auth.create_user(a.state.db, "amy", "Amy", "battery staple", "parent")
    return a


def login(app, user, pw) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/login", json={"username": user, "password": pw}, headers=H)
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def admin(app):
    with login(app, "brad", "correct horse") as c:
        yield c


@pytest.fixture
def parent(app):
    with login(app, "amy", "battery staple") as c:
        yield c


@pytest.fixture
def kid(admin):
    """A 'Riley' group holding the phone, tablet and wired TV."""
    gid = admin.post("/api/admin/groups", json={"name": "Riley"}, headers=H).json()["id"]
    for mac, label, kind in [(KID_PHONE, "Riley's phone", "phone"), (KID_TABLET, "Riley's tablet", "tablet"),
                             (KID_TV, "Riley's TV", "tv")]:
        r = admin.put(f"/api/admin/devices/{mac}", json={"label": label, "kind": kind, "group_id": gid}, headers=H)
        assert r.status_code == 200, r.text
    return gid
