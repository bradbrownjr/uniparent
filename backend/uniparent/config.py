"""Runtime settings, read once from the environment."""
import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    unifi_host: str = field(default_factory=lambda: os.environ.get("UNIFI_HOST", "").rstrip("/"))
    unifi_api_key: str = field(default_factory=lambda: os.environ.get("UNIFI_API_KEY", ""))
    unifi_site: str = field(default_factory=lambda: os.environ.get("UNIFI_SITE", "default"))
    unifi_verify_tls: bool = field(default_factory=lambda: _bool("UNIFI_VERIFY_TLS", False))
    db_path: str = field(default_factory=lambda: os.environ.get("UNIPARENT_DB", "/data/uniparent.db"))
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo(os.environ.get("TZ", "America/New_York")))
    reconcile_seconds: int = field(default_factory=lambda: int(os.environ.get("RECONCILE_SECONDS", "30")))
    poll_seconds: int = field(default_factory=lambda: int(os.environ.get("POLL_SECONDS", "60")))
    # A device counts as "active" in a poll interval once it moves more than this many bytes.
    active_bytes: int = field(default_factory=lambda: int(os.environ.get("ACTIVE_BYTES", "200000")))
    traffic_days: int = field(default_factory=lambda: int(os.environ.get("TRAFFIC_DAYS", "7")))
    session_days: int = field(default_factory=lambda: int(os.environ.get("SESSION_DAYS", "365")))
    cookie_secure: bool = field(default_factory=lambda: _bool("COOKIE_SECURE", True))
    # Only honour X-Forwarded-For when running behind a trusted reverse proxy.
    trust_proxy: bool = field(default_factory=lambda: _bool("TRUST_PROXY", True))
    background: bool = field(default_factory=lambda: _bool("UNIPARENT_BACKGROUND", True))
    static_dir: str = field(default_factory=lambda: os.environ.get("UNIPARENT_STATIC", "/app/static"))
