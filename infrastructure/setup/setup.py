"""One-shot setup: everything a person would configure once, by hand, in the tools' own UIs/APIs.

Idempotent: re-running it changes nothing that is already right. It uses native features instead of
custom jobs where the tools have them:
  - RustFS lifecycle rules expire old raw files (no purge job)
  - Lakekeeper soft delete keeps dropped tables recoverable ("undrop") for 7 days, even after
    `DROP SCHEMA ... CASCADE`
Table protection is left as a hands-on demo in the Lakekeeper UI (README): protecting the gold
namespace instead protects nothing, because CASCADE drops the tables before the namespace (D-010).

Runs in the `setup` container with /opt/ingest-venv/bin/python (boto3 + PyIceberg).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from pyiceberg.catalog.rest import RestCatalog

S3_ENDPOINT = os.environ["S3_ENDPOINT"]                    # http://rustfs:9000 (inside the network)
WAREHOUSE_S3_ENDPOINT = "http://rustfs.localhost:9000"     # stored in the warehouse: also reachable by browsers
LAKEKEEPER = os.environ.get("LAKEKEEPER_URL", "http://lakekeeper:8181")
WAREHOUSE = "px4"
DAY = 86400

# bucket -> lifecycle rules (prefix, days after creation). RustFS's object scanner deletes expired objects.
LIFECYCLE = {
    "landing": [("px4/ulog/", 1),    # D-004: one day of raw ULogs (~9 GB/day uncapped)
                ("px4/index/", 7)],  # a week of raw index snapshots
    "reports": [("", 30)],           # rendered dashboards
    "lakehouse": [],                 # Iceberg files: never expire by age (snapshots manage them)
}
# Browser origins allowed to read Iceberg files (Lakekeeper UI's DuckDB-WASM preview)
CORS_BUCKET, CORS_ORIGINS = "lakehouse", ["http://localhost:8181", "http://127.0.0.1:8181"]
NAMESPACES = ["bronze", "silver", "gold", "audit"]
SOFT_DELETE_SECONDS = 7 * DAY


def log(msg: str) -> None:
    print(f"setup: {msg}", flush=True)


# --- RustFS ---------------------------------------------------------------------------------

def setup_storage() -> None:
    s3 = boto3.client("s3", endpoint_url=S3_ENDPOINT, region_name="us-east-1",
                      aws_access_key_id=os.environ["S3_ACCESS_KEY"],
                      aws_secret_access_key=os.environ["S3_SECRET_KEY"],
                      config=Config(s3={"addressing_style": "path"}))
    existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
    for bucket, rules in LIFECYCLE.items():
        if bucket not in existing:
            s3.create_bucket(Bucket=bucket)
            log(f"bucket created: s3://{bucket}")
        if rules:
            s3.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration={"Rules": [
                {"ID": f"expire-{(prefix.strip('/').replace('/', '-') or 'all')}-{days}d", "Status": "Enabled",
                 "Filter": {"Prefix": prefix}, "Expiration": {"Days": days}}
                for prefix, days in rules]})
            log(f"lifecycle on s3://{bucket}: " + ", ".join(f"{p or '*'} -> {d} d" for p, d in rules))
    s3.put_bucket_cors(Bucket=CORS_BUCKET, CORSConfiguration={"CORSRules": [{
        "AllowedOrigins": CORS_ORIGINS, "AllowedMethods": ["GET", "HEAD"], "AllowedHeaders": ["*"],
        "ExposeHeaders": ["ETag", "Content-Length", "Content-Range"], "MaxAgeSeconds": 3000}]})
    log(f"cors on s3://{CORS_BUCKET}: {', '.join(CORS_ORIGINS)} (GET, HEAD)")


# --- Lakekeeper -----------------------------------------------------------------------------

def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(LAKEKEEPER + path, method=method, headers={"Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw) if raw else {}


def setup_lakekeeper() -> None:
    code, resp = call("POST", "/management/v1/bootstrap", {"accept-terms-of-use": True})
    if code == 204:
        log("lakekeeper bootstrapped")
    elif resp.get("error", {}).get("type") != "CatalogAlreadyBootstrapped":
        raise RuntimeError(f"bootstrap failed ({code}): {resp}")

    delete_profile = {"type": "soft", "expiration-seconds": SOFT_DELETE_SECONDS}
    _, listing = call("GET", "/management/v1/warehouse")
    warehouse = next((w for w in listing.get("warehouses", []) if w["name"] == WAREHOUSE), None)
    if warehouse is None:
        code, resp = call("POST", "/management/v1/warehouse", {
            "warehouse-name": WAREHOUSE,
            # sts-enabled: Lakekeeper vends short-lived credentials to clients that ask (the UI's DuckDB);
            # Trino and PyIceberg bring their own keys. Validated on creation (writes a test object).
            "storage-profile": {"type": "s3", "bucket": "lakehouse", "region": "us-east-1",
                                "endpoint": WAREHOUSE_S3_ENDPOINT, "sts-endpoint": WAREHOUSE_S3_ENDPOINT,
                                "path-style-access": True, "flavor": "s3-compat", "sts-enabled": True,
                                "remote-signing-enabled": False},
            "storage-credential": {"type": "s3", "credential-type": "access-key",
                                   "access-key-id": os.environ["S3_ACCESS_KEY"],
                                   "secret-access-key": os.environ["S3_SECRET_KEY"]},
            "delete-profile": delete_profile,
        })
        if code != 201:
            raise RuntimeError(f"warehouse creation failed ({code}): {resp}")
        log(f"warehouse created: {WAREHOUSE} -> s3://lakehouse/ (soft delete, {SOFT_DELETE_SECONDS // DAY} d)")
    else:
        warehouse_id = warehouse["id"]
        if warehouse.get("delete-profile") != delete_profile:
            code, resp = call("POST", f"/management/v1/warehouse/{warehouse_id}/delete-profile",
                              {"delete-profile": delete_profile})
            if code != 200:
                raise RuntimeError(f"delete-profile update failed ({code}): {resp}")
            log(f"warehouse {WAREHOUSE}: delete profile set to soft, {SOFT_DELETE_SECONDS // DAY} d")
        else:
            log(f"warehouse exists: {WAREHOUSE} (soft delete, {SOFT_DELETE_SECONDS // DAY} d)")


def setup_namespaces() -> None:
    catalog = RestCatalog("px4", uri=f"{LAKEKEEPER}/catalog", warehouse=WAREHOUSE,
                          **{"header.X-Iceberg-Access-Delegation": "client-managed"})
    existing = {ns[0] for ns in catalog.list_namespaces()}
    for ns in NAMESPACES:
        if ns not in existing:
            # explicit location: otherwise Lakekeeper gives every namespace the warehouse root
            catalog.create_namespace(ns, {"location": f"s3://lakehouse/{ns}"})
            log(f"namespace created: {ns} -> s3://lakehouse/{ns}")


if __name__ == "__main__":
    setup_storage()
    setup_lakekeeper()
    setup_namespaces()
    log("done")
