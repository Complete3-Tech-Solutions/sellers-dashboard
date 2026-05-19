"""Object storage abstraction. Uses Cloudflare R2 (S3-compatible) when R2 env vars
are set; falls back to local-disk storage under ``./data/storage`` otherwise, so
the app boots in dev / Railway free-tier without external credentials."""
from __future__ import annotations

import io
import os
import pathlib
from functools import lru_cache

from app.settings import settings


def _local_root() -> pathlib.Path:
    root = pathlib.Path(os.environ.get("LOCAL_STORAGE_DIR", "./data/storage")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _use_r2() -> bool:
    return bool(
        settings.r2_endpoint_url
        and settings.r2_access_key_id
        and settings.r2_secret_access_key
    )


@lru_cache
def _client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        region_name="auto",
    )


def put_bytes(key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
    if _use_r2():
        _client().put_object(
            Bucket=settings.r2_bucket, Key=key, Body=body, ContentType=content_type
        )
        return
    target = _local_root() / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)


def get_bytes(key: str) -> bytes:
    if _use_r2():
        obj = _client().get_object(Bucket=settings.r2_bucket, Key=key)
        return obj["Body"].read()
    return (_local_root() / key).read_bytes()


def stream_to_buffer(key: str) -> io.BytesIO:
    return io.BytesIO(get_bytes(key))


def delete(key: str) -> None:
    if _use_r2():
        _client().delete_object(Bucket=settings.r2_bucket, Key=key)
        return
    target = _local_root() / key
    if target.exists():
        target.unlink()


def object_exists(key: str) -> bool:
    if _use_r2():
        try:
            _client().head_object(Bucket=settings.r2_bucket, Key=key)
            return True
        except Exception:
            return False
    return (_local_root() / key).exists()
