#!/bin/bash
# Build without starting services or accessing production credentials.
set -euo pipefail
umask 077
release=${1:?Usage: build.sh source-directory release-id domain|ip}
release_id=${2:?Missing release id}
mode=${3:?Missing deployment mode}
[[ "$release_id" =~ ^[a-f0-9]{40}-[0-9]+-[0-9]+$ ]] || { echo 'Invalid release id' >&2; exit 1; }
[[ "$mode" == domain || "$mode" == ip ]] || { echo 'Invalid deployment mode' >&2; exit 1; }
[[ -f "$release/deploy/company/Dockerfile" && ! -e "$release/.release.env" ]] || { echo 'Missing source or release already built' >&2; exit 1; }
docker buildx version >/dev/null || { echo 'Install the Docker Buildx plugin before deploying' >&2; exit 1; }
export DOCKER_BUILDKIT=1
manifest="$release/.release.env.tmp"
trap 'rm -f "$manifest"' EXIT
: > "$manifest"
# Serialize builds on small servers; shared service layers stay in Docker's build cache.
for target in service worker web; do
  image="paa-company/$target:$release_id"
  docker build --progress=plain --file "$release/deploy/company/Dockerfile" \
    --target "$target" --tag "$image" "$release"
  image_id=$(docker image inspect --format '{{.Id}}' "$image")
  [[ "$image_id" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo "Invalid $target image ID" >&2; exit 1; }
  printf 'PAA_%s_IMAGE=%s\n' "$(printf '%s' "$target" | tr '[:lower:]' '[:upper:]')" "$image_id" >> "$manifest"
done
printf 'PAA_DEPLOY_MODE=%s\n' "$mode" >> "$manifest"
mv "$manifest" "$release/.release.env"
