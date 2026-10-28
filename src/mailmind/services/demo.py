"""演示数据播种（可重复执行）。

``mailmind demo`` 与管理台"点一下看看效果"都走这里：
- 账号按邮箱复用，不重复创建；
- 知识库只在为空时导入；
- 邮件按固定 Message-ID 投递，重复执行只会得到 duplicate，不会产生脏数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mailmind.core.config import Settings
from mailmind.db.models import Account, KnowledgeDocument
from mailmind.services.ingest import IngestService
from mailmind.services.kb import KnowledgeService
from mailmind.services.runtime import Runtime

DEMO_EMAIL = "support@example.com"

DEMO_DOCUMENTS: list[tuple[str, str]] = [
    (
        "退换货政策",
        "商品签收后 7 天内可无理由退货，运费由买家承担。\n\n若商品存在质量问题，退换货运费由我们承担，请在售后页面提交照片凭证。",
    ),
    (
        "发票与对账",
        "发票默认开具增值税普通发票，下单时可在备注中填写抬头与税号。\n\n对账单每月 1 日生成，可在财务中心下载。",
    ),
    (
        "服务时间",
        "客服工作时间为工作日 9:00-18:00，节假日顺延。紧急问题请拨打 400-000-0000。",
    ),
]

DEMO_MESSAGES: list[tuple[str, str, str, str]] = [
    (
        "consult.eml",
        "Tom <tom@customer.com>",
        "关于退货的咨询",
        "您好，我上周买的产品想退货，请问具体怎么操作？运费谁承担？",
    ),
    (
        "spam.eml",
        "Promo <promo@bulk-spam.cn>",
        "恭喜您中奖了！",
        "恭喜您中奖！立即点击 http://192.168.1.10/win 领取 10000 元现金，限时 24 小时有效。",
    ),
    (
        "billing.eml",
        "Finance <finance@partner.com>",
        "9 月对账单",
        "附件是 9 月对账单，请核对金额后于本周五前完成付款。",
    ),
]


@dataclass
class DemoResult:
    account_id: int
    account_created: bool = False
    knowledge_docs: int = 0
    ingested: int = 0
    duplicates: int = 0
    messages: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "account_created": self.account_created,
            "knowledge_docs": self.knowledge_docs,
            "ingested": self.ingested,
            "duplicates": self.duplicates,
            "messages": self.messages,
        }


def seed_demo(settings: Settings, session: Session, runtime: Runtime) -> DemoResult:
    account = session.scalar(select(Account).where(Account.email == DEMO_EMAIL))
    created = account is None
    if account is None:
        account = Account(email=DEMO_EMAIL, provider="memory", display_name="演示客服邮箱", config={})
        session.add(account)
        session.commit()
        session.refresh(account)

    result = DemoResult(account_id=account.id, account_created=created)

    doc_count = int(
        session.scalar(select(func.count()).select_from(KnowledgeDocument)) or 0
    )
    if doc_count == 0:
        kb = KnowledgeService(settings, session, runtime.retriever(session))
        for title, content in DEMO_DOCUMENTS:
            kb.add_document(title, content)
        result.knowledge_docs = len(DEMO_DOCUMENTS)

    service = IngestService(settings, session, runtime)
    for index, (name, sender, subject, body) in enumerate(DEMO_MESSAGES, start=1):
        raw = (
            f"From: {sender}\r\nTo: {DEMO_EMAIL}\r\nSubject: {subject}\r\n"
            f"Message-ID: <demo-{name}@example.com>\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n" + body + "\r\n"
        ).encode("utf-8")
        outcome = service.ingest_raw(account, raw, uid=str(index))
        if outcome.status == "ingested":
            result.ingested += 1
        elif outcome.status == "duplicate":
            result.duplicates += 1
        result.messages.append(
            {"name": name, "status": outcome.status, "mail_id": outcome.mail_id}
        )

    return result
