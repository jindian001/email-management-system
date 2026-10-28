"""会话（thread）归并。

归并规则（exp.md 4.1/4.3）：
1. 有 References → 取第一个引用作为根；
2. 只有 In-Reply-To → 用它作为根；
3. 都没有 → 用自己的 Message-ID 作为根。

这样"根邮件"的 thread_id = hash(自己的 Message-ID)，而回复的 thread_id = hash(根 Message-ID)，
两者天然落到同一会话，不需要依赖数据库回查（见 exp.md 附录 C.2）。
"""

from __future__ import annotations

import hashlib

from mailmind.pipeline.parse import ParsedMail


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def thread_id_for(parsed: ParsedMail) -> str:
    if parsed.references:
        return f"t-{_hash(parsed.references[0])}"
    if parsed.in_reply_to:
        return f"t-{_hash(parsed.in_reply_to[0])}"
    return f"t-{_hash(parsed.message_id)}"


def thread_depth(parsed: ParsedMail) -> int:
    """会话深度：引用链长度，用于自动回复的防回环判断。"""
    ids = {r for r in parsed.references if r}
    for value in parsed.in_reply_to:
        ids.add(value)
    return len(ids)
