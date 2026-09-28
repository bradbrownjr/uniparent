"""Users, password hashing, long-lived sessions and a simple login rate limit."""
import hashlib
import secrets
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .db import DB

COOKIE = "uniparent_session"
ROLES = ("admin", "parent")

_ph = PasswordHasher()
# Hash of a random string, verified against when the username doesn't exist so timing doesn't reveal it.
_DUMMY = _ph.hash(secrets.token_hex(16))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(db: DB, username: str, display_name: str, password: str, role: str) -> int:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    return db.x("INSERT INTO users (username, display_name, password_hash, role, created) VALUES (?,?,?,?,?)",
                (username.strip(), display_name.strip() or username.strip(), _ph.hash(password), role,
                 int(time.time())))


def set_password(db: DB, user_id: int, password: str) -> None:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    db.x("UPDATE users SET password_hash=? WHERE id=?", (_ph.hash(password), user_id))
    db.x("DELETE FROM sessions WHERE user_id=?", (user_id,))


def check_password(db: DB, username: str, password: str):
    u = db.one("SELECT * FROM users WHERE username=?", (username.strip(),))
    try:
        _ph.verify(u["password_hash"] if u else _DUMMY, password)
    except (VerificationError, InvalidHashError):
        return None
    if u is None:
        return None
    if _ph.check_needs_rehash(u["password_hash"]):
        db.x("UPDATE users SET password_hash=? WHERE id=?", (_ph.hash(password), u["id"]))
    return u


def new_session(db: DB, user_id: int, days: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.x("INSERT INTO sessions (token_hash, user_id, created, expires) VALUES (?,?,?,?)",
         (_token_hash(token), user_id, now, now + days * 86400))
    db.x("DELETE FROM sessions WHERE expires < ?", (now,))
    return token


def session_user(db: DB, token: str | None):
    if not token:
        return None
    return db.one("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                  "WHERE s.token_hash=? AND s.expires > ?", (_token_hash(token), int(time.time())))


def end_session(db: DB, token: str | None) -> None:
    if token:
        db.x("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


class RateLimit:
    """At most `limit` failed logins per key in `window` seconds."""

    def __init__(self, limit: int = 5, window: int = 900):
        self.limit, self.window = limit, window
        self.fails: dict[str, deque] = defaultdict(deque)

    def _trim(self, key: str, now: float):
        q = self.fails[key]
        while q and q[0] < now - self.window:
            q.popleft()

    def blocked(self, key: str) -> bool:
        self._trim(key, time.time())
        return len(self.fails[key]) >= self.limit

    def fail(self, key: str) -> None:
        self.fails[key].append(time.time())

    def reset(self, key: str) -> None:
        self.fails.pop(key, None)
