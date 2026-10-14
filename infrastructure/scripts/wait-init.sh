#!/usr/bin/env bash
# Wait for one-shot init services to finish and fail if any exited non-zero.
# `docker compose up --wait` doesn't cover these: it returns while they are still running,
# and `docker compose wait` ignores containers that have already exited.
#   usage: scripts/wait-init.sh rustfs-init [other-init ...]
set -euo pipefail
TIMEOUT=${INIT_TIMEOUT:-180}

for svc in "$@"; do
  cid=$(docker compose ps -a -q "$svc")
  [[ -n "$cid" ]] || { echo "init job '$svc' has no container (was it started?)"; exit 1; }
  for ((i = 0; i < TIMEOUT; i++)); do
    read -r status code < <(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' "$cid")
    [[ "$status" == "exited" ]] && break
    sleep 1
  done
  if [[ "$status" != "exited" ]]; then
    echo "init job '$svc' still $status after ${TIMEOUT}s"; exit 1
  elif [[ "$code" != "0" ]]; then
    echo "init job '$svc' failed with exit code $code:"; docker compose logs --no-log-prefix "$svc" | tail -20; exit 1
  fi
  echo "init job '$svc' completed"
done
