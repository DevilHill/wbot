"""下载固定版本的 Monaco 离线资源，核对 npm SHA-512，不执行 npm 脚本。"""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

VERSION = '0.57.0'
ROOT = Path(__file__).resolve().parents[1]


def main():
    metadata = json.load(urllib.request.urlopen(f'https://registry.npmjs.org/monaco-editor/{VERSION}', timeout=30))
    raw = urllib.request.urlopen(metadata['dist']['tarball'], timeout=90).read()
    assert metadata['dist']['integrity'] == 'sha512-' + base64.b64encode(hashlib.sha512(raw).digest()).decode()
    dest = ROOT / 'app/web/vendor/monaco'
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        for member in archive.getmembers():
            if not member.isfile(): continue
            name = member.name
            if name.startswith('package/min/vs/') and not name.endswith('.map'):
                relative = name.removeprefix('package/min/')
            elif name in ('package/LICENSE', 'package/ThirdPartyNotices.txt'):
                relative = name.removeprefix('package/')
            else: continue
            target = (dest / relative).resolve()
            assert target.is_relative_to(dest.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
            count += 1
    (dest / 'VERSION.json').write_text(json.dumps({'version': VERSION, 'integrity': metadata['dist']['integrity'],
        'source': metadata['dist']['tarball']}, indent=2), encoding='utf-8')
    print(f'Monaco {VERSION}: {count} offline assets, SHA-512 verified.')


if __name__ == '__main__': main()
