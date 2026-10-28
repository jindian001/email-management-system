"""异步任务：同步、重处理、重训。

任务本身只做"取依赖 + 调 service"，因此既可以 Celery 异步跑，
也可以在同步模式下直接函数调用（测试与 CLI 都用后者）。
"""

from __future__ import annotations

from celery import shared_task

from mailmind.connectors.factory import build_connector
from mailmind.core.config import get_settings
from mailmind.core.logging import get_logger, new_trace_id, set_trace_id
from mailmind.db.models import Account, Mail
from mailmind.db.session import init_db, make_engine, make_session_factory
from mailmind.pipeline.parse import parse_message
from mailmind.services.ingest import IngestService
from mailmind.services.processing import ProcessingService
from mailmind.services.runtime import Runtime
from mailmind.services.training import rebuild_from_db

log = get_logger("mailmind.tasks")


def _deps():
    settings = get_settings()
    engine = make_engine(settings)
    init_db(engine)
    factory = make_session_factory(engine)
    return settings, factory, Runtime.create(settings)


def run_sync(account_id: int, limit: int = 100) -> dict:
    set_trace_id(new_trace_id())
    settings, factory, runtime = _deps()
    session = factory()
    try:
        account = session.get(Account, account_id)
        if account is None:
            return {"error": "account_not_found", "account_id": account_id}
        connector = build_connector(account, settings)
        if connector is None:
            return {"error": "connector_unavailable", "account_id": account_id}
        result = IngestService(settings, session, runtime).sync_account(account, connector, limit)
        return result.to_dict()
    finally:
        session.close()


def run_process_mail(mail_id: int) -> dict:
    """重新跑一封邮件的处理链（模型升级后回放）。"""
    set_trace_id(new_trace_id())
    settings, factory, runtime = _deps()
    session = factory()
    try:
        mail = session.get(Mail, mail_id)
        if mail is None:
            return {"error": "mail_not_found", "mail_id": mail_id}
        if not mail.raw_object_key:
            return {"error": "raw_missing", "mail_id": mail_id}
        raw = runtime.store.get(mail.raw_object_key)
        parsed = parse_message(raw)
        result = ProcessingService(settings, session, runtime).process(mail, parsed)
        session.commit()
        return result.to_dict()
    finally:
        session.close()


def run_retrain() -> dict:
    set_trace_id(new_trace_id())
    settings, factory, _runtime = _deps()
    session = factory()
    try:
        stats = rebuild_from_db(session, settings)
        log.info("retrained", **stats)
        return stats
    finally:
        session.close()


@shared_task(name="mailmind.sync_account")
def sync_account_task(account_id: int, limit: int = 100) -> dict:
    return run_sync(account_id, limit)


@shared_task(name="mailmind.process_mail")
def process_mail_task(mail_id: int) -> dict:
    return run_process_mail(mail_id)


@shared_task(name="mailmind.retrain")
def retrain_task() -> dict:
    return run_retrain()


__all__ = [
    "run_process_mail",
    "run_retrain",
    "run_sync",
    "sync_account_task",
    "process_mail_task",
    "retrain_task",
]
