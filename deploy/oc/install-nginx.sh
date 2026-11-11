#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo 'Run with sudo from the Tencent console.' >&2
    exit 1
fi
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
available=/etc/nginx/sites-available/wbot-oc-rpa
enabled=/etc/nginx/sites-enabled/wbot-oc-rpa
domain=rpa.marswei.fun

command -v certbot >/dev/null
nginx -t
status=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:18892/api/oc/session)
if [[ "$status" != 401 ]]; then echo 'OC must require account login first.' >&2; exit 1; fi
if ! getent ahostsv4 "$domain" | awk '{print $1}' | grep -qx '124.223.173.147'; then
    echo 'Domain does not resolve to the expected server.' >&2
    exit 1
fi
if [[ -e "$enabled" && $(readlink -f "$enabled") != "$available" ]]; then
    echo 'The nginx site path is already owned by another configuration.' >&2
    exit 1
fi
backup=$(mktemp /etc/nginx/wbot-oc-backup.XXXXXX)
had_config=false
had_link=false
if [[ -f "$available" ]]; then cp -p -- "$available" "$backup"; had_config=true; fi
if [[ -L "$enabled" ]]; then had_link=true; fi

rollback() {
    if $had_config; then cp -p -- "$backup" "$available"; else rm -f -- "$available"; fi
    if ! $had_link; then rm -f -- "$enabled"; fi
    nginx -t && systemctl reload nginx
    echo 'OC nginx installation failed; previous site configuration restored.' >&2
}
trap rollback ERR

install -d -m 755 /var/www/wbot-acme
if [[ ! -f /etc/letsencrypt/live/rpa.marswei.fun/fullchain.pem ]]; then
    cat > "$available" <<'NGINX'
server {
    listen 80;
    listen [::]:80;
    server_name rpa.marswei.fun;
    location /.well-known/acme-challenge/ { root /var/www/wbot-acme; }
    location / { return 404; }
}
NGINX
    if [[ ! -L "$enabled" ]]; then ln -s -- "$available" "$enabled"; fi
    nginx -t
    systemctl reload nginx
    certbot certonly --webroot -w /var/www/wbot-acme -d "$domain" --non-interactive
fi

install -m 644 "$project_dir/deploy/oc/nginx-rpa.conf" "$available"
if [[ ! -L "$enabled" ]]; then ln -s -- "$available" "$enabled"; fi
nginx -t
systemctl reload nginx
install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/wbot-oc-nginx.sh <<'HOOK'
#!/usr/bin/env sh
nginx -t && systemctl reload nginx
HOOK
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/wbot-oc-nginx.sh
trap - ERR
echo 'OC HTTPS site enabled. Sign in using the initialized OC account.'
