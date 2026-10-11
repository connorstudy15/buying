"""共享邀请入口与独立浏览器登录；仅存随机凭证哈希，撤销对后续请求生效。"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Callable
from urllib.parse import urlsplit

from app.infrastructure.identity import IdentityError

COOKIE_NAME = "__Host-globex_invite_session"
LOCAL_COOKIE_NAME = "globex_invite_session"
_CAPABILITY = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class InviteOriginError(IdentityError):
    pass


def normalize_origin(value: str) -> str:
    """公开入口要求 HTTPS；HTTP 仅供明确的本机回环开发入口。"""
    try:
        url = urlsplit(value)
        port = url.port
        if port is not None and port < 1:
            raise ValueError
        if (not url.hostname or url.username or url.password or url.path not in ("", "/")
                or url.query or url.fragment or url.scheme not in ("http", "https")):
            raise ValueError
        if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError
        host = f"[{url.hostname}]" if ":" in url.hostname else url.hostname
        return f"{url.scheme}://{host}" + (f":{port}" if port and port != (443 if url.scheme == "https" else 80) else "")
    except (ValueError, TypeError):
        raise ValueError("邀请入口必须是 HTTPS 域名源地址；HTTP 仅允许本机 localhost/回环地址") from None


def _digest(value: str) -> str:
    if not isinstance(value, str) or not _CAPABILITY.fullmatch(value):
        raise IdentityError("邀请或体验登录无效、已过期或已撤销")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class InviteSession:
    buyer_id: str
    invite_id: str
    origin: str
    expires_at: int


class InviteAccessStore:
    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time):
        self.path, self.clock = path, clock
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS shared_invites (
                    invite_id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                    origin TEXT NOT NULL, expires_at INTEGER NOT NULL,
                    session_seconds INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS invite_sessions (
                    session_hash TEXT PRIMARY KEY, invite_id TEXT NOT NULL,
                    buyer_id TEXT NOT NULL, expires_at INTEGER NOT NULL,
                    FOREIGN KEY(invite_id) REFERENCES shared_invites(invite_id)
                );
                CREATE INDEX IF NOT EXISTS invite_session_parent ON invite_sessions(invite_id);
            """)
        path.chmod(0o600)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, origin: str, *, ttl_seconds: int = 7 * 86400, session_seconds: int = 86400) -> tuple[str, str]:
        origin = normalize_origin(origin)
        if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 90 * 86400:
            raise ValueError("邀请有效期必须为 60 秒至 90 天")
        if type(session_seconds) is not int or not 60 <= session_seconds <= 7 * 86400:
            raise ValueError("体验登录有效期必须为 60 秒至 7 天")
        invite_id, token = secrets.token_hex(12), secrets.token_urlsafe(32)
        with self._db() as db:
            db.execute("INSERT INTO shared_invites VALUES (?, ?, ?, ?, ?, 0)",
                       (invite_id, _digest(token), origin, int(self.clock()) + ttl_seconds, session_seconds))
        return invite_id, token

    def revoke(self, invite_id: str) -> bool:
        with self._db() as db:
            return bool(db.execute("UPDATE shared_invites SET revoked=1 WHERE invite_id=?", (invite_id,)).rowcount)

    def list_invites(self) -> list[dict]:
        with self._db() as db:
            return [dict(row) for row in db.execute(
                "SELECT invite_id, origin, expires_at, session_seconds, revoked FROM shared_invites ORDER BY expires_at DESC")]

    def _resolve(self, db, cookie: str) -> InviteSession:
        now = int(self.clock())
        row = db.execute("""SELECT s.buyer_id, s.invite_id, i.origin, s.expires_at
            FROM invite_sessions s JOIN shared_invites i ON i.invite_id=s.invite_id
            WHERE s.session_hash=? AND s.expires_at>? AND i.expires_at>? AND i.revoked=0""",
                         (_digest(cookie), now, now)).fetchone()
        if row is None:
            raise IdentityError("邀请或体验登录无效、已过期或已撤销")
        return InviteSession(**dict(row))

    def resolve(self, cookie: str) -> InviteSession:
        with self._db() as db:
            return self._resolve(db, cookie)

    def exchange(self, token: str, origin: str, existing_cookie: str = "") -> tuple[str, InviteSession]:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            now = int(self.clock())
            invite = db.execute("SELECT * FROM shared_invites WHERE token_hash=? AND revoked=0 AND expires_at>?",
                                (_digest(token), now)).fetchone()
            if invite is None:
                raise IdentityError("邀请或体验登录无效、已过期或已撤销")
            if origin != invite["origin"]:
                raise InviteOriginError("邀请入口来源不匹配")
            if existing_cookie:
                try:
                    current = self._resolve(db, existing_cookie)
                    if current.invite_id == invite["invite_id"]:
                        return existing_cookie, current
                except IdentityError:
                    pass
            cookie = secrets.token_urlsafe(32)
            session = InviteSession("guest-" + secrets.token_hex(16), invite["invite_id"], invite["origin"],
                                    min(now + invite["session_seconds"], invite["expires_at"]))
            db.execute("INSERT INTO invite_sessions VALUES (?, ?, ?, ?)",
                       (_digest(cookie), session.invite_id, session.buyer_id, session.expires_at))
            return cookie, session

    def logout(self, cookie: str) -> None:
        try:
            key = _digest(cookie)
        except IdentityError:
            return
        with self._db() as db:
            db.execute("DELETE FROM invite_sessions WHERE session_hash=?", (key,))
