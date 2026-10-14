"""Landing zone on RustFS (S3 API via boto3, path-style)."""

from __future__ import annotations

from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from drone_ingest.config import Settings


def s3_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 5, "mode": "standard"},
                      max_pool_connections=64),  # parallel downloads x multipart upload threads
    )


def head(client, bucket: str, key: str) -> dict | None:
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def list_prefixes(client, bucket: str, prefix: str) -> list[str]:
    """Immediate "sub-folders" under prefix, e.g. px4/ulog/log_date=2026-10-13/."""
    out: list[str] = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        out += [p["Prefix"] for p in page.get("CommonPrefixes", [])]
    return sorted(out)


def list_keys(client, bucket: str, prefix: str) -> list[dict]:
    out: list[dict] = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        out += page.get("Contents", [])
    return out


def delete_prefix(client, bucket: str, prefix: str) -> tuple[int, int]:
    """Delete every object under prefix. Returns (objects, bytes) deleted."""
    objects = list_keys(client, bucket, prefix)
    for i in range(0, len(objects), 1000):
        chunk = objects[i:i + 1000]
        client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": o["Key"]} for o in chunk], "Quiet": True})
    return len(objects), sum(o["Size"] for o in objects)


def put_file(client, bucket: str, key: str, path: Path, metadata: dict[str, str] | None = None) -> None:
    client.upload_file(str(path), bucket, key, ExtraArgs={"Metadata": metadata or {}})


def put_bytes(client, bucket: str, key: str, data: bytes, content_type: str = "application/json") -> None:
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


def get_file(client, bucket: str, key: str, path: Path) -> None:
    client.download_file(bucket, key, str(path))


def get_bytes(client, bucket: str, key: str) -> bytes:
    return client.get_object(Bucket=bucket, Key=key)["Body"].read()
