"""Celery 应用。默认 eager 模式，测试与演示不需要 broker。"""

from __future__ import annotations

from celery import Celery

from mailmind.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "mailmind",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_default_queue="mailmind",
    broker_connection_retry_on_startup=True,
)

# 注册任务（导入即注册）
from mailmind.tasks import jobs  # noqa: E402,F401
