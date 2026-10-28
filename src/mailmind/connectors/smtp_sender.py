"""SMTP 发送网关。

统一出口（同一 IP / 域名）并预置 SPF/DKIM/DMARC，否则自家回复会被对方判垃圾
—— 这是 exp.md 4.7.4 特别强调的坑。
"""

from __future__ import annotations

import smtplib
from typing import Any, Callable

from mailmind.connectors.base import OutgoingMessage, SendError, build_mime


class SmtpSender:
    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        timeout: float = 30.0,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.timeout = timeout
        self._factory = client_factory or smtplib.SMTP

    def send(self, account_email: str, message: OutgoingMessage) -> str:
        mime = build_mime(message, account_email)
        client = None
        try:
            client = self._factory(self.host, self.port, timeout=self.timeout)
            client.ehlo()
            if self.use_tls:
                client.starttls()
                client.ehlo()
            if self.username:
                client.login(self.username, self.password)
            client.send_message(mime)
        except Exception as exc:  # noqa: BLE001 - 统一转成 SendError
            raise SendError(f"SMTP 发送失败: {exc}") from exc
        finally:
            if client is not None:
                try:
                    client.quit()
                except Exception:  # noqa: BLE001
                    pass
        return message.headers.get("Message-ID") or mime.get("Message-ID", "") or ""
