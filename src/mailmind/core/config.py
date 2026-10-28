"""全局配置。

所有可调参数集中在此处，通过 ``MAILMIND_`` 前缀的环境变量或 ``.env`` 覆盖。
阈值默认值与设计文档 exp.md 第 4.5 / 4.7 节保持一致。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MAILMIND_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 基础 ----------
    app_name: str = "MailMind"
    env: Literal["dev", "test", "prod"] = "dev"
    debug: bool = False

    # ---------- 存储 ----------
    database_url: str = "sqlite+pysqlite:///./var/mailmind.db"
    storage_backend: Literal["local", "memory"] = "local"
    storage_root: str = "./var/raw"
    max_mail_bytes: int = 25 * 1024 * 1024
    max_attachment_bytes: int = 25 * 1024 * 1024

    # ---------- 队列 ----------
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = True

    # ---------- 安全 ----------
    api_key: str = ""
    secret_key: str = "mailmind-dev-insecure-key"
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # ---------- 垃圾邮件过滤 ----------
    # spam_score < pass_threshold            -> pass
    # pass_threshold <= score < quarantine   -> tag（打标照常投递）
    # score >= quarantine_threshold          -> quarantine（隔离）
    spam_pass_threshold: float = 0.70
    spam_quarantine_threshold: float = 0.95
    # 模型概率落在此区间时交给 LLM 复核
    spam_review_low: float = 0.20
    spam_review_high: float = 0.80
    # 规则命中时的固定置信度
    spam_rule_hit_score: float = 0.99
    spam_auth_fail_score: float = 0.90

    # ---------- 分类 ----------
    # 主分类置信度低于此值时走 LLM few-shot 分类
    classifier_review_threshold: float = 0.60
    categories: list[str] = Field(
        default_factory=lambda: [
            "consult",
            "billing",
            "notice",
            "marketing",
            "social",
            "internal",
            "recruiting",
            "complaint",
            "spam",
            "other",
        ]
    )

    # ---------- 自动回复 ----------
    auto_reply_enabled: bool = True
    auto_reply_send_mode: Literal["review", "auto"] = "review"
    auto_reply_min_confidence: float = 0.85
    auto_reply_review_min_confidence: float = 0.60
    auto_reply_categories: list[str] = Field(default_factory=lambda: ["consult", "aftersale", "booking"])
    auto_reply_noreply_localparts: list[str] = Field(
        default_factory=lambda: [
            "no-reply",
            "noreply",
            "do-not-reply",
            "donotreply",
            "mailer-daemon",
            "postmaster",
            "bounce",
        ]
    )
    auto_reply_cooldown_hours: int = 24
    auto_reply_max_thread_depth: int = 3
    auto_reply_cooldown_domain: str = ""  # 冷却期 Key 的命名空间，留空用账号 ID
    quiet_hours_start: str = ""  # "22:00"
    quiet_hours_end: str = ""  # "08:00"
    quiet_hours_utc_offset: int = 8  # 免打扰时段按 UTC+8 计算

    # ---------- 检索 ----------
    retrieval_top_k: int = 20
    retrieval_rerank_k: int = 5
    retrieval_min_score: float = 0.15
    embedding_dim: int = 256
    chunk_size: int = 512
    chunk_overlap: int = 80

    # ---------- LLM ----------
    llm_provider: Literal["template", "openai"] = "template"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 1

    # ---------- 模型 ----------
    model_dir: str = "./var/models"

    # ---------- 业务常量 ----------
    quarantine_folder: str = "Quarantine"
    noreply_folders: list[str] = Field(default_factory=lambda: ["Spam", "Junk", "Trash"])

    def quiet_window(self) -> tuple[int, int] | None:
        """返回免打扰时段（分钟数区间 [start, end)），未配置或非法返回 None。"""
        if not self.quiet_hours_start or not self.quiet_hours_end:
            return None
        try:
            sh, sm = (int(x) for x in self.quiet_hours_start.split(":"))
            eh, em = (int(x) for x in self.quiet_hours_end.split(":"))
        except ValueError:
            return None
        if not (0 <= sh < 24 and 0 <= eh < 24 and 0 <= sm < 60 and 0 <= em < 60):
            return None
        return sh * 60 + sm, eh * 60 + em


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
