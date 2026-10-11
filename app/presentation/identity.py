"""所有买家入口共用身份与会话归属检查；严格模式不接收 query 中的 token。"""
from __future__ import annotations
import json

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.domain.session.ports.session_store import SessionNotFound, SessionOwnerMismatch, SessionStoreError
from app.infrastructure.identity import IdentityError, IdentityPolicy, buyer_identity
from app.infrastructure.invite_access import COOKIE_NAME, LOCAL_COOKIE_NAME, InviteOriginError


def identity_policy(request: Request | WebSocket) -> IdentityPolicy:
    return getattr(request.app.state, "identity_policy", None) or IdentityPolicy()


def _token(request: Request | WebSocket) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization:
        scheme, separator, value = authorization.partition(" ")
        if separator and scheme.lower() == "bearer" and value and " " not in value:
            return value
        return ""
    if isinstance(request, WebSocket):
        protocols = request.headers.get("sec-websocket-protocol", "").split(",")
        tokens = [item.strip()[len("globex-auth."):] for item in protocols if item.strip().startswith("globex-auth.")]
        if len(tokens) == 1:
            return tokens[0]
    return ""


def _check_cookie_origin(request: Request | WebSocket, origin: str) -> None:
    supplied = request.headers.get("origin")
    unsafe = isinstance(request, WebSocket) or request.method not in {"GET", "HEAD", "OPTIONS"}
    if (unsafe or supplied is not None) and supplied != origin:
        raise HTTPException(status_code=403, detail="体验登录不接受跨站请求", headers={"Cache-Control": "no-store"})


def _cookie(request: Request | WebSocket) -> str:
    return request.cookies.get(COOKIE_NAME, "") or request.cookies.get(LOCAL_COOKIE_NAME, "")


def verified_buyer(request: Request | WebSocket) -> str:
    """显式 Bearer/WS 凭证优先；无显式凭证时验证服务端浏览器登录。"""
    token = _token(request)
    if (request.headers.get("authorization") or token
            or "globex-auth." in request.headers.get("sec-websocket-protocol", "")):
        return identity_policy(request).verify(token)
    store = getattr(request.app.state, "invite_access", None)
    if store is None:
        raise IdentityError("身份凭证无效或已过期")
    session = store.resolve(_cookie(request))
    # HTTPS 必须使用 __Host- Cookie；普通名称只供本机 HTTP 开发，不能降级公开登录。
    if session.origin.startswith("https://") and not request.cookies.get(COOKIE_NAME):
        raise IdentityError("身份凭证无效或已过期")
    _check_cookie_origin(request, session.origin)
    return session.buyer_id


def register_identity_routes(api: FastAPI) -> None:
    @api.get("/commerce/auth")
    async def access_status(request: Request):
        policy = identity_policy(request)
        headers = {"Cache-Control": "no-store"}
        if policy.mode == "demo":
            return JSONResponse({"mode": "demo", "authenticated": False}, headers=headers)
        if not request.headers.get("authorization") and not _cookie(request):
            return JSONResponse({"mode": "hmac", "authenticated": False}, headers=headers)
        try:
            buyer_id = verified_buyer(request)
        except IdentityError as error:
            raise HTTPException(status_code=401, detail="内测凭证无效或已过期",
                                headers={**headers, "WWW-Authenticate": "Bearer"}) from error
        data = {"mode": "hmac", "authenticated": True, "buyer_id": buyer_id}
        if not request.headers.get("authorization"):
            data["credential"] = "invite"
        return JSONResponse(data, headers=headers)

    @api.post("/commerce/auth/invite")
    async def accept_invite(request: Request):
        store = getattr(request.app.state, "invite_access", None)
        if identity_policy(request).mode != "hmac" or store is None:
            raise HTTPException(status_code=404, detail="邀请入口未启用")
        # 不用会回显 input 的通用验证错误，原始邀请码不得进入错误正文。
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 1024:
                raise HTTPException(status_code=400, detail="邀请请求格式无效")
        try:
            body = json.loads(content)
            if not isinstance(body, dict) or set(body) != {"invite"} or not isinstance(body["invite"], str):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="邀请请求格式无效") from None
        try:
            origin = request.headers.get("origin", "")
            existing = request.cookies.get(COOKIE_NAME, "") or (
                request.cookies.get(LOCAL_COOKIE_NAME, "") if origin.startswith("http://") else "")
            cookie, session = await run_in_threadpool(store.exchange, body["invite"], origin, existing)
        except InviteOriginError as error:
            raise HTTPException(status_code=403, detail="邀请链接与访问入口不匹配") from error
        except IdentityError as error:
            raise HTTPException(status_code=401, detail="邀请链接无效、已过期或已撤销",
                                headers={"Cache-Control": "no-store"}) from error
        response = JSONResponse({"mode": "hmac", "authenticated": True,
            "buyer_id": session.buyer_id, "credential": "invite"}, headers={"Cache-Control": "no-store"})
        secure = session.origin.startswith("https://")
        response.set_cookie(COOKIE_NAME if secure else LOCAL_COOKIE_NAME, cookie, httponly=True, secure=secure,
                            samesite="lax", path="/", max_age=max(1, session.expires_at - int(store.clock())))
        return response

    @api.post("/commerce/auth/logout")
    def logout(request: Request):
        store = getattr(request.app.state, "invite_access", None)
        cookie = _cookie(request)
        if store is not None and cookie:
            try:
                session = store.resolve(cookie)
                _check_cookie_origin(request, session.origin)
            except IdentityError:
                pass
            store.logout(cookie)
        response = JSONResponse({"authenticated": False}, headers={"Cache-Control": "no-store"})
        response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
        response.delete_cookie(LOCAL_COOKIE_NAME, path="/", httponly=True, samesite="lax")
        return response


