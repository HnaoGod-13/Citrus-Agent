"""Private immutable attachments, stored locally or through an S3-compatible API."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import socket
import struct
import tempfile

from app.platform_db import runtime_dir


class BlobStore:
    def __init__(self, root=None, *, backend=None, client=None, bucket=None):
        self.backend = backend or os.getenv("CITRUS_BLOB_BACKEND", "local")
        self.root = Path(root or os.getenv("CITRUS_BLOB_DIR") or runtime_dir() / "attachments").resolve()
        self.bucket = bucket or os.getenv("CITRUS_S3_BUCKET", "")
        self.client = client
        if self.backend not in {"local", "s3"}:
            raise ValueError("附件存储类型无效。")
        if self.backend == "s3":
            if not self.bucket:
                raise ValueError("尚未配置附件存储桶。")
            if self.client is None:
                import boto3
                from botocore.config import Config
                self.client = boto3.client("s3", endpoint_url=os.getenv("CITRUS_S3_ENDPOINT") or None,
                    region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
                    config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}))

    @staticmethod
    def validate_key(key):
        if not re.fullmatch(r"org_[a-f0-9]{32}/[a-f0-9]{64}\.(pdf|png|jpg|jpeg)", key):
            raise ValueError("附件引用无效。")
        return key

    def _path(self, key):
        result = (self.root / self.validate_key(key)).resolve()
        if not result.is_relative_to(self.root):
            raise ValueError("附件路径无效。")
        return result

    @staticmethod
    def scan(raw):
        host = os.getenv("CITRUS_CLAMAV_HOST", "")
        if not host:
            if os.getenv("CITRUS_ENV", "").strip().lower() == "production":
                raise ValueError("文件扫描服务尚未配置，暂不能保存附件。")
            return "not_scanned"
        try:
            with socket.create_connection((host, int(os.getenv("CITRUS_CLAMAV_PORT", "3310"))), timeout=15) as sock:
                sock.sendall(b"zINSTREAM\x00")
                for offset in range(0, len(raw), 65536):
                    chunk = raw[offset:offset + 65536]
                    sock.sendall(struct.pack("!I", len(chunk)) + chunk)
                sock.sendall(struct.pack("!I", 0))
                reply = b""
                while not reply.endswith(b"\x00") and len(reply) < 4096:
                    chunk = sock.recv(1024)
                    if not chunk:
                        break
                    reply += chunk
            if reply.rstrip(b"\x00\r\n") != b"stream: OK":
                raise ValueError("附件未通过文件扫描，请检查文件后重试。")
            return "clean"
        except OSError as exc:
            raise ValueError("文件扫描服务不可用，请稍后重试。") from exc

    def put(self, organization_id, name, raw):
        suffix = Path(name).suffix.lower()
        digest = hashlib.sha256(raw).hexdigest()
        key = self.validate_key(f"{organization_id}/{digest}{suffix}")
        scan = self.scan(raw)
        if self.backend == "local":
            target = self._path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as fp:
                fp.write(raw)
                temp = Path(fp.name)
            try:
                temp.replace(target)
            finally:
                temp.unlink(missing_ok=True)
        else:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=raw,
                ContentType={".pdf":"application/pdf", ".png":"image/png", ".jpg":"image/jpeg", ".jpeg":"image/jpeg"}[suffix])
        return {"key": key, "sha256": digest, "size": len(raw), "name": name, "scan": scan}

    def read(self, item):
        key = self.validate_key(item["key"])
        try:
            if self.backend == "local":
                raw = self._path(key).read_bytes()
            else:
                stream = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
                try:
                    raw = stream.read(3 * 1024 * 1024 + 1)
                finally:
                    stream.close()
        except Exception as exc:
            raise ValueError("附件暂时无法读取，请联系管理员检查存储。") from exc
        if len(raw) != item["size"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("附件校验失败，请从备份恢复。")
        return raw
