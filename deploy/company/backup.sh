#!/bin/sh
# Run from repository root. Destination should be an operator-managed private backup volume.
set -eu
: "${PAA_BACKUP_DIR:?Set an existing private backup destination}"
[ -d "$PAA_BACKUP_DIR" ] || { echo 'Backup directory does not exist' >&2; exit 1; }
: "${PAA_MODEL_KEY_BACKUP_DIR:?Set a separate private master-key backup destination}"
[ -d "$PAA_MODEL_KEY_BACKUP_DIR" ] || { echo 'Master-key backup directory does not exist' >&2; exit 1; }
[ "$(cd "$PAA_MODEL_KEY_BACKUP_DIR" && pwd -P)" != "$(cd "$PAA_BACKUP_DIR" && pwd -P)" ] || { echo 'Keep key backups separate from database backups' >&2; exit 1; }
umask 077
compose() { docker compose --env-file .env.company -f deploy/company/compose.yml "$@"; }
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$PAA_BACKUP_DIR/company-$stamp"
mkdir "$target"
key_target="$PAA_MODEL_KEY_BACKUP_DIR/company-$stamp"
mkdir "$key_target"
# A maintenance window stops writers; in-flight uncertain paid jobs retain the durable retry boundary.
compose stop -t 190 web api worker
trap 'compose start api worker web' EXIT INT TERM
compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$target/database.dump"
compose run --rm --no-deps --user root -T --entrypoint sh api -c 'tar -C /data/media -cf - .' > "$target/media.tar"
compose run --rm --no-deps -T --entrypoint cat api /run/paa/model-master.key > "$key_target/model-master.key"
[ "$(wc -c < "$key_target/model-master.key" | tr -d ' ')" = 32 ] || { echo 'Invalid master-key backup' >&2; exit 1; }
(cd "$key_target" && sha256sum model-master.key > SHA256SUMS)
compose images --format json > "$target/images.json"
(cd "$target" && sha256sum database.dump media.tar > SHA256SUMS)
# Only complete backups created by this script are eligible for retention pruning.
python3 - "$PAA_BACKUP_DIR" <<'PY'
from pathlib import Path
import shutil, sys
backups=sorted(p for p in Path(sys.argv[1]).glob('company-*') if p.is_dir() and (p/'SHA256SUMS').is_file())
for backup in backups[:-7]:
    shutil.rmtree(backup)
PY
printf 'Backup complete: %s\n' "$target"