async def require_buyer(request: Request | WebSocket, claimed_buyer: str) -> str:
    policy = identity_policy(request)
    if policy.mode == "hmac":
        try:
            verified = verified_buyer(request)
        except IdentityError as error:
            raise HTTPException(status_code=401, detail="需要有效的买家身份凭证", headers={"WWW-Authenticate": "Bearer"}) from error
        try:
            claimed = buyer_identity(claimed_buyer)
        except IdentityError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if verified != claimed:
            raise HTTPException(status_code=403, detail="请求买家与签名身份不一致")
        return verified
    try:
        return buyer_identity(claimed_buyer)
    except IdentityError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def session_error(error: SessionStoreError) -> HTTPException:
    code = 403 if isinstance(error, SessionOwnerMismatch) else 404 if isinstance(error, SessionNotFound) else 409
    return HTTPException(status_code=code, detail={"code": error.code, "message": str(error)})


async def require_session(request: Request | WebSocket, buyer_id: str, session_id: str, *, create: bool = False) -> None:
    store = getattr(request.app.state, "session_store", None)
    if store is None:
        # 独立演示路由可以不配置持久层；严格运行态绝不降级跳过归属检查。
        if identity_policy(request).mode == "hmac":
            raise HTTPException(status_code=503, detail="会话归属存储未就绪")
        return
    try:
        await store.assert_owner(session_id, buyer_id, create=create,
            enforce_owner=getattr(request.app.state, "session_owner_binding", True))
    except SessionStoreError as error:
        raise session_error(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


async def require_task(request: Request, buyer_id: str, task_id: str) -> None:
    store = getattr(request.app.state, "session_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="任务归属存储未就绪")
    try:
        session_id = await store.assert_task_owner(task_id, buyer_id)
    except SessionStoreError as error:
        raise session_error(error) from error
    await require_session(request, buyer_id, session_id)


async def require_metrics_reader(request: Request) -> str:
    """全进程聚合指标只对服务端明确授权的签名主体开放。"""
    readers = getattr(request.app.state, "metrics_reader_buyers", ())
    if not readers:
        raise HTTPException(status_code=404, detail="运维指标接口未启用")
    policy = identity_policy(request)
    if policy.mode != "hmac":
        raise HTTPException(status_code=503, detail="运维指标要求配置严格签名身份")
    try:
        buyer_id = policy.verify(_token(request))
    except IdentityError as error:
        raise HTTPException(status_code=401, detail="需要有效的运维读取凭证", headers={"WWW-Authenticate": "Bearer"}) from error
    if buyer_id not in readers:
        raise HTTPException(status_code=403, detail="该主体没有运维指标读取权限")
    return buyer_id
