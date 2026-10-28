"""连接器与发送器工厂：按账号 provider 组装。"""

from __future__ import annotations

from mailmind.connectors.base import MailConnector, MessageSender
from mailmind.connectors.gmail_connector import GMAIL_BASE, GmailConnector, GmailSender
from mailmind.connectors.graph_connector import GRAPH_BASE, GraphConnector
from mailmind.connectors.imap_connector import ImapConnector
from mailmind.connectors.smtp_sender import SmtpSender
from mailmind.core.config import Settings
from mailmind.core.logging import get_logger
from mailmind.core.security import secret_box

log = get_logger("mailmind.connectors")


def _secret(account, settings: Settings) -> str:
    if not account.secret_enc:
        return ""
    try:
        return secret_box(settings).decrypt(account.secret_enc)
    except ValueError:
        # 常见原因：MAILMIND_SECRET_KEY 变更过，或数据库来自另一套密钥的环境
        log.warning(
            "credential_decrypt_failed",
            account_id=account.id,
            email=account.email,
            hint="请检查 MAILMIND_SECRET_KEY 是否与创建账号时一致",
        )
        return ""


def build_connector(account, settings: Settings) -> MailConnector | None:
    cfg = account.config or {}
    if account.provider == "imap":
        host = cfg.get("imap_host") or cfg.get("host")
        if not host:
            return None
        return ImapConnector(
            host=host,
            username=cfg.get("imap_user") or cfg.get("username") or account.email,
            password=_secret(account, settings),
            port=int(cfg.get("imap_port", cfg.get("port", 993))),
            folder=cfg.get("folder", "INBOX"),
            use_ssl=bool(cfg.get("use_ssl", True)),
        )
    if account.provider == "gmail":
        return GmailConnector(
            _secret(account, settings),
            user_id=cfg.get("user_id", "me"),
            base_url=cfg.get("base_url", GMAIL_BASE),
            label_ids=tuple(cfg.get("label_ids", ["INBOX"])),
        )
    if account.provider == "graph":
        return GraphConnector(
            _secret(account, settings),
            mailbox=cfg.get("mailbox", "me"),
            folder=cfg.get("folder", "inbox"),
            base_url=cfg.get("base_url", GRAPH_BASE),
        )
    return None


def build_sender(account, settings: Settings, default: MessageSender | None = None) -> MessageSender | None:
    """优先级：账号显式 SMTP > Gmail API > 注入的默认发送器。"""
    cfg = account.config or {}
    host = cfg.get("smtp_host")
    if host:
        return SmtpSender(
            host=host,
            port=int(cfg.get("smtp_port", 587)),
            username=cfg.get("smtp_user", account.email),
            password=_secret(account, settings),
            use_tls=bool(cfg.get("smtp_tls", True)),
        )
    if account.provider == "gmail":
        return GmailSender(
            _secret(account, settings),
            user_id=cfg.get("user_id", "me"),
            base_url=cfg.get("base_url", GMAIL_BASE),
        )
    # Graph 走 SMTP（见 graph_connector 文档字符串）；否则用注入的发送器（测试/演示）
    return default
