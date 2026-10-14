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

aws s3 ls
