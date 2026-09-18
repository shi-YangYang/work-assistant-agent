#!/bin/bash
# Transfer a tracked-source snapshot into a new release, reusing completed releases.
set -euo pipefail
source_dir=${1:?Usage: upload.sh source-directory ssh-target deployment-root release-id [ssh-options...]}
target=${2:?Missing SSH target}
root=${3:?Missing deployment root}
release_id=${4:?Missing release id}
shift 4
ssh_options=("$@")
[[ -d "$source_dir" && -f "$source_dir/package.json" ]] || { echo 'Missing source snapshot' >&2; exit 1; }
[[ "$target" =~ ^[a-z_][a-z0-9_-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || { echo 'Invalid SSH target' >&2; exit 1; }
[[ "$root" =~ ^/[a-zA-Z0-9_/-]+$ && "$root" != / ]] || { echo 'Invalid deployment root' >&2; exit 1; }
[[ "$release_id" =~ ^[a-f0-9]{40}-[0-9]+-[0-9]+$ ]] || { echo 'Invalid release id' >&2; exit 1; }
command -v rsync >/dev/null || { echo 'Install rsync on the deployment runner' >&2; exit 1; }
directory="$root/releases/$release_id"
basis=$(ssh "${ssh_options[@]}" "$target" bash -s -- "$root" "$release_id" <<'REMOTE'
set -euo pipefail
command -v rsync >/dev/null || { echo 'Install rsync on the server' >&2; exit 1; }
mkdir -p "$1/releases"
mkdir -m 700 "$1/releases/$2"
python3 - "$1/releases" <<'PY'
from pathlib import Path
import re, sys
candidates = []
for path in Path(sys.argv[1]).iterdir():
    if path.is_symlink() or not re.fullmatch(r'[a-f0-9]{40}-[0-9]+-[0-9]+', path.name):
        continue
    if not (path / 'package.json').is_file() or not (path / 'deploy/company/Dockerfile').is_file():
        continue
    # .release.env also supports complete snapshots from the previous archive-based CD.
    for name in ('.source-complete', '.release.env'):
        marker = path / name
        if marker.is_file():
            candidates.append((marker.stat().st_mtime_ns, str(path)))
            break
print(max(candidates)[1] if candidates else '')
PY
REMOTE
)
reuse=()
if [[ -n "$basis" ]]; then
  [[ "$basis" == "$root/releases/"* && "$basis" != "$directory" ]] || { echo 'Invalid source basis' >&2; exit 1; }
  reuse=(--copy-dest="$basis")
  echo "Reusing source files from ${basis##*/}"
else
  echo 'No complete source snapshot on server; uploading the first copy'
fi
# Ignore Git archive mtimes: identical content must be reused across different commits.
# Copy instead of hard-linking so a later build cannot alter a previous release.
printf -v transport '%q ' ssh "${ssh_options[@]}"
echo 'Uploading source (progress and transfer totals below)'
rsync -rlpcz --timeout=120 --info=progress2 --outbuf=L --human-readable --stats \
  "${reuse[@]}" --rsh="$transport" -- "$source_dir/" "$target:$directory/"
ssh "${ssh_options[@]}" "$target" "chmod 700 '$directory' && touch '$directory/.source-complete'"
echo 'Source upload complete'
