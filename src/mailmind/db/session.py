"""数据库引擎与会话管理。

测试用 SQLite 内存库；生产用 PostgreSQL（同一套模型，JSON 字段自动映射 JSONB 之外的类型）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from mailmind.core.config import Settings
from mailmind.db.models import Base


def make_engine(settings: Settings) -> Engine:
    url = settings.database_url
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    try:
        parsed = make_url(url)
    except Exception:  # noqa: BLE001 - 非法 URL 交给 create_engine 报错
        parsed = None

    if parsed is not None and parsed.get_backend_name() == "sqlite":
        if parsed.database in (None, "", ":memory:"):
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = StaticPool
        else:
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_fk(dbapi_conn, _rec):  # pragma: no cover - 驱动级
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def drop_db(engine: Engine) -> None:
    Base.metadata.drop_all(engine)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
