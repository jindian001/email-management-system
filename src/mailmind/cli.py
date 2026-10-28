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


def cmd_demo(_args: argparse.Namespace) -> int:
    """一键演示：内存账号 + 知识库 + 三封样例邮件。"""
    from mailmind.api.main import create_app
    from mailmind.core.config import Settings
    from mailmind.db.models import Account
    from mailmind.services.ingest import IngestService
    from mailmind.services.kb import KnowledgeService

    base = get_settings()
    settings = Settings(**{**base.model_dump(), "auto_reply_send_mode": "review"})
    app = create_app(settings)
    runtime = app.state.runtime
    session = app.state.session_factory()

    account = Account(email="support@example.com", provider="memory", display_name="演示客服邮箱")
    session.add(account)
    session.commit()

    kb = KnowledgeService(settings, session, runtime.retriever(session))
    kb.add_document(
        "退换货政策",
        "商品签收后 7 天内可无理由退货，运费由买家承担。\n\n若商品存在质量问题，退换货运费由我们承担，请在售后页面提交照片凭证。",
    )
    kb.add_document(
        "发票与对账",
        "发票默认开具增值税普通发票，下单时可在备注中填写抬头与税号。\n\n对账单每月 1 日生成，可在财务中心下载。",
    )
    kb.add_document(
        "服务时间",
        "客服工作时间为工作日 9:00-18:00，节假日顺延。紧急问题请拨打 400-000-0000。",
    )

    samples = {
        "consult.eml": (
            "Tom <tom@customer.com>", "关于退货的咨询",
            "您好，我上周买的产品想退货，请问具体怎么操作？运费谁承担？",
        ),
        "spam.eml": (
            "Promo <promo@bulk-spam.cn>", "恭喜您中奖了！",
            "恭喜您中奖！立即点击 http://192.168.1.10/win 领取 10000 元现金，限时 24 小时。",
        ),
        "billing.eml": (
            "Finance <finance@partner.com>", "9 月对账单",
            "附件是 9 月对账单，请核对金额后于本周五前完成付款。",
        ),
    }

    service = IngestService(settings, session, runtime)
    for name, (sender, subject, body) in samples.items():
        raw = (
            f"From: {sender}\r\nTo: support@example.com\r\nSubject: {subject}\r\n"
            f"Message-ID: <demo-{name}@example.com>\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n" + body + "\r\n"
        ).encode("utf-8")
        outcome = service.ingest_raw(account, raw, uid=str(len(samples)))
        print(f"{name}: {outcome}")

    print("\n演示数据已就绪，启动服务：")
    print("  MAILMIND_ENV=dev mailmind serve --port 8080")
    print("  管理台: http://127.0.0.1:8080/ui/")
    session.close()
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
