"""IMAP 连接器（stdlib imaplib）。

只做 IO 与协议解析，业务逻辑在 services 层。关键点（exp.md 4.1）：
- UIDVALIDITY 变化必须触发全量重扫，否则会漏信；
- UID 搜索使用 ``UID n:*``；
- 所有解析函数独立可测（用假 client 注入）。
"""

from __future__ import annotations

import imaplib
import re
from datetime import UTC, datetime
from typing import Any

from mailmind.connectors.base import (
    ConnectorError,
    FetchedMessage,
    FetchPage,
    Folder,
)

_UID_RE = re.compile(rb"UID\s+(\d+)", re.I)
_FLAGS_RE = re.compile(rb"FLAGS\s+\(([^)]*)\)", re.I)
_INTERNALDATE_RE = re.compile(rb'INTERNALDATE\s+"([^"]+)"', re.I)


def parse_uidvalidity(select_response: Any) -> int:
    """从 SELECT 响应里取 UIDVALIDITY。

    imaplib 返回形如 ``[b'1234']`` 或 ``{'UIDVALIDITY': [b'1234']}``。
    """
    if not select_response:
        return 0
    if isinstance(select_response, dict):
        values = select_response.get("UIDVALIDITY") or []
        if values:
            try:
                return int(values[0])
            except (TypeError, ValueError):
                return 0
        return 0
    for item in select_response:
        if isinstance(item, bytes) and item.strip().isdigit():
            return int(item.strip())
    return 0


def parse_fetch_meta(meta: bytes) -> tuple[str, list[str], datetime | None]:
    uid_match = _UID_RE.search(meta)
    uid = uid_match.group(1).decode() if uid_match else ""
    flags_match = _FLAGS_RE.search(meta)
    flags = flags_match.group(1).decode().split() if flags_match else []
    internal = _INTERNALDATE_RE.search(meta)
    received: datetime | None = None
    if internal:
        try:
            received = datetime.strptime(
                internal.group(1).decode(), "%d-%b-%Y %H:%M:%S %z"
            ).astimezone(UTC)
        except ValueError:
            received = None
    return uid, flags, received


def parse_fetch_response(data: Any) -> list[FetchedMessage]:
    """把 ``client.uid('fetch', ...)`` 的返回解析成 FetchedMessage 列表。"""
    messages: list[FetchedMessage] = []
    if not data:
        return messages
    for item in data:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        meta, raw = item[0], item[1]
        if not isinstance(raw, (bytes, bytearray)):
            continue
        uid, flags, _received = parse_fetch_meta(meta if isinstance(meta, bytes) else b"")
        messages.append(FetchedMessage(uid=uid or str(len(messages) + 1), raw=bytes(raw), flags=flags))
    return messages


class ImapConnector:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 993,
        folder: str = "INBOX",
        use_ssl: bool = True,
        timeout: float = 30.0,
        client_factory: Any | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.folder = folder
        self.use_ssl = use_ssl
        self.timeout = timeout
        self._factory = client_factory or (
            imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4
        )
        self._client: Any | None = None

    # ------------------------------------------------------------ 连接
    def _connect(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            client = self._factory(self.host, self.port, timeout=self.timeout)
            client.login(self.username, self.password)
        except Exception as exc:  # noqa: BLE001 - 统一转成 ConnectorError
            raise ConnectorError(f"IMAP 登录失败: {exc}") from exc
        self._client = client
        return client

    def list_folders(self) -> list[Folder]:
        client = self._connect()
        try:
            typ, data = client.list()
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"LIST 失败: {exc}") from exc
        if typ != "OK":
            raise ConnectorError(f"LIST 返回 {typ}")
        folders: list[Folder] = []
        for line in data or []:
            if not isinstance(line, bytes):
                continue
            text = line.decode("utf-8", "replace")
            # 形如：(\HasNoChildren) "/" "INBOX"  —— 文件夹名是最后一个引号串
            quoted = re.findall(r'"([^"]*)"', text)
            name = quoted[-1].strip() if quoted else text.strip()
            if name:
                folders.append(Folder(name=name))
        return folders

    def select(self) -> int:
        client = self._connect()
        try:
            typ, data = client.select(self.folder, readonly=True)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"SELECT {self.folder} 失败: {exc}") from exc
        if typ != "OK":
            raise ConnectorError(f"SELECT 返回 {typ}")
        return parse_uidvalidity(data)

    def fetch_since(
        self, last_uid: int, uid_validity: int, limit: int = 100
    ) -> FetchPage:
        client = self._connect()
        current_uidvalidity = self.select()
        reset = uid_validity not in (0, current_uidvalidity)
        start = 1 if reset else max(last_uid + 1, 1)
        try:
            typ, data = client.uid("search", None, f"UID {start}:*")
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"SEARCH 失败: {exc}") from exc
        if typ != "OK":
            raise ConnectorError(f"SEARCH 返回 {typ}")
        uids: list[str] = []
        for chunk in data or []:
            if isinstance(chunk, bytes):
                uids.extend(chunk.decode().split())
        uids = [u for u in uids if u.isdigit()]
        # UID n:* 在 n 大于最大值时会回送最后一封，需要过滤掉
        if not reset:
            uids = [u for u in uids if int(u) > last_uid]
        uids.sort(key=int)
        page = uids[:limit]
        if not page:
            return FetchPage([], current_uidvalidity, 0 if reset else last_uid, reset)

        try:
            typ, raw_data = client.uid("fetch", ",".join(page), "(UID RFC822 FLAGS INTERNALDATE)")
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"FETCH 失败: {exc}") from exc
        if typ != "OK":
            raise ConnectorError(f"FETCH 返回 {typ}")
        messages = parse_fetch_response(raw_data)
        for msg in messages:
            msg.folder = self.folder
        new_last = max((int(m.uid) for m in messages if m.uid.isdigit()), default=int(page[-1]))
        return FetchPage(messages, current_uidvalidity, new_last, reset)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.logout()
            except Exception:  # noqa: BLE001 - 关闭失败不影响主流程
                pass
            self._client = None
