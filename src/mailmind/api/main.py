"""FastAPI 应用工厂。

``create_app`` 是唯一的组装入口：配置、数据库、运行时依赖（LLM/发送器/模型）都在这里注入，
测试因此可以完全离线运行（不碰真实邮箱、不调真实 LLM）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from mailmind import __version__
from mailmind.api.routers import accounts, kb, mails, quarantine, replies, rules, system
from mailmind.core.config import Settings, get_settings
from mailmind.core.logging import configure_logging, get_logger, new_trace_id, set_trace_id
from mailmind.db.session import init_db, make_engine, make_session_factory
from mailmind.services.runtime import Runtime

log = get_logger("mailmind.api")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(
    settings: Settings | None = None,
    runtime: Runtime | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level="DEBUG" if settings.debug else "INFO", json_logs=settings.env != "dev")

    engine = make_engine(settings)
    init_db(engine)
    session_factory = make_session_factory(engine)
    runtime = runtime or Runtime.create(settings)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="智能邮箱管理系统：自动分类、垃圾邮件过滤、自动回复",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.runtime = runtime
    # 由调用方（测试/演示）注入 MemoryConnector，覆盖账号的真实连接器
    app.state.connectors = {}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):  # pragma: no cover - 框架级
        trace_id = request.headers.get("X-Trace-Id") or new_trace_id()
        set_trace_id(trace_id)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

    app.include_router(system.router)
    app.include_router(accounts.router)
    app.include_router(mails.router)
    app.include_router(quarantine.router)
    app.include_router(replies.router)
    app.include_router(rules.router)
    app.include_router(kb.router)

    if STATIC_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")

        @app.get("/", include_in_schema=False)
        def index() -> RedirectResponse:
            return RedirectResponse(url="/ui/")

    log.info("app_created", env=settings.env, llm=settings.llm_provider)
    return app


def __getattr__(name: str):
    """``mailmind.api.main:app`` 的惰性属性，避免 import 阶段就建库。"""
    if name == "app":
        return create_app()
    raise AttributeError(name)
