"""运行时依赖装配。

把"可替换的外部依赖"集中到一处：LLM、发送器、对象存储、模型、冷却表。
测试只需要传入自己的实现（RecordingSender / TemplateGateway / MemoryObjectStore）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from mailmind.connectors.base import MessageSender, RecordingSender
from mailmind.core.config import Settings
from mailmind.ml.classify import EmailClassifier
from mailmind.ml.llm import LLMGateway, build_gateway
from mailmind.ml.naive_bayes import NaiveBayesModel
from mailmind.ml.rules import RuleSet
from mailmind.ml.spam import SpamFilter
from mailmind.reply.policy import MemoryCooldown, ReplyPolicy
from mailmind.reply.retrieval import HybridRetriever
from mailmind.services.training import ensure_models
from mailmind.storage import ObjectStore, make_store


@dataclass
class Runtime:
    settings: Settings
    llm: LLMGateway
    sender: MessageSender
    store: ObjectStore
    cooldown: MemoryCooldown = field(default_factory=MemoryCooldown)
    spam_model: NaiveBayesModel | None = None
    category_model: NaiveBayesModel | None = None

    @classmethod
    def create(
        cls,
        settings: Settings,
        *,
        sender: MessageSender | None = None,
        llm: LLMGateway | None = None,
        store: ObjectStore | None = None,
        train_if_missing: bool = True,
    ) -> Runtime:
        spam_model, category_model = ensure_models(settings, train_if_missing=train_if_missing)
        return cls(
            settings=settings,
            llm=llm or build_gateway(settings),
            sender=sender or RecordingSender(),
            store=store or make_store(settings),
            spam_model=spam_model,
            category_model=category_model,
        )

    def reply_policy(self) -> ReplyPolicy:
        return ReplyPolicy(self.settings, self.cooldown)

    def sender_for(self, account) -> MessageSender:
        """账号若配置了 SMTP，就用真实 SMTP 发送；否则用注入的发送器（测试/演示）。"""
        from mailmind.connectors.smtp_sender import SmtpSender
        from mailmind.core.security import secret_box

        cfg = account.config or {}
        host = cfg.get("smtp_host")
        if not host:
            return self.sender
        password = ""
        if account.secret_enc:
            try:
                password = secret_box(self.settings).decrypt(account.secret_enc)
            except ValueError:
                password = ""
        return SmtpSender(
            host=host,
            port=int(cfg.get("smtp_port", 587)),
            username=cfg.get("smtp_user", account.email),
            password=password,
            use_tls=bool(cfg.get("smtp_tls", True)),
        )

    def retriever(self, session: Session | None = None) -> HybridRetriever:
        return HybridRetriever(self.settings, session=session)

    def spam_filter(self, session: Session | None = None, account_id: int | None = None) -> SpamFilter:
        rules = RuleSet.from_db(session, account_id) if session is not None else RuleSet([])
        return SpamFilter(self.settings, rules, self.spam_model, self.llm)

    def classifier(self, session: Session | None = None, account_id: int | None = None) -> EmailClassifier:
        rules = RuleSet.from_db(session, account_id) if session is not None else RuleSet([])
        return EmailClassifier(self.settings, rules, self.category_model, self.llm)
