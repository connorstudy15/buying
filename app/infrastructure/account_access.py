"""账号及可撤销浏览器会话；密码仅存加盐 PBKDF2，数据归属使用稳定 buyer_id。"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import time

from app.infrastructure.identity import IdentityError
from app.infrastructure.invite_access import normalize_origin

ACCOUNT_COOKIE = "__Host-ezbuying_account"
LOCAL_ACCOUNT_COOKIE = "ezbuying_account"
ITERATIONS = 600_000
SESSION_SECONDS = 7 * 86400
_USERNAME = re.compile(r"[a-z0-9][a-z0-9_.-]{2,31}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class AccountRateLimit(IdentityError):
    pass


@dataclass(frozen=True)
class AccountSession:
    buyer_id: str
    username: str
    display_name: str
    origin: str
    expires_at: int


def normalize_username(value: str) -> str:
    value = value.strip().lower()
    if not _USERNAME.fullmatch(value):
        raise ValueError("账号需为 3–32 位英文字母、数字、下划线、点或短横线，以字母或数字开头")
    return value


def validate_password(value: str) -> None:
    if not 6 <= len(value) <= 12:
        raise ValueError("密码需为 6–12 个字符")


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)


def _digest(token: str) -> str:
    if not _TOKEN.fullmatch(token):
        raise IdentityError("账号登录已失效，请重新登录")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class AccountAccessStore:
    def __init__(self, path: Path, *, clock=time.time):
        self.path, self.clock = path, clock
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    buyer_id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL, password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL, created_at INTEGER NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS account_sessions (
                    token_hash TEXT PRIMARY KEY, buyer_id TEXT NOT NULL,
                    origin TEXT NOT NULL, expires_at INTEGER NOT NULL,
                    FOREIGN KEY(buyer_id) REFERENCES accounts(buyer_id)
                );
                CREATE TABLE IF NOT EXISTS account_attempts (
                    bucket TEXT PRIMARY KEY, started_at INTEGER NOT NULL, attempts INTEGER NOT NULL
                );
            """)
        path.chmod(0o600)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def throttle(self, action: str, username: str) -> None:
        """持久计数，跨 worker/重启生效；账号与全局配额共同限制昂贵密码运算。"""
        now = int(self.clock())
        limit = 20 if action == "register" else 120
        buckets = [(action + ":global", limit)]
        if action == "login":
            buckets.append(("login:" + hashlib.sha256(username.encode()).hexdigest(), 10))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM account_attempts WHERE started_at<=?", (now - 900,))
            for bucket, maximum in buckets:
                row = db.execute("SELECT attempts FROM account_attempts WHERE bucket=?", (bucket,)).fetchone()
                if row and row[0] >= maximum:
                    raise AccountRateLimit("尝试过于频繁，请在 15 分钟后重试")
            for bucket, _ in buckets:
                db.execute("INSERT INTO account_attempts VALUES (?, ?, 1) ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1", (bucket, now))

    def register(self, username: str, password: str, display_name: str, origin: str):
        username = normalize_username(username)
        validate_password(password)
        display_name = display_name.strip() or username
        if len(display_name) > 32 or any(ord(c) < 32 for c in display_name):
            raise ValueError("昵称需为 1–32 个字符，不含控制字符")
        origin = normalize_origin(origin)
        self.throttle("register", username)
        salt, buyer_id = secrets.token_bytes(16), "account-" + secrets.token_hex(16)
        digest = _hash(password, salt)
        try:
            with self._db() as db:
                db.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?, 0)",
                           (buyer_id, username, display_name, salt, digest, int(self.clock())))
                return self._issue(db, buyer_id, username, display_name, origin)
        except sqlite3.IntegrityError:
            raise ValueError("该账号不可用，请换一个账号名") from None

    def login(self, username: str, password: str, origin: str):
        username = normalize_username(username)
        # 允许旧账号继续使用此前注册的较长密码。
        if not 1 <= len(password) <= 128 or len(password.encode("utf-8")) > 512:
            raise ValueError("密码格式不正确")
        origin = normalize_origin(origin)
        self.throttle("login", username)
        with self._db() as db:
            row = db.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
        # 未找到账号也执行同等密码运算，避免明显的账号枚举时序差异。
        actual = _hash(password, bytes(row["password_salt"]) if row else b"\0" * 16)
        expected = bytes(row["password_hash"]) if row else b"\0" * 32
        if not hmac.compare_digest(actual, expected) or row is None or row["disabled"]:
            raise IdentityError("账号或密码不正确")
        with self._db() as db:
            return self._issue(db, row["buyer_id"], row["username"], row["display_name"], origin)

    def _issue(self, db, buyer_id, username, display_name, origin):
        now = int(self.clock())
        db.execute("DELETE FROM account_sessions WHERE expires_at<=?", (now,))
        cookie = secrets.token_urlsafe(32)
        session = AccountSession(buyer_id, username, display_name, origin, now + SESSION_SECONDS)
        db.execute("INSERT INTO account_sessions VALUES (?, ?, ?, ?)",
                   (_digest(cookie), buyer_id, origin, session.expires_at))
        return cookie, session

    def resolve(self, cookie: str) -> AccountSession:
        with self._db() as db:
            row = db.execute("""SELECT a.buyer_id, a.username, a.display_name, s.origin, s.expires_at
                FROM account_sessions s JOIN accounts a ON a.buyer_id=s.buyer_id
                WHERE s.token_hash=? AND s.expires_at>? AND a.disabled=0""",
                             (_digest(cookie), int(self.clock()))).fetchone()
        if row is None:
            raise IdentityError("账号登录已失效，请重新登录")
        return AccountSession(**dict(row))

    def logout(self, cookie: str) -> None:
        try:
            digest = _digest(cookie)
        except IdentityError:
            return
        with self._db() as db:
            db.execute("DELETE FROM account_sessions WHERE token_hash=?", (digest,))
