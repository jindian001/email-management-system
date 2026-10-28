from __future__ import annotations

from mailmind.pipeline.features import FeatureBundle, SenderStats, build_features
from mailmind.pipeline.normalize import (
    clean_body,
    deobfuscate,
    extract_urls,
    mask_pii,
    normalize_text,
    strip_quoted,
)
from mailmind.pipeline.parse import ParsedAttachment, ParsedMail, html_to_text, parse_message
from mailmind.pipeline.thread import thread_depth, thread_id_for

__all__ = [
    "FeatureBundle",
    "ParsedAttachment",
    "ParsedMail",
    "SenderStats",
    "build_features",
    "clean_body",
    "deobfuscate",
    "extract_urls",
    "html_to_text",
    "mask_pii",
    "normalize_text",
    "parse_message",
    "strip_quoted",
    "thread_depth",
    "thread_id_for",
]
