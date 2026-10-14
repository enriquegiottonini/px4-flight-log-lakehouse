#!/bin/sh
# Creates the lakehouse buckets on RustFS. Safe to re-run: existing buckets are left alone.
set -eu

for bucket in $BUCKETS; do
  if aws s3api head-bucket --bucket "$bucket" 2>/dev/null; then
    echo "bucket exists:  s3://$bucket"
  else
    aws s3api create-bucket --bucket "$bucket" >/dev/null
    echo "bucket created: s3://$bucket"
  fi
done

# Read-only CORS for browser clients (re-applied every run, so edits to CORS_ORIGINS take effect).
if [ -n "${CORS_BUCKET:-}" ]; then
  origins=$(printf '"%s",' $CORS_ORIGINS | sed 's/,$//')
  aws s3api put-bucket-cors --bucket "$CORS_BUCKET" --cors-configuration "{
    \"CORSRules\": [{
      \"AllowedOrigins\": [$origins],
      \"AllowedMethods\": [\"GET\", \"HEAD\"],
      \"AllowedHeaders\": [\"*\"],
      \"ExposeHeaders\": [\"ETag\", \"Content-Length\", \"Content-Range\"],
      \"MaxAgeSeconds\": 3000
    }]
  }"
  echo "cors applied:   s3://$CORS_BUCKET <- $CORS_ORIGINS (GET, HEAD)"
fi

aws s3 ls
