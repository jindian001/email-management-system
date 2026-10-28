"""凭据加密与 API Key 校验。

邮箱密码/token 绝不明文入库（AGENT.md 安全底线）。
开发环境用 ``MAILMIND_SECRET_KEY`` 派生密钥；生产应由 KMS/Vault 提供。
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from mailmind.core.config import Settings

DEV_SECRET = "mailmind-dev-insecure-key"


class SecretBox:
    def __init__(self, secret_key: str | None = None) -> None:
        raw = (secret_key or DEV_SECRET).encode("utf-8")
        key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        if not token:
            return ""
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise ValueError("凭据解密失败，请检查 MAILMIND_SECRET_KEY") from exc


def secret_box(settings: Settings) -> SecretBox:
    return SecretBox(settings.secret_key)


def api_key_ok(settings: Settings, provided: str | None) -> bool:
    """未配置 API Key 时（开发/测试）放行；配置后用常量时间比较。"""
    if not settings.api_key:
        return True
    if not provided:
        return False
    return hmac.compare_digest(settings.api_key, provided)
