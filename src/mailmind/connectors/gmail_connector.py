"""Gmail API 连接器与发送器。

不依赖 google-api-python-client：直接用 REST + 注入的 httpx.Client，
既减少了依赖，也让协议层可以用 ``httpx.MockTransport`` 完整测试。

游标语义（对应 ``Account.last_uid``）：Gmail 的 ``historyId``（int64），
因此不需要额外的字符串游标列；history 过期（404）时返回 ``reset=True`` 触发全量重扫。
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from mailmind.connectors.base import (
    ConnectorError,
    FetchedMessage,
    FetchPage,
    Folder,
    OutgoingMessage,
    SendError,
    build_mime,
)

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"


def _b64decode(value: str) -> bytes:
    value = (value or "").strip()
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(f"Gmail raw 解码失败: {exc}") from exc


class GmailConnector:
    def __init__(
        self,
        access_token: str = "",
        *,
        user_id: str = "me",
        label_ids: tuple[str, ...] = ("INBOX",),
        base_url: str = GMAIL_BASE,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.access_token = access_token
        self.user_id = user_id
        self.label_ids = label_ids
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)
        self._own_client = client is None

    # ------------------------------------------------------------ HTTP
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}

    def _get(self, path: str, params: dict[str, Any] | None = None, *, allow_404: bool = False) -> dict | None:
        try:
            response = self.client.get(
                f"{self.base_url}{path}", params=params, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Gmail 请求失败: {exc}") from exc
        if response.status_code == 404 and allow_404:
            return None
        if response.status_code >= 400:
            raise ConnectorError(
                f"Gmail 返回 {response.status_code}: {response.text[:200]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ConnectorError(f"Gmail 响应不是 JSON: {exc}") from exc

    # ------------------------------------------------------------ 接口
    def list_folders(self) -> list[Folder]:
        data = self._get(f"/users/{self.user_id}/labels") or {}
        return [
            Folder(name=str(item.get("id") or item.get("name") or ""))
            for item in data.get("labels", [])
            if item.get("id")
        ]

    def fetch_since(self, last_uid: int, uid_validity: int, limit: int = 100) -> FetchPage:
        reset = False
        new_cursor = last_uid
        message_ids: list[str] = []

        if last_uid:
            history = self._get(
                f"/users/{self.user_id}/history",
                {"startHistoryId": last_uid, "historyTypes": "messageAdded", "maxResults": limit},
                allow_404=True,
            )
            if history is None:
                # history 过期：必须全量重扫（与 IMAP 的 UIDVALIDITY 变化同等处理）
                reset = True
            else:
                for record in history.get("history", []):
                    for added in record.get("messagesAdded", []):
                        message_id = (added.get("message") or {}).get("id")
                        if message_id and message_id not in message_ids:
                            message_ids.append(message_id)
                cursor = history.get("historyId")
                if cursor:
                    new_cursor = int(cursor)

        if (not last_uid) or reset:
            listing = self._get(
                f"/users/{self.user_id}/messages",
                {"labelIds": ",".join(self.label_ids), "maxResults": limit},
            ) or {}
            message_ids = [m["id"] for m in listing.get("messages", []) if m.get("id")]
            profile = self._get(f"/users/{self.user_id}/profile") or {}
            history_id = profile.get("historyId")
            if history_id:
                new_cursor = int(history_id)

        messages: list[FetchedMessage] = []
        for message_id in message_ids[:limit]:
            payload = self._get(
                f"/users/{self.user_id}/messages/{message_id}", {"format": "raw"}
            ) or {}
            raw = payload.get("raw")
            if not raw:
                continue
            messages.append(
                FetchedMessage(uid=message_id, raw=_b64decode(raw), folder="INBOX")
            )

        return FetchPage(messages, uid_validity=1, last_uid=new_cursor, reset=reset)

    def close(self) -> None:
        if self._own_client:
            self.client.close()


class GmailSender:
    """通过 ``messages.send`` 发送原始 MIME，天然保留 In-Reply-To/References 线程头。"""

    def __init__(
        self,
        access_token: str = "",
        *,
        user_id: str = "me",
        base_url: str = GMAIL_BASE,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.access_token = access_token
        self.user_id = user_id
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)
        self._own_client = client is None

    def send(self, account_email: str, message: OutgoingMessage) -> str:
        mime = build_mime(message, account_email)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
        try:
            response = self.client.post(
                f"{self.base_url}/users/{self.user_id}/messages/send",
                headers={"Authorization": f"Bearer {self.access_token}"} if self.access_token else {},
                json={"raw": raw},
            )
        except httpx.HTTPError as exc:
            raise SendError(f"Gmail 发送失败: {exc}") from exc
        if response.status_code >= 400:
            raise SendError(f"Gmail 发送返回 {response.status_code}: {response.text[:200]}")
        try:
            return str(response.json().get("id", ""))
        except ValueError as exc:
            raise SendError(f"Gmail 发送响应不可解析: {exc}") from exc

    def close(self) -> None:
        if self._own_client:
            self.client.close()
