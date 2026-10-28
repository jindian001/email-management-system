"""原始邮件对象存储。

原始 .eml 必须留存（exp.md 4.2.2）：模型升级后可离线重放，审计也需要原文。
本地实现用于开发/测试；生产可换成 S3/MinIO，只需实现同样的三个方法。
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Protocol

from mailmind.core.config import Settings

_KEY_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")


def content_key(data: bytes, prefix: str = "raw") -> str:
    """按内容寻址：同样的邮件永远落到同一个 key，天然去重。"""
    digest = hashlib.sha256(data).hexdigest()
    return f"{prefix}/{digest[:2]}/{digest}.eml"


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalObjectStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not key or not _KEY_RE.match(key):
            raise ValueError(f"非法对象键: {key!r}")
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root) + os.sep) and path != self.root:
            raise ValueError(f"对象键越界: {key!r}")
        return path

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        try:
            return self._path(key).is_file()
        except ValueError:
            return False


class MemoryObjectStore:
    """测试与无盘环境使用。"""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> str:
        self.data[key] = data
        return key

    def get(self, key: str) -> bytes:
        return self.data[key]

    def exists(self, key: str) -> bool:
        return key in self.data


def make_store(settings: Settings) -> ObjectStore:
    if settings.storage_backend == "memory":
        return MemoryObjectStore()
    return LocalObjectStore(settings.storage_root)
