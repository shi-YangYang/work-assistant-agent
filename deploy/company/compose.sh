#!/bin/sh
# One entry point for source installations and image-based releases.
set -eu
repo_root=${PAA_COMPOSE_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}
env_file="$repo_root/apps/server/.env.web"
# Backup/recovery can target a release created before the environment-file move.
if [ ! -f "$env_file" ] && [ -f "$repo_root/.env.company" ]; then
  env_file="$repo_root/.env.company"
fi
mode=${PAA_DEPLOY_MODE:-domain}
if [ -f "$repo_root/.release.env" ]; then
  mode=$(sed -n 's/^PAA_DEPLOY_MODE=//p' "$repo_root/.release.env")
fi
case "$mode" in
  domain) ;;
  ip) set -- -f "$repo_root/deploy/company/compose.ip.yml" "$@" ;;
  *) echo 'Deployment mode must be domain or ip' >&2; exit 1 ;;
esac
if [ -f "$repo_root/.release.env" ]; then
  set -- --env-file "$repo_root/.release.env" -f "$repo_root/deploy/company/compose.release.yml" "$@"
fi
exec docker compose -p paa-company --env-file "$env_file" \
  -f "$repo_root/deploy/company/compose.yml" "$@"
