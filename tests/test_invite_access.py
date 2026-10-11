"""共享邀请不共享身份；验证 HTTP/WS、持久撤销及跨站防护，无外部模型调用。"""
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace

from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
import httpx
import pytest
from starlette.websockets import WebSocketDisconnect

from app.infrastructure.eventbus import TradeEventBus, TradeEvent
from app.infrastructure.identity import IdentityError, IdentityPolicy
from app.infrastructure.invite_access import COOKIE_NAME, LOCAL_COOKIE_NAME, InviteAccessStore, normalize_origin
from app.infrastructure.persistence.json_file_stores import JsonFileSessionStore
from app.presentation.connection import ConnectionManager
from app.presentation.identity import register_identity_routes, require_buyer, require_session

ORIGIN = "https://demo.example"
POLICY = IdentityPolicy(mode="hmac", secret="synthetic-invite-secret-" * 3)


def invite_app(tmp_path, clock=None):
    api = FastAPI()
    api.state.identity_policy = POLICY
    api.state.invite_access = InviteAccessStore(tmp_path / "invite.db", **({"clock": clock} if clock else {}))
    api.state.session_store = JsonFileSessionStore(tmp_path / "sessions")
    register_identity_routes(api)

    @api.get("/commerce/private")
    async def private(request: Request, buyer_id: str):
        return {"buyer_id": await require_buyer(request, buyer_id)}

    @api.post("/commerce/private")
    async def write(request: Request, buyer_id: str, session_id: str):
        await require_buyer(request, buyer_id)
        await require_session(request, buyer_id, session_id, create=True)
        return {"ok": True}

    class ReadyBus(TradeEventBus):
        def subscribe(self, session_id):
            queue = super().subscribe(session_id)
            queue.put_nowait(TradeEvent(session_id, "test.ready", {}, "now"))
            return queue
    manager = ConnectionManager(ReadyBus())
    @api.websocket("/commerce/events")
    async def events(websocket: WebSocket):
        await manager.serve(websocket)
    return api


def test_store_hashes_capabilities_reuses_browser_and_revokes_across_instances(tmp_path):
    now = [1000]
    store = InviteAccessStore(tmp_path / "invite.db", clock=lambda: now[0])
    invite_id, token = store.create(ORIGIN, ttl_seconds=120, session_seconds=90)
    cookie, first = store.exchange(token, ORIGIN)
    assert store.exchange(token, ORIGIN, cookie) == (cookie, first)
    second_cookie, second = store.exchange(token, ORIGIN)
    assert second.buyer_id != first.buyer_id
    assert token not in json.dumps(store.list_invites())
    assert token.encode() not in store.path.read_bytes() and cookie.encode() not in store.path.read_bytes()
    assert first.expires_at == 1090
    with pytest.raises(IdentityError):
        store.exchange(token, "https://other.example")
    another = InviteAccessStore(store.path, clock=lambda: now[0])
    assert another.resolve(cookie) == first
    assert another.revoke(invite_id)
    for value in (cookie, second_cookie):
        with pytest.raises(IdentityError):
            store.resolve(value)
    with pytest.raises(IdentityError):
        store.exchange(token, ORIGIN)


def test_shared_link_can_create_five_independent_logins_concurrently(tmp_path):
    store = InviteAccessStore(tmp_path / "invite.db")
    _, token = store.create(ORIGIN)
    with ThreadPoolExecutor(max_workers=5) as pool:
        sessions = list(pool.map(lambda _: store.exchange(token, ORIGIN), range(5)))
    assert len({session.buyer_id for _, session in sessions}) == 5
    assert len({cookie for cookie, _ in sessions}) == 5


