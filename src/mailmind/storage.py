"""原始邮件对象存储。

原始 .eml 必须留存（exp.md 4.2.2）：模型升级后可离线重放，审计也需要原文。
实现三套：
- :class:`LocalObjectStore`  本地目录（开发/单机）
- :class:`MemoryObjectStore` 内存（测试）
- :class:`S3ObjectStore`     S3 / MinIO / OSS 等兼容对象存储（生产）
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Protocol

from mailmind.core.config import Settings

_KEY_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")


def validate_key(key: str) -> str:
    """对象键白名单校验：禁止空值、非法字符与 ``..`` 路径段（防目录穿越）。"""
    if not key or not _KEY_RE.match(key):
        raise ValueError(f"非法对象键: {key!r}")
    if any(part in {"..", "."} for part in key.split("/")):
        raise ValueError(f"对象键不允许相对路径段: {key!r}")
    return key


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
        validate_key(key)
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


class S3ObjectStore:
    """S3 兼容对象存储。

    ``client`` 可注入（测试用 botocore Stubber），未注入时按需创建 boto3 client，
    因此未安装 boto3 的环境依然可以跑 local/memory 后端。
    """

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        client=None,
        endpoint_url: str = "",
        region: str = "",
    ) -> None:
        if not bucket:
            raise ValueError("storage_backend=s3 时必须配置 MAILMIND_S3_BUCKET")
        if client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - 依赖缺失
                raise RuntimeError("使用 S3 存储需要安装 boto3：pip install 'mailmind[s3]'") from exc
            kwargs = {}
            if endpoint_url:
                kwargs["endpoint_url"] = endpoint_url
            if region:
                kwargs["region_name"] = region
            client = boto3.client("s3", **kwargs)
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client

    def _key(self, key: str) -> str:
        validate_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=data)
        return key

    def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        body = response["Body"]
        return body.read() if hasattr(body, "read") else bytes(body)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ValueError:
            return False
        except Exception as exc:  # noqa: BLE001 - botocore 的 ClientError
            code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise


def make_store(settings: Settings) -> ObjectStore:
    if settings.storage_backend == "memory":
        return MemoryObjectStore()
    if settings.storage_backend == "s3":
        return S3ObjectStore(
            settings.s3_bucket,
            prefix=settings.s3_prefix,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
        )
    return LocalObjectStore(settings.storage_root)
