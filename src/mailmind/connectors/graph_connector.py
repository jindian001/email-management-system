"""Microsoft Graph 读取连接器。

游标语义（``Account.last_uid``）：用**最新一封邮件的 receivedDateTime 的 Unix 秒**，
增量拉取时转成 ``receivedDateTime gt <iso>`` 过滤条件。同一个 int 列即可跨提供商复用。

发信不在此实现：Graph 的 ``sendMail`` 无法携带 In-Reply-To/References 等自定义头，
强行使用会破坏会话线程，因此 Graph 账号建议走 SMTP（Graph 支持 SMTP AUTH），
由 :class:`mailmind.connectors.smtp_sender.SmtpSender` 发送。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from mailmind.connectors.base import ConnectorError, FetchPage, FetchedMessage, Folder

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _epoch(value: str | None, fallback: int) -> int:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


class GraphConnector:
    def __init__(
        self,
        access_token: str = "",
        *,
        mailbox: str = "me",
        folder: str = "inbox",
        base_url: str = GRAPH_BASE,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.access_token = access_token
        self.mailbox = mailbox
        self.folder = folder
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)
        self._own_client = client is None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}

    def _request(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        try:
            response = self.client.get(
                f"{self.base_url}{path}", params=params, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Graph 请求失败: {exc}") from exc
        if response.status_code >= 400:
            raise ConnectorError(f"Graph 返回 {response.status_code}: {response.text[:200]}")
        return response

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict:
        try:
            return self._request(path, params).json()
        except ValueError as exc:
            raise ConnectorError(f"Graph 响应不是 JSON: {exc}") from exc

    def list_folders(self) -> list[Folder]:
        data = self._get_json(f"/{self.mailbox}/mailFolders")
        return [
            Folder(name=str(item.get("displayName") or item.get("id") or ""), flags=[])
            for item in data.get("value", [])
            if item.get("id")
        ]

    def fetch_since(self, last_uid: int, uid_validity: int, limit: int = 100) -> FetchPage:
        params: dict[str, Any] = {
            "$top": limit,
            "$orderby": "receivedDateTime asc",
            "$select": "id,internetMessageId,receivedDateTime,subject",
        }
        if last_uid:
            since = datetime.fromtimestamp(last_uid, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            params["$filter"] = f"receivedDateTime gt {since}"

        data = self._get_json(f"/{self.mailbox}/mailFolders/{self.folder}/messages", params)
        cursor = last_uid
        messages: list[FetchedMessage] = []
        for item in data.get("value", []):
            message_id = item.get("id")
            if not message_id:
                continue
            received = _epoch(item.get("receivedDateTime"), cursor)
            cursor = max(cursor, received)
            raw = self._request(f"/{self.mailbox}/messages/{message_id}/$value").content
            messages.append(FetchedMessage(uid=str(message_id), raw=raw, folder="INBOX"))

        return FetchPage(messages, uid_validity=1, last_uid=cursor, reset=False)

    def close(self) -> None:
        if self._own_client:
            self.client.close()
