"""账号登录、跨设备稳定归属、Cookie/CSRF 与邀请兼容，无模型调用。"""
import json
import sqlite3

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from app.infrastructure.account_access import AccountAccessStore, AccountRateLimit, ACCOUNT_COOKIE, LOCAL_ACCOUNT_COOKIE
from app.infrastructure.identity import IdentityError, IdentityPolicy
from app.infrastructure.invite_access import InviteAccessStore
from app.infrastructure.persistence.json_file_stores import JsonFileSessionStore
from app.presentation.identity import register_identity_routes, require_buyer, require_session

ORIGIN = "https://demo.example"
PASSWORD = "correct-password-for-test"


def app_for(tmp_path, clock=None):
    api = FastAPI()
    api.state.identity_policy = IdentityPolicy(mode="hmac", secret="synthetic-account-secret-" * 3)
    api.state.account_access = AccountAccessStore(tmp_path / "accounts.db", **({"clock": clock} if clock else {}))
    api.state.invite_access = InviteAccessStore(tmp_path / "invites.db")
    api.state.account_origins = [ORIGIN, "http://localhost:5173"]
    api.state.session_store = JsonFileSessionStore(tmp_path / "sessions")
    register_identity_routes(api)

    @api.post("/private")
    async def private(request: Request, buyer_id: str, session_id: str, create: bool = False):
        await require_buyer(request, buyer_id)
        await require_session(request, buyer_id, session_id, create=create)
        return {"ok": True}

    return api


def register(client, username="alice", name="小爱", origin=ORIGIN):
    return client.post("/commerce/auth/register", json={"username": username, "password": PASSWORD, "display_name": name}, headers={"Origin": origin})


def login(client, username="alice", password=PASSWORD, origin=ORIGIN):
    return client.post("/commerce/auth/login", json={"username": username, "password": password}, headers={"Origin": origin})


def test_password_and_session_not_stored_plaintext_and_survive_restart(tmp_path):
    path = tmp_path / "accounts.db"
    store = AccountAccessStore(path)
    cookie, account = store.register("Alice", PASSWORD, "小爱", ORIGIN)
    other_cookie, other = AccountAccessStore(path).login("ALICE", PASSWORD, ORIGIN)
    assert other.buyer_id == account.buyer_id and other.display_name == "小爱"
    assert other_cookie != cookie
    assert PASSWORD.encode() not in path.read_bytes() and cookie.encode() not in path.read_bytes()
    with sqlite3.connect(path) as db:
        salt, digest = db.execute("SELECT password_salt,password_hash FROM accounts").fetchone()
        assert len(salt) == 16 and len(digest) == 32
    with pytest.raises(IdentityError):
        store.login("alice", "wrong-password-long", ORIGIN)
    with pytest.raises(ValueError):
        store.register("ALICE", PASSWORD, "另一个昵称", ORIGIN)


def test_http_cross_device_stable_identity_and_two_account_isolation(tmp_path):
    api = app_for(tmp_path)
    with TestClient(api, base_url=ORIGIN) as a, TestClient(api, base_url=ORIGIN) as b, TestClient(api, base_url=ORIGIN) as other_device:
        response = register(a)
        assert response.status_code == 200
        buyer = response.json()["buyer_id"]
        assert response.json()["display_name"] == "小爱"
        assert PASSWORD not in response.text and "token" not in response.text
        cookie = response.headers.get_list("set-cookie")[-1]
        assert ACCOUNT_COOKIE in cookie and "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie and "Domain=" not in cookie
        assert a.post(f"/private?buyer_id={buyer}&session_id=alice-chat&create=true", headers={"Origin": ORIGIN}).status_code == 200
        second = register(b, "bob", "小波").json()
        assert second["buyer_id"] != buyer
        assert b.post(f"/private?buyer_id={buyer}&session_id=alice-chat", headers={"Origin": ORIGIN}).status_code == 403
        assert b.post(f"/private?buyer_id={second['buyer_id']}&session_id=alice-chat", headers={"Origin": ORIGIN}).status_code == 403
        assert login(other_device).json()["buyer_id"] == buyer
        assert other_device.post(f"/private?buyer_id={buyer}&session_id=alice-chat", headers={"Origin": ORIGIN}).status_code == 200
        assert other_device.get("/commerce/auth").json()["display_name"] == "小爱"


