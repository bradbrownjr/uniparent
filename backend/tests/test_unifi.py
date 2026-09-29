import asyncio
import json

import httpx
import pytest

from uniparent.unifi import UniFi, UniFiError

AP = "e0:00:00:00:00:01"
DEVICES = [{"mac": AP, "name": "Living Room"}]
USERS = [
    {"mac": "aa:00:00:00:00:01", "name": "Kitchen phone", "hostname": "Galaxy-A15", "oui": "Samsung", "last_ip": "192.0.2.10",
     "first_seen": 100, "last_seen": 200},
    {"mac": "aa:00:00:00:00:02", "oui": "TP-Link", "blocked": True, "last_uplink_name": "Living Room",
     "last_ip": "192.0.2.11", "first_seen": 50, "last_seen": 60},
]
STA = [
    {"mac": "aa:00:00:00:00:01", "hostname": "Galaxy-A15", "ip": "192.0.2.10", "ap_mac": AP, "signal": -55,
     "tx_bytes": 10, "rx_bytes": 5, "last_seen": 300, "is_wired": False},
    {"mac": "AA:00:00:00:00:09", "oui": "Roku", "ip": "192.0.2.12", "is_wired": True, "tx_bytes": 1,
     "rx_bytes": 1},
]


def transport(seen: list):
    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, req.headers.get("x-api-key"),
                     json.loads(req.content) if req.content else None))
        path = req.url.path.removeprefix("/proxy/network/api/s/default")
        data = {"/stat/device": DEVICES, "/rest/user": USERS, "/stat/sta": STA, "/cmd/stamgr": []}.get(path)
        if data is None:
            return httpx.Response(404, json={"meta": {"rc": "error"}})
        return httpx.Response(200, json={"meta": {"rc": "ok"}, "data": data})
    return httpx.MockTransport(handler)


def test_clients_merge():
    seen = []
    u = UniFi("https://ctrl.example", "KEY", transport=transport(seen))
    c = asyncio.run(u.clients())
    phone, plug, roku = c["aa:00:00:00:00:01"], c["aa:00:00:00:00:02"], c["aa:00:00:00:00:09"]
    assert phone.online and phone.ap == "Living Room" and phone.total_bytes == 15 and phone.signal == -55
    assert not plug.online and plug.blocked and plug.ap == "Living Room" and plug.name == "TP-Link"
    assert phone.name == "Kitchen phone" and phone.hostname == "Galaxy-A15"  # UniFi name wins, hostname kept
    assert roku.online and roku.wired and plug.hostname == ""
    assert all(k == "KEY" for _, _, k, _ in seen)


def test_block_body():
    seen = []
    u = UniFi("https://ctrl.example", "KEY", transport=transport(seen))
    asyncio.run(u.block("aa:00:00:00:00:01"))
    asyncio.run(u.unblock("aa:00:00:00:00:01"))
    assert [s[3]["cmd"] for s in seen] == ["block-sta", "unblock-sta"]
    assert seen[0][1] == "/proxy/network/api/s/default/cmd/stamgr"


def test_errors():
    u = UniFi("https://ctrl.example", "KEY", site="nope", transport=transport([]))
    with pytest.raises(UniFiError):
        asyncio.run(u.clients())
