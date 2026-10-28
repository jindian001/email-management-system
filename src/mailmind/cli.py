"""命令行入口：``mailmind serve|train|demo|ingest|sync``。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mailmind import __version__
from mailmind.core.config import get_settings


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "mailmind.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
    return 0


def cmd_train(_args: argparse.Namespace) -> int:
    from mailmind.db.session import init_db, make_engine, make_session_factory
    from mailmind.services.training import rebuild_from_db

    settings = get_settings()
    engine = make_engine(settings)
    init_db(engine)
    session = make_session_factory(engine)()
    try:
        stats = rebuild_from_db(session, settings)
    finally:
        session.close()
    print(f"模型已更新：{stats}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from mailmind.db.models import Account
    from mailmind.db.session import init_db, make_engine, make_session_factory
    from mailmind.services.ingest import IngestService
    from mailmind.services.runtime import Runtime

    settings = get_settings()
    engine = make_engine(settings)
    init_db(engine)
    session = make_session_factory(engine)()
    try:
        account = session.get(Account, args.account_id)
        if account is None:
            print(f"账号不存在: {args.account_id}", file=sys.stderr)
            return 1
        raw = Path(args.file).read_bytes()
        outcome = IngestService(settings, session, Runtime.create(settings)).ingest_raw(
            account, raw, folder=args.folder
        )
        print(outcome)
        return 0 if outcome.ok else 1
    finally:
        session.close()


def cmd_sync(args: argparse.Namespace) -> int:
    from mailmind.tasks.jobs import run_sync

    print(run_sync(args.account_id, args.limit))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """一键演示：内存账号 + 知识库 + 三封样例邮件（可重复执行）。"""
    from mailmind.api.main import create_app
    from mailmind.core.config import Settings
    from mailmind.services.demo import seed_demo

    base = get_settings()
    settings = Settings(**{**base.model_dump(), "auto_reply_send_mode": "review"})
    app = create_app(settings)
    session = app.state.session_factory()
    try:
        result = seed_demo(settings, session, app.state.runtime)
    finally:
        session.close()

    for item in result.messages:
        print(f"{item['name']}: {item['status']}")
    print(
        f"\n账号 #{result.account_id}"
        + ("（新建）" if result.account_created else "（复用已有）")
        + f" · 新增邮件 {result.ingested} · 跳过重复 {result.duplicates} · 知识库新增 {result.knowledge_docs}"
    )
    print("\n启动服务：")
    print(f"  mailmind serve --port {args.port}")
    print(f"  管理台: http://127.0.0.1:{args.port}/ui/")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mailmind", description="智能邮箱管理系统")
    parser.add_argument("--version", action="version", version=f"mailmind {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="启动 API 服务")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.add_argument("--log-level", default="info")
    p_serve.set_defaults(func=cmd_serve)

    p_train = sub.add_parser("train", help="用反馈数据重训模型")
    p_train.set_defaults(func=cmd_train)

    p_demo = sub.add_parser("demo", help="生成演示数据")
    p_demo.add_argument("--port", type=int, default=8080, help="仅用于打印访问地址")
    p_demo.set_defaults(func=cmd_demo)

    p_ingest = sub.add_parser("ingest", help="导入一封 .eml")
    p_ingest.add_argument("--account-id", type=int, required=True)
    p_ingest.add_argument("--file", required=True)
    p_ingest.add_argument("--folder", default="INBOX")
    p_ingest.set_defaults(func=cmd_ingest)

    p_sync = sub.add_parser("sync", help="同步一个 IMAP 账号")
    p_sync.add_argument("--account-id", type=int, required=True)
    p_sync.add_argument("--limit", type=int, default=100)
    p_sync.set_defaults(func=cmd_sync)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