def test_expiry_logout_and_invalid_capability_fail_closed(tmp_path):
    now = [1000]
    store = InviteAccessStore(tmp_path / "invite.db", clock=lambda: now[0])
    _, token = store.create(ORIGIN, ttl_seconds=60, session_seconds=120)
    cookie, session = store.exchange(token, ORIGIN)
    assert session.expires_at == 1060
    store.logout(cookie)
    with pytest.raises(IdentityError):
        store.resolve(cookie)
    cookie, _ = store.exchange(token, ORIGIN)
    now[0] = 1060
    with pytest.raises(IdentityError):
        store.resolve(cookie)
    with pytest.raises(IdentityError):
        store.exchange(token, ORIGIN)
    for bad in ("", "x" * 10000, "!" * 43):
        with pytest.raises(IdentityError):
            store.resolve(bad)


@pytest.mark.parametrize("origin", ["http://public.example", "https://user:pass@demo.example", "https://demo.example/demo", "https://demo.example#token", "file:///tmp"])
def test_public_invite_origin_must_be_unambiguous_https(origin):
    with pytest.raises(ValueError):
        normalize_origin(origin)


@pytest.mark.asyncio
async def test_cookie_login_isolated_and_existing_bearer_login_preserved(tmp_path):
    api = invite_app(tmp_path)
    invite_id, token = api.state.invite_access.create(ORIGIN)
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as a, httpx.AsyncClient(transport=transport, base_url=ORIGIN) as b:
        response = await a.post("/commerce/auth/invite", json={"invite": token}, headers={"Origin": ORIGIN})
        assert response.status_code == 200
        assert token not in response.text and "access_token" not in response.text
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(COOKIE_NAME + "=") and "Domain=" not in cookie
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie and "Path=/;" in cookie
        buyer_a = response.json()["buyer_id"]
        assert (await a.get("/commerce/auth")).json()["buyer_id"] == buyer_a
        assert (await a.post("/commerce/auth/invite", json={"invite": token}, headers={"Origin": ORIGIN})).json()["buyer_id"] == buyer_a
        buyer_b = (await b.post("/commerce/auth/invite", json={"invite": token}, headers={"Origin": ORIGIN})).json()["buyer_id"]
        assert buyer_a != buyer_b
        assert (await a.get("/commerce/private", params={"buyer_id": buyer_b})).status_code == 403
        params = {"buyer_id": buyer_a, "session_id": "one-private-session"}
        assert (await a.post("/commerce/private", params=params, headers={"Origin": ORIGIN})).status_code == 200
        assert (await b.post("/commerce/private", params={**params, "buyer_id": buyer_b}, headers={"Origin": ORIGIN})).status_code == 403
        for origin in ("https://evil.example", "null", ""):
            headers = {"Origin": origin} if origin else {}
            assert (await a.post("/commerce/private", params=params, headers=headers)).status_code == 403
        assert (await a.get("/commerce/private", params={"buyer_id": buyer_a}, headers={"Origin": "https://evil.example"})).status_code == 403
        # 显式的坏 Bearer 不能降级为浏览器 Cookie；个人管理员 Bearer 仍可用。
        assert (await a.get("/commerce/auth", headers={"Authorization": "Bearer invalid"})).status_code == 401
        assert (await a.get("/commerce/auth", headers={"Authorization": "Bearer " + POLICY.issue("operator")})).json()["buyer_id"] == "operator"
        saved = a.cookies.get(COOKIE_NAME)
        a.cookies.clear()
        a.cookies.set(LOCAL_COOKIE_NAME, saved)
        assert (await a.get("/commerce/auth")).status_code == 401
        a.cookies.clear()
        assert (await a.get("/commerce/auth")).json()["authenticated"] is False
        api.state.invite_access.revoke(invite_id)
        assert (await b.get("/commerce/auth")).status_code == 401
        assert (await b.get("/commerce/private", params={"buyer_id": buyer_b})).status_code == 401


