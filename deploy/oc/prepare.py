"""在部署目录生成独立随机密码；不覆盖现有配置或打印密码。"""
import os
from pathlib import Path
import secrets


def main():
    directory = Path(__file__).resolve().parents[2]
    target = directory / '.env'
    if target.exists():
        print('Existing .env retained')
        return
    content = ('POSTGRES_PASSWORD=' + secrets.token_urlsafe(32) + '\n'
               'REDIS_PASSWORD=' + secrets.token_urlsafe(32) + '\n'
               'OC_IMAGE=wbot-oc:20261111-pg-v1\n'
               'OC_AGENT_DOMAIN=rpa.marswei.fun\n')
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(content)
    print('Created private .env; credentials were not printed')


if __name__ == '__main__':
    main()
