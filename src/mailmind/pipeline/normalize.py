"""文本归一化、PII 脱敏、URL 抽取、引用剥离。

垃圾邮件会做各种混淆（exp.md 4.5.4），规则匹配前必须先还原。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse

ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)

_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "$": "s", "@": "a", "!": "i"}
)

SHORTENER_DOMAINS = {
    "bit.ly", "t.co", "goo.gl", "tinyurl.com", "t.cn", "url.cn", "dwz.cn",
    "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly", "shorturl.at",
}

# PII 正则（中文场景为主，可扩展）
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("bank_card", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    ("phone_cn", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("ipv4", re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")),
]
_URL_RE = re.compile(r"https?://[^\s<>\"'）)】]+", re.I)
_QUOTE_HEADER_RE = re.compile(
    r"^(?:-{2,}\s*original message\s*-{2,}|on .{0,200}wrote:|-{5,}|在.{0,60}写道[:：]|发件人[:：])",
    re.I | re.M,
)


@dataclass
class UrlInfo:
    url: str
    host: str
    scheme: str = "http"
    is_ip: bool = False
    is_shortener: bool = False
    has_punycode: bool = False


def normalize_text(text: str) -> str:
    """宽度归一 + 去零宽 + 空白压缩。保留大小写（情感特征要用）。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(ZERO_WIDTH)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def deobfuscate(text: str) -> str:
    """还原 leet / 分隔符混淆：``v1agra`` → ``viagra``，``sp am`` 不动（避免误伤）。

    仅对"同时含字母且含可映射字符"的 token 做映射，降低误伤。
    """
    if not text:
        return ""

    def fix(match: re.Match[str]) -> str:
        token = match.group(0)
        alpha = sum(ch.isalpha() for ch in token)
        leet = sum(ch in "013457$@!" for ch in token)
        if alpha >= 2 and leet and leet <= alpha * 2:
            return token.translate(_LEET)
        return token

    return re.sub(r"[A-Za-z0-9$@!]{2,}", fix, text)


def mask_pii(text: str) -> tuple[str, list[dict]]:
    """把敏感信息替换成占位符，返回 (脱敏文本, 命中记录)。"""
    findings: list[dict] = []
    masked = text or ""
    for kind, pattern in _PII_PATTERNS:
        def repl(match: re.Match[str], kind: str = kind) -> str:
            findings.append({"kind": kind, "value": match.group(0)})
            return f"[{kind.upper()}]"

        masked = pattern.sub(repl, masked)
    return masked, findings


def extract_urls(text: str) -> list[UrlInfo]:
    urls: list[UrlInfo] = []
    for raw in _URL_RE.findall(text or ""):
        try:
            parsed = urlparse(raw)
        except ValueError:
            continue
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            continue
        is_ip = bool(re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", host))
        urls.append(
            UrlInfo(
                url=raw,
                host=host,
                scheme=parsed.scheme or "http",
                is_ip=is_ip,
                is_shortener=host in SHORTENER_DOMAINS or any(host.endswith("." + d) for d in SHORTENER_DOMAINS),
                has_punycode="xn--" in host,
            )
        )
    return urls


def strip_quoted(text: str) -> str:
    """去掉引用历史：``>`` 开头行与 ``On ... wrote:`` 之后的内容。"""
    if not text:
        return ""
    lines = text.split("\n")
    kept: list[str] = []
    for line in lines:
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    body = "\n".join(kept)
    match = _QUOTE_HEADER_RE.search(body)
    if match:
        body = body[: match.start()]
    return body.strip()


def strip_signature(text: str) -> str:
    """去掉常见签名（``-- `` 分隔线之后）。"""
    if not text:
        return ""
    parts = re.split(r"\n--\s*\n", text, maxsplit=1)
    return parts[0].strip()


def clean_body(text: str) -> str:
    return strip_signature(strip_quoted(normalize_text(text)))


def caps_ratio(text: str) -> float:
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if ch.isupper()) / len(letters)


def dense_feature_hint(text: str) -> dict[str, float]:
    text = text or ""
    length = max(len(text), 1)
    return {
        "caps_ratio": round(caps_ratio(text), 4),
        "exclamations": float(text.count("!") + text.count("！")),
        "currency": float(len(re.findall(r"[$￥€£]|元|折扣|优惠", text))),
        "density_scale": round(len(re.findall(r"[!！$￥%]", text)) / length * 100, 4),
    }