def test_logout_revokes_replayed_cookie_but_preserves_other_device(tmp_path):
    api = app_for(tmp_path)
    with TestClient(api, base_url=ORIGIN) as a, TestClient(api, base_url=ORIGIN) as b:
        register(a)
        login(b)
        cookie = a.cookies.get(ACCOUNT_COOKIE)
        assert a.post("/commerce/auth/logout", headers={"Origin": ORIGIN}).status_code == 200
        a.cookies.set(ACCOUNT_COOKIE, cookie)
        assert a.get("/commerce/auth").status_code == 401
        assert b.get("/commerce/auth").json()["authenticated"]


def test_expiry_disabled_account_and_persistent_throttle(tmp_path):
    now = [1000]
    store = AccountAccessStore(tmp_path / "accounts.db", clock=lambda: now[0])
    cookie, session = store.register("alice", PASSWORD, "小爱", ORIGIN)
    now[0] = session.expires_at
    with pytest.raises(IdentityError):
        store.resolve(cookie)
    for _ in range(10):
        store.throttle("login", "alice")
    with pytest.raises(AccountRateLimit):
        AccountAccessStore(store.path, clock=lambda: now[0]).login("alice", PASSWORD, ORIGIN)
    now[0] += 901
    cookie, _ = store.login("alice", PASSWORD, ORIGIN)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE accounts SET disabled=1")
    with pytest.raises(IdentityError):
        store.resolve(cookie)
    with pytest.raises(IdentityError):
        store.login("alice", PASSWORD, ORIGIN)


@pytest.mark.parametrize("origin", ["https://evil.example", "http://demo.example", "", "null"])
def test_account_endpoints_reject_cross_site_and_insecure_origins(tmp_path, origin):
    with TestClient(app_for(tmp_path), base_url=ORIGIN) as client:
        assert register(client, origin=origin).status_code == 403
        assert login(client, origin=origin).status_code == 403


def test_csrf_bearer_precedence_and_invitation_does_not_replace_account(tmp_path):
    api = app_for(tmp_path)
    with TestClient(api, base_url=ORIGIN) as client:
        buyer = register(client).json()["buyer_id"]
        assert client.post("/commerce/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/commerce/auth", headers={"Authorization": "Bearer invalid"}).status_code == 401
        _, token = api.state.invite_access.create(ORIGIN)
        response = client.post("/commerce/auth/invite", json={"invite": token}, headers={"Origin": ORIGIN})
        assert response.json()["credential"] == "account" and response.json()["buyer_id"] == buyer
        assert client.post(f"/private?buyer_id={buyer}&session_id=test&create=true", headers={"Origin": "https://evil.example"}).status_code == 403


def test_loopback_cookie_and_password_validation_do_not_echo_secrets(tmp_path):
    api = app_for(tmp_path)
    origin = "http://localhost:5173"
    with TestClient(api, base_url=origin) as client:
        assert register(client, origin=origin).status_code == 200
        assert client.cookies.get(LOCAL_ACCOUNT_COOKIE)
        assert client.get("/commerce/auth").json()["credential"] == "account"
        assert login(client, "missing", "wrong-password-long", origin).status_code == 401
        response = client.post("/commerce/auth/login", json={"username": "alice", "password": "secret", "extra": "sensitive"}, headers={"Origin": origin})
        assert response.status_code == 400 and "secret" not in response.text and "sensitive" not in response.text
        response = client.post("/commerce/auth/register", json={"username": "bad!", "password": PASSWORD, "display_name": "小爱"}, headers={"Origin": origin})
        assert response.status_code == 400 and PASSWORD not in response.text
        response = client.post("/commerce/auth/register", content="x" * 3000, headers={"Origin": origin})
        assert response.status_code == 400


def test_old_invite_remains_usable_alongside_accounts(tmp_path):
    api = app_for(tmp_path)
    with TestClient(api, base_url=ORIGIN) as client:
        _, token = api.state.invite_access.create(ORIGIN)
        assert client.post("/commerce/auth/invite", json={"invite": token}, headers={"Origin": ORIGIN}).status_code == 200
        status = client.get("/commerce/auth").json()
        assert status["credential"] == "invite" and status["display_name"] == "体验访客"
        guest = status["buyer_id"]
        assert register(client).json()["buyer_id"] != guest
        assert client.get("/commerce/auth").json()["credential"] == "account"


def test_expired_account_cookie_can_return_to_invite_experience(tmp_path):
    now = [1000]
    api = app_for(tmp_path, clock=lambda: now[0])
    with TestClient(api, base_url=ORIGIN) as client:
        register(client)
        now[0] += 8 * 86400
        _, token = api.state.invite_access.create(ORIGIN)
        assert client.post("/commerce/auth/invite", json={"invite": token}, headers={"Origin": ORIGIN}).status_code == 200
        assert client.get("/commerce/auth").json()["credential"] == "invite"
