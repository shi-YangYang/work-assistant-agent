#!/bin/sh
# Run as root on the deployment host. Certbot state and credentials stay outside Git.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
reload_marker=/var/lib/letsencrypt/paa-ip-reload-required

case "${1:-}" in
  reload)
    # Certbot reports hook errors but may still exit 0. Leave a marker until reload succeeds.
    umask 077
    touch "$reload_marker"
    docker compose --env-file "$repo_root/.env.company" \
      -f "$repo_root/deploy/company/compose.yml" \
      -f "$repo_root/deploy/company/compose.ip.yml" \
      exec -T web caddy reload --config /etc/caddy/Caddyfile.ip --adapter caddyfile --force
    rm "$reload_marker"
    ;;
  renew)
    shift
    # Retry a previous failed reload even when no new certificate is due yet.
    if [ -f "$reload_marker" ]; then
      "$0" reload
    fi
    status=0
    /opt/paa-certbot/bin/certbot renew --cert-name paa-ip --quiet \
      --deploy-hook "/bin/sh \"$repo_root/deploy/company/ip-certificate.sh\" reload" "$@" || status=$?
    if [ -f "$reload_marker" ]; then
      echo 'Certificate renewed but Caddy reload failed; run ip-certificate.sh reload after fixing the error.' >&2
      exit 1
    fi
    exit "$status"
    ;;
  *)
    echo 'Usage: ip-certificate.sh reload | renew [Certbot renewal options]' >&2
    exit 2
    ;;
esac
