#!/bin/bash
# The token arrives only on stdin; the selected release never receives it as an argument.
set -euo pipefail
registry_user=${1:?Usage: with-registry-auth.sh registry-user command [args...]}
shift
[[ $# -gt 0 ]] || { echo 'Missing deployment command' >&2; exit 1; }
umask 077
registry_config=$(mktemp -d "${TMPDIR:-/tmp}/paa-registry.XXXXXX")
trap 'rm -rf -- "$registry_config"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
export DOCKER_CONFIG="$registry_config"
docker login ghcr.io --username "$registry_user" --password-stdin
"$@" </dev/null
