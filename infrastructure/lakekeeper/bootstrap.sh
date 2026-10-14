#!/bin/sh
# One-shot Lakekeeper setup. Safe to re-run:
#   1. bootstrap the server (first call accepts the terms of use; later calls are refused)
#   2. create the warehouse on RustFS unless it already exists
# Lakekeeper validates the storage profile on creation (it writes and deletes a test file).
set -eu

api="$LAKEKEEPER_URL/management/v1"
resp=/tmp/resp.json

# --- 1. bootstrap -------------------------------------------------------------
code=$(curl -sS -o "$resp" -w '%{http_code}' -X POST "$api/bootstrap" \
  -H 'Content-Type: application/json' -d '{"accept-terms-of-use": true}')
case "$code" in
  204) echo "lakekeeper bootstrapped" ;;
  4*) if grep -q 'CatalogAlreadyBootstrapped' "$resp"; then echo "lakekeeper already bootstrapped"
      else echo "bootstrap failed (HTTP $code):"; cat "$resp"; echo; exit 1; fi ;;
  *) echo "bootstrap failed (HTTP $code):"; cat "$resp"; echo; exit 1 ;;
esac

# --- 2. warehouse ---------------------------------------------------------------
curl -sS -f -o "$resp" "$api/warehouse"
if grep -q "\"name\":\"$WAREHOUSE\"" "$resp"; then
  echo "warehouse exists:  $WAREHOUSE"
  exit 0
fi

# sts-enabled: Lakekeeper calls STS AssumeRole on RustFS and hands short-lived credentials to
# clients that ask for them (DuckDB-WASM in the web UI). Trino keeps using its own static keys
# (vended-credentials-enabled=false in its catalog). Remote signing stays off.
# Changing this profile later needs `make reset`: this script only creates missing warehouses.
code=$(curl -sS -o "$resp" -w '%{http_code}' -X POST "$api/warehouse" \
  -H 'Content-Type: application/json' --data-binary @- <<EOF
{
  "warehouse-name": "$WAREHOUSE",
  "storage-profile": {
    "type": "s3",
    "bucket": "$S3_BUCKET",
    "region": "us-east-1",
    "endpoint": "$S3_ENDPOINT",
    "path-style-access": true,
    "flavor": "s3-compat",
    "sts-enabled": true,
    "sts-endpoint": "$S3_ENDPOINT",
    "remote-signing-enabled": false
  },
  "storage-credential": {
    "type": "s3",
    "credential-type": "access-key",
    "access-key-id": "$S3_ACCESS_KEY",
    "secret-access-key": "$S3_SECRET_KEY"
  }
}
EOF
)
if [ "$code" = "201" ]; then
  echo "warehouse created: $WAREHOUSE -> s3://$S3_BUCKET/"
else
  echo "warehouse creation failed (HTTP $code):"; cat "$resp"; echo; exit 1
fi
