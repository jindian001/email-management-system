"""连接器工厂：按账号配置构造 IMAP 连接器。"""

from __future__ import annotations

from mailmind.connectors.base import MailConnector
from mailmind.connectors.imap_connector import ImapConnector
from mailmind.core.config import Settings
from mailmind.core.security import secret_box


def build_connector(account, settings: Settings) -> MailConnector | None:
    if account.provider != "imap":
        return None
    cfg = account.config or {}
    host = cfg.get("imap_host") or cfg.get("host")
    if not host:
        return None
    password = ""
    if account.secret_enc:
        try:
            password = secret_box(settings).decrypt(account.secret_enc)
        except ValueError:
            password = ""
    return ImapConnector(
        host=host,
        username=cfg.get("imap_user") or cfg.get("username") or account.email,
        password=password,
        port=int(cfg.get("imap_port", cfg.get("port", 993))),
        folder=cfg.get("folder", "INBOX"),
        use_ssl=bool(cfg.get("use_ssl", True)),
    )
