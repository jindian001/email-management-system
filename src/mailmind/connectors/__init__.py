from __future__ import annotations

from mailmind.connectors.base import (
    ConnectorError,
    FetchedMessage,
    FetchPage,
    Folder,
    MailConnector,
    MemoryConnector,
    MessageSender,
    OutgoingMessage,
    RecordingSender,
    SendError,
    build_mime,
    is_auto_submitted,
    is_bulk,
    parse_address_list,
    thread_depth,
)
from mailmind.connectors.imap_connector import ImapConnector
from mailmind.connectors.smtp_sender import SmtpSender

__all__ = [
    "ConnectorError",
    "FetchPage",
    "FetchedMessage",
    "Folder",
    "ImapConnector",
    "MailConnector",
    "MemoryConnector",
    "MessageSender",
    "OutgoingMessage",
    "RecordingSender",
    "SendError",
    "SmtpSender",
    "build_mime",
    "is_auto_submitted",
    "is_bulk",
    "parse_address_list",
    "thread_depth",
]
