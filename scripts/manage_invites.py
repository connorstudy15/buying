"""操作员在服务器本机创建/撤销共享邀请；无公开签发接口。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from app.infrastructure.identity import IdentityPolicy
from app.infrastructure.invite_access import InviteAccessStore, normalize_origin
from app.infrastructure.settings import load_settings


def main():
    parser = argparse.ArgumentParser(description="管理共享邀请链接（仅服务器本机）")
    actions = parser.add_subparsers(dest="action", required=True)
    create = actions.add_parser("create")
    create.add_argument("--origin", required=True, help="访客实际打开的 HTTPS 源地址，不带路径")
    create.add_argument("--days", type=int, default=7, choices=range(1, 91), metavar="1..90")
    create.add_argument("--session-hours", type=int, default=24, choices=range(1, 169), metavar="1..168")
    create.add_argument("--output", required=True, type=Path, help="新建私密文件保存链接，不覆盖已有文件")
    revoke = actions.add_parser("revoke")
    revoke.add_argument("--invite-id", required=True)
    actions.add_parser("list")
    args = parser.parse_args()
    settings = load_settings(require_llm_key=False)
    if IdentityPolicy.from_settings(settings).mode != "hmac":
        parser.error("共享邀请必须先启用 hmac 身份验证和会话归属绑定")
    store = InviteAccessStore(settings.data_dir / "invite_access.db")
    if args.action == "create":
        origin = normalize_origin(args.origin)
        # exclusive + 0600：原始链接仅在操作员指定文件中保存，不打印到构建/终端日志。
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        invite_id = None
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                invite_id, token = store.create(origin, ttl_seconds=args.days * 86400,
                                                session_seconds=args.session_hours * 3600)
                output.write(f"{origin}/demo#invite={token}\n")
        except Exception:
            if invite_id is not None:
                store.revoke(invite_id)
            raise
        print(json.dumps({"invite_id": invite_id, "link_file": str(args.output), "days": args.days}, ensure_ascii=False))
    elif args.action == "revoke":
        if not store.revoke(args.invite_id):
            parser.error("未找到该邀请 ID")
        print("邀请已撤销，关联体验登录的后续请求将被拒绝")
    else:
        rows = store.list_invites()
        for row in rows:
            row["expires_at_utc"] = datetime.fromtimestamp(row.pop("expires_at"), timezone.utc).isoformat()
        print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
