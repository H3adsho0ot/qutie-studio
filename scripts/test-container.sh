#!/usr/bin/env bash
set -euo pipefail

image="${1:-qutie-studio:test}"
container="qutie-studio-smoke-${GITHUB_RUN_ID:-$$}"
volume="${container}-data"
port="${QUTIE_TEST_PORT:-18765}"

cleanup() {
  result=$?
  if [ "$result" -ne 0 ]; then docker logs --tail 80 "$container" || true; fi
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  exit "$result"
}
trap cleanup EXIT

docker volume create "$volume" >/dev/null
docker run --detach --name "$container" \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true \
  --publish "127.0.0.1:${port}:8765" \
  --mount "type=volume,source=${volume},target=/data" "$image" >/dev/null

docker exec "$container" python -c "import os, pathlib; assert os.getuid() == 10001; assert not any(pathlib.Path(p).exists() for p in ['/app/.git', '/app/.local', '/app/data', '/app/.env', '/app/tests'])"
python scripts/container_smoke.py --url "http://127.0.0.1:${port}" --phase write
docker restart "$container" >/dev/null
python scripts/container_smoke.py --url "http://127.0.0.1:${port}" --phase read
