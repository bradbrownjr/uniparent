"""Thin async client for the UniFi Network legacy API on UniFi OS (X-API-KEY auth).

Uses the legacy `/api/s/<site>/...` endpoints because the official integration API has no
block/unblock action. Verified on Network 10.6: `cmd/stamgr` block-sta drops the client within
seconds and normally keeps it from re-associating (see `hidden` for when it doesn't); unblock-sta lets
it straight back on.
"""
from dataclasses import dataclass

import httpx


class UniFiError(RuntimeError):
    pass


@dataclass
class Client:
    mac: str
    name: str            # controller-side name/hostname/vendor, best available
    ip: str
    online: bool
    wired: bool
    blocked: bool
    ap: str              # AP name it is (or was last) connected to
    signal: int | None
    total_bytes: int | None  # cumulative tx+rx for the current association (online only)
    last_seen: int | None
    first_seen: int | None
    oui: str
    hostname: str = ""  # what the device calls itself (DHCP), kept even when UniFi has a name for it


class UniFi:
    def __init__(self, host: str, api_key: str, site: str = "default", verify: bool = False,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(
            base_url=f"{host}/proxy/network/api/s/{site}",
            headers={"X-API-KEY": api_key, "Accept": "application/json"},
            verify=verify, timeout=15, transport=transport)
        # Per AP name: stations the AP itself reports minus clients the controller lists on it, as of the
        # last clients() call. The controller leaves blocked clients out of stat/sta, so a blocked device
        # that got back on (seen right after a block, on the other AP) only shows up here.
        self.hidden: dict[str, int] = {}

    async def close(self):
        await self._http.aclose()

    async def _call(self, method: str, path: str, body: dict | None = None) -> list:
        try:
            r = await self._http.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise UniFiError(f"{method} {path}: {e}") from e
        if r.status_code != 200:
            raise UniFiError(f"{method} {path}: HTTP {r.status_code} {r.text[:200]}")
        data = r.json()
        if data.get("meta", {}).get("rc") != "ok":
            raise UniFiError(f"{method} {path}: {data.get('meta')}")
        return data.get("data", [])

    async def clients(self) -> dict[str, Client]:
        """Every client the controller knows, merged with live association data. Keyed by MAC."""
        devices = await self._call("GET", "/stat/device")
        aps = {d["mac"]: d.get("name") or d["mac"] for d in devices}
        known = await self._call("GET", "/rest/user")
        live = {s["mac"]: s for s in await self._call("GET", "/stat/sta")}
        listed: dict[str, int] = {}
        for s in live.values():
            if s.get("ap_mac") and not s.get("is_wired"):
                listed[s["ap_mac"]] = listed.get(s["ap_mac"], 0) + 1
        self.hidden = {}
        for d in devices:
            n = sum(v.get("num_sta", 0) for v in d.get("vap_table") or []) - listed.get(d["mac"], 0)
            if n > 0:
                self.hidden[aps[d["mac"]]] = n
        out: dict[str, Client] = {}
        for u in known:
            mac = u["mac"].lower()
            s = live.get(u["mac"])
            src = s or u
            out[mac] = Client(
                mac=mac,
                name=src.get("name") or u.get("name") or src.get("hostname") or u.get("hostname") or u.get("oui") or mac,
                ip=(s or {}).get("ip") or u.get("last_ip", ""),
                online=s is not None,
                wired=bool(src.get("is_wired")),
                blocked=bool(u.get("blocked")),
                ap=aps.get((s or {}).get("ap_mac"), "") if s else (u.get("last_uplink_name") or ""),
                signal=(s or {}).get("signal"),
                total_bytes=(s["tx_bytes"] + s["rx_bytes"]) if s and "tx_bytes" in s else None,
                last_seen=src.get("last_seen"),
                first_seen=u.get("first_seen"),
                oui=u.get("oui", ""),
                hostname=src.get("hostname") or u.get("hostname") or "",
            )
        for mac, s in live.items():  # associated but not (yet) in rest/user
            if mac.lower() not in out:
                out[mac.lower()] = Client(mac.lower(), s.get("name") or s.get("hostname") or s.get("oui") or mac,
                                          s.get("ip", ""), True, bool(s.get("is_wired")), False,
                                          aps.get(s.get("ap_mac"), ""), s.get("signal"),
                                          s.get("tx_bytes", 0) + s.get("rx_bytes", 0), s.get("last_seen"),
                                          s.get("first_seen"), s.get("oui", ""), s.get("hostname") or "")
        return out

    async def block(self, mac: str):
        await self._call("POST", "/cmd/stamgr", {"cmd": "block-sta", "mac": mac})

    async def unblock(self, mac: str):
        await self._call("POST", "/cmd/stamgr", {"cmd": "unblock-sta", "mac": mac})
