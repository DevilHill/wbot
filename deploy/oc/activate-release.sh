#!/usr/bin/env bash
# Called over verified SSH by GitHub Actions; only OC is replaced, data volumes are retained.
set -euo pipefail
umask 077
revision=${1:?Git commit required}
[[ "$revision" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid revision' >&2; exit 1; }
project_dir="$HOME/wbot-oc"
release="$project_dir/releases/$revision"
cd "$project_dir"
exec 9>deploy.lock
flock -w 600 9
test -f "$release/image.tar.gz"
test -f "$release/compose.yml"
image="wbot-oc:$revision"
docker load -i "$release/image.tar.gz"
OC_IMAGE="$image" docker compose --env-file .env -f "$release/compose.yml" config --quiet
backup="$project_dir/backups/$(date -u +%Y%m%dT%H%M%SZ)-$revision"
mkdir -p "$backup"
cp .env "$backup/deployment.env"
cp deploy/oc/compose.yml "$backup/compose.yml"
finished=false
rollback() {
    if ! $finished; then
        cp "$backup/deployment.env" .env
        cp "$backup/compose.yml" deploy/oc/compose.yml
        docker compose --env-file .env -f deploy/oc/compose.yml up -d --no-build --pull never oc
        echo 'Deployment failed; previous application image restored. Database was not rolled back.' >&2
    fi
}
trap rollback EXIT
docker compose --env-file .env -f deploy/oc/compose.yml stop oc
docker compose --env-file .env -f deploy/oc/compose.yml exec -T postgres pg_dump -U wbot -d wbot -Fc > "$backup/database.dump"
docker compose --env-file .env -f deploy/oc/compose.yml run --rm --no-deps --entrypoint python oc -c "import sys,tarfile; archive=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); archive.add('/data',arcname='data'); archive.close()" > "$backup/files.tar.gz"
python3 - "$image" <<'PYTHON'
from pathlib import Path
import sys
path = Path('.env')
lines = [line for line in path.read_text().splitlines() if not line.startswith('OC_IMAGE=')]
pending = path.with_name('.env.pending')
pending.write_text('\n'.join(lines + ['OC_IMAGE=' + sys.argv[1]]) + '\n')
pending.chmod(0o600)
pending.replace(path)
PYTHON
cp "$release/compose.yml" deploy/oc/compose.yml
docker compose --env-file .env -f deploy/oc/compose.yml up -d --no-build --pull never oc
for attempt in {1..60}; do
    state=$(docker inspect --format '{{.State.Health.Status}}' wbot-oc-oc-1)
    if [[ "$state" == healthy ]]; then break; fi
    sleep 2
done
[[ "$state" == healthy ]]
status=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:18892/api/oc/session)
[[ "$status" == 401 ]]
printf '%s\n' "$revision" > deployed.sha
finished=true
echo "Deployed $revision; backups saved under $backup"
# Remove only this uploaded archive; the tagged image and rollback backup remain available.
rm -- "$release/image.tar.gz"