@pytest.mark.asyncio
async def test_invite_errors_never_echo_capability_and_logout_revokes_session(tmp_path):
    api = invite_app(tmp_path)
    _, token = api.state.invite_access.create(ORIGIN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url=ORIGIN) as client:
        for origin in ("https://evil.example", "null", ""):
            response = await client.post("/commerce/auth/invite", json={"invite": token}, headers={"Origin": origin})
            assert response.status_code == 403 and token not in response.text
        for body in ({"invite": token + "private"}, {"invite": token, "buyer_id": "operator"}, {"invite": token * 50}, []):
            response = await client.post("/commerce/auth/invite", json=body, headers={"Origin": ORIGIN})
            assert response.status_code in (400, 401) and token not in response.text
        response = await client.post("/commerce/auth/invite", json={"invite": token}, headers={"Origin": ORIGIN})
        saved = client.cookies.get(COOKIE_NAME)
        buyer = response.json()["buyer_id"]
        assert (await client.post("/commerce/auth/logout", headers={"Origin": "https://evil.example"})).status_code == 403
        assert (await client.post("/commerce/auth/logout", headers={"Origin": ORIGIN})).status_code == 200
        assert client.cookies.get(COOKIE_NAME) is None
        client.cookies.set(COOKIE_NAME, saved)
        assert (await client.get("/commerce/private", params={"buyer_id": buyer})).status_code == 401


@pytest.mark.asyncio
async def test_http_cookie_only_allowed_on_local_development_origin(tmp_path):
    api = invite_app(tmp_path)
    _, token = api.state.invite_access.create("http://localhost:5173")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://localhost:5173") as client:
        response = await client.post("/commerce/auth/invite", json={"invite": token}, headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200 and "Secure" not in response.headers["set-cookie"]
        assert response.headers["set-cookie"].startswith(LOCAL_COOKIE_NAME + "=")
        assert (await client.get("/commerce/auth")).json()["authenticated"] is True


def test_cookie_websocket_origin_and_live_revocation(tmp_path, monkeypatch):
    from app.presentation import connection
    monkeypatch.setattr(connection, "AUTH_RECHECK_SECONDS", 0.01)
    api = invite_app(tmp_path)
    invite_id, token = api.state.invite_access.create(ORIGIN)
    with TestClient(api, base_url=ORIGIN) as client:
        buyer = client.post("/commerce/auth/invite", json={"invite": token}, headers={"Origin": ORIGIN}).json()["buyer_id"]
        with client.websocket_connect(ORIGIN.replace("https://", "wss://") + "/commerce/events", headers={"Origin": "https://evil.example"}) as ws:
            ws.send_json({"buyer_id": buyer, "shopping_session_id": "private"})
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == 4403
        with client.websocket_connect(ORIGIN.replace("https://", "wss://") + "/commerce/events", headers={"Origin": ORIGIN}) as ws:
            ws.send_json({"buyer_id": buyer, "shopping_session_id": "private"})
            assert ws.receive_json()["type"] == "test.ready"
            api.state.invite_access.revoke(invite_id)
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == 4401


def test_operator_command_saves_link_only_in_exclusive_file_and_lists_no_capability(tmp_path, monkeypatch, capsys):
    from scripts import manage_invites
    monkeypatch.setattr(manage_invites, "load_settings", lambda **_: SimpleNamespace(
        data_dir=tmp_path, identity_mode="hmac", identity_hmac_secret=POLICY.secret, session_owner_binding=True))
    link_file = tmp_path / "shared-link.txt"
    args = ["manage_invites", "create", "--origin", ORIGIN, "--days", "1", "--output", str(link_file)]
    monkeypatch.setattr("sys.argv", args)
    manage_invites.main()
    result = json.loads(capsys.readouterr().out)
    link = link_file.read_text(encoding="utf-8").strip()
    assert link.startswith(ORIGIN + "/demo#invite=")
    token = link.split("#invite=")[1]
    assert token not in json.dumps(result)
    with pytest.raises(FileExistsError):
        manage_invites.main()
    assert link_file.read_text(encoding="utf-8").strip() == link
    monkeypatch.setattr("sys.argv", ["manage_invites", "list"])
    manage_invites.main()
    assert token not in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["manage_invites", "revoke", "--invite-id", result["invite_id"]])
    manage_invites.main()
    with pytest.raises(IdentityError):
        InviteAccessStore(tmp_path / "invite_access.db").exchange(token, ORIGIN)
