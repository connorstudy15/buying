"""注册与账号登录：仅同源 HTTPS（或回环开发）；不回显密码输入。"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.infrastructure.account_access import ACCOUNT_COOKIE, LOCAL_ACCOUNT_COOKIE, AccountRateLimit
from app.infrastructure.identity import IdentityError
from app.infrastructure.invite_access import normalize_origin


def _origin(request: Request) -> str:
    try:
        supplied = request.headers.get("origin", "")
        origin = normalize_origin(supplied)
        if origin != supplied:
            raise ValueError
        approved = getattr(request.app.state, "account_origins", ())
        # Nginx 保留公网 Host；开发代理改写 Host 时使用显式允许的开发源。
        host = request.headers.get("host", "").lower()
        if origin not in approved and urlsplit(origin).netloc.lower() != host:
            raise ValueError
        if request.headers.get("sec-fetch-site", "same-origin") == "cross-site":
            raise ValueError
        return origin
    except ValueError:
        raise HTTPException(status_code=403, detail="请从同一个 HTTPS 网站页面注册或登录") from None


async def _body(request: Request, fields: set[str]) -> dict:
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 2048:
            raise HTTPException(status_code=400, detail="注册或登录请求格式无效")
    try:
        data = json.loads(content)
        if not isinstance(data, dict) or set(data) != fields or not all(isinstance(v, str) for v in data.values()):
            raise ValueError
        return data
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="注册或登录请求格式无效") from None


def register_account_routes(api: FastAPI):
    async def authenticate(request: Request, *, register: bool):
        from app.presentation.identity import identity_policy
        store = getattr(request.app.state, "account_access", None)
        if store is None or identity_policy(request).mode != "hmac":
            raise HTTPException(status_code=404, detail="账号登录未启用")
        origin = _origin(request)
        data = await _body(request, {"username", "password", "display_name"} if register else {"username", "password"})
        try:
            if register:
                cookie, session = await run_in_threadpool(store.register, data["username"], data["password"], data["display_name"], origin)
            else:
                cookie, session = await run_in_threadpool(store.login, data["username"], data["password"], origin)
        except AccountRateLimit as error:
            raise HTTPException(status_code=429, detail=str(error), headers={"Retry-After": "900", "Cache-Control": "no-store"}) from None
        except IdentityError:
            raise HTTPException(status_code=401, detail="账号或密码不正确", headers={"Cache-Control": "no-store"}) from None
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error), headers={"Cache-Control": "no-store"}) from None
        # 登录切换会话时吊销当前浏览器旧账号会话，保留其他设备登录。
        previous = request.cookies.get(ACCOUNT_COOKIE, "") or request.cookies.get(LOCAL_ACCOUNT_COOKIE, "")
        if previous:
            await run_in_threadpool(store.logout, previous)
        response = JSONResponse({"mode": "hmac", "authenticated": True, "credential": "account",
            "buyer_id": session.buyer_id, "display_name": session.display_name, "username": session.username},
            headers={"Cache-Control": "no-store"})
        secure = origin.startswith("https://")
        response.delete_cookie(LOCAL_ACCOUNT_COOKIE if secure else ACCOUNT_COOKIE, path="/", secure=not secure, httponly=True, samesite="lax")
        response.set_cookie(ACCOUNT_COOKIE if secure else LOCAL_ACCOUNT_COOKIE, cookie, secure=secure,
            httponly=True, samesite="lax", path="/", max_age=max(1, session.expires_at - int(store.clock())))
        return response

    @api.post("/commerce/auth/register")
    async def register(request: Request):
        return await authenticate(request, register=True)

    @api.post("/commerce/auth/login")
    async def login(request: Request):
        return await authenticate(request, register=False)
