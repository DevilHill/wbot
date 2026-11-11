#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run this script with sudo.' >&2; exit 1; fi
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
site=/etc/nginx/sites-available/wbot-oc-rpa
test -f "$site"
nginx -t
status=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:18892/api/oc/session)
if [[ "$status" != 401 ]]; then echo 'OC must require account login before removing Basic Auth.' >&2; exit 1; fi
backup=$(mktemp /etc/nginx/wbot-oc-account-backup.XXXXXX)
cp -p -- "$site" "$backup"
rollback() { cp -p -- "$backup" "$site"; nginx -t && systemctl reload nginx; }
trap rollback ERR
install -m 644 "$project_dir/deploy/oc/nginx-rpa.conf" "$site"
nginx -t
systemctl reload nginx
trap - ERR
echo 'OC account login enabled; previous nginx configuration retained in a backup file.'
