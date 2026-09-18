#!/bin/bash
# Runs on the deployment host after a trusted main release has been uploaded.
set -euo pipefail
umask 077
root=${1:?Usage: release.sh deployment-root release-id domain|ip}
release_id=${2:?Missing release id}
mode=${3:?Missing deployment mode}
[[ "$root" =~ ^/[a-zA-Z0-9_/-]+$ && "$root" != / ]] || { echo 'Invalid deployment root' >&2; exit 1; }
[[ "$release_id" =~ ^[a-f0-9]{40}-[0-9]+-[0-9]+$ ]] || { echo 'Invalid release id' >&2; exit 1; }
[[ "$mode" == domain || "$mode" == ip ]] || { echo 'Invalid deployment mode' >&2; exit 1; }
[[ $(uname -m) == x86_64 ]] || { echo 'This release requires a Linux x86_64 server' >&2; exit 1; }
release="$root/releases/$release_id"
[[ -f "$root/.env.company" && -f "$release/deploy/company/build.sh" ]] || { echo 'Missing server environment or release source' >&2; exit 1; }
exec 9>"$root/.deploy.lock"
flock -n 9 || { echo 'Another deployment is running' >&2; exit 1; }
# Build and download before touching the running release. The manifest pins local image IDs.
bash "$release/deploy/company/build.sh" "$release" "$release_id" "$mode"
ln -s "$root/.env.company" "$release/.env.company"
compose() { PAA_COMPOSE_ROOT="$release" sh "$release/deploy/company/compose.sh" "$@"; }
compose config --quiet
compose pull postgres
# Check the server-owned key and origin before touching the running services.
compose run --rm --no-deps -T --entrypoint python api -c '
import os
from urllib.parse import urlparse
assert len(open(os.environ["PAA_MODEL_KEY_FILE"], "rb").read()) == 32, "Invalid master key"
url = urlparse(os.environ["PAA_WEB_ORIGIN"])
assert url.scheme == "https" and url.hostname and not url.username and not url.password and url.path in ("", "/") and not url.query and not url.fragment, "Invalid production Web origin"
'
previous=''
if docker volume inspect paa-company_pgdata >/dev/null 2>&1; then
  if [[ -L "$root/current" ]]; then
    previous=$(readlink -f "$root/current")
  elif [[ -f "$root/deploy/company/compose.yml" ]]; then
    previous=$root
  else
    echo 'Existing database found without a deployment directory; adopt the existing installation before deploying.' >&2
    exit 1
  fi
fi
if [[ -n "$previous" ]]; then
  mkdir -p "$root/backups" "$root/key-backups"
  chmod 700 "$root/backups" "$root/key-backups"
  PAA_COMPOSE_ROOT="$previous" PAA_DEPLOY_MODE="$mode" \
    PAA_BACKUP_DIR="$root/backups" PAA_MODEL_KEY_BACKUP_DIR="$root/key-backups" \
    sh "$release/deploy/company/backup.sh" --keep-stopped
  ln -s "$previous" "$root/.previous-next"
  mv -Tf "$root/.previous-next" "$root/previous"
fi
# current describes the attempted release even if migration fails, so recovery commands
# use the correct images and schema. Never automatically restart older code after migration.
ln -s "$release" "$root/.current-next"
mv -Tf "$root/.current-next" "$root/current"
finish() {
  code=$?
  if [[ $code -ne 0 ]]; then
    compose stop -t 190 web api worker || true
    printf 'failed\n' > "$release/deployment-status"
    echo "Deployment failed; application services stopped. Inspect $release; database and backups are retained." >&2
  fi
  exit "$code"
}
trap finish EXIT
trap 'exit 1' HUP INT TERM
printf 'deploying\n' > "$release/deployment-status"
compose up -d --no-build --wait --wait-timeout 90 postgres
compose run --rm --no-deps -T migrate
compose up -d --no-build --no-deps api worker web
# The API health endpoint checks PostgreSQL; test the actual HTTPS entry, without -k.
origin=$(compose exec -T api python -c 'import os; print(os.environ["PAA_WEB_ORIGIN"].rstrip("/"))')
[[ "$origin" =~ ^https://[a-zA-Z0-9.:-]+$ ]] || { echo 'Invalid production Web origin' >&2; exit 1; }
for attempt in {1..12}; do
  if curl --fail --silent --show-error --connect-timeout 5 --max-time 10 "$origin/api/v1/health" \
    | python3 -c 'import json,sys; assert json.load(sys.stdin).get("status") == "ready"'; then
    break
  fi
  [[ "$attempt" -lt 12 ]] || exit 1
  sleep 5
done
curl --fail --silent --show-error --connect-timeout 5 --max-time 15 "$origin/" \
  | python3 -c 'import sys; assert "<html" in sys.stdin.read().lower()'
compose exec -T worker python -c 'import os; assert b"paa_server.worker" in open("/proc/1/cmdline", "rb").read()'
printf 'ready\n' > "$release/deployment-status"
printf 'Deployment ready: %s\n' "$release_id"
