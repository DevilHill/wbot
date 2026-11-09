"""供 Node 客户端验收使用的隔离 Assistant 与 OC 实例。"""
import json
from pathlib import Path
import sys
import threading
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.assistant.connection import ConnectionService
from app.assistant.execution import ExecutionService
from app.assistant.server import create_server as assistant_server
from app.oc.agent_server import create_agent_server
from app.oc.server import create_server as oc_server
from app.oc.service import OcService
from wbot.elements import ElementLibrary


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdin.reconfigure(encoding='utf-8')
    directory = Path(sys.argv[1]).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    oc = OcService(directory / 'oc')
    execution = ExecutionService(directory / 'assistant')
    connection = ConnectionService(directory / 'assistant', execution)
    gateway = create_agent_server(oc, port=0)
    web = directory / 'web'
    web.mkdir()
    (web / 'index.html').write_text('<title>Shared elements API fixture</title>', encoding='utf-8')
    management = oc_server(oc, web, port=0)
    assistant = assistant_server(execution, connection=connection)
    servers = [gateway, management, assistant]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    try:
        identity = connection.connect(gateway.origin, 'VS Code 集成测试开发机')
        connection.synchronize()
        oc.agents.decide(identity['device_id'], 'approve')
        connection.synchronize()
        metadata = {'url': assistant.origin, 'token': assistant.token}
        (directory / 'assistant' / 'service.json').write_text(json.dumps(metadata), encoding='utf-8')
        repository = oc.elements.create_repository({'name': '集成测试共享页面', 'request_id': uuid4().hex,
            'items': [{'id': 'search', 'name': '搜索框', 'group': '首页', 'xpath': '//input',
                       'url': 'https://example.test', 'frame': None, 'description': ''}]})
        library = ElementLibrary(directory / 'elements.sqlite3')
        print(json.dumps({'assistant_dir': str(directory / 'assistant'), 'library_path': str(library.path),
                          'repository_id': repository['id'], 'admin_url': management.origin}), flush=True)
        for line in sys.stdin:
            command = json.loads(line)
            if command['action'] == 'stop':
                break
            if command['action'] == 'edit':
                record = library.get('search')
                record['xpath'] = command['xpath']
                result = library.upsert(record)
            elif command['action'] == 'items':
                result = library.list()
            else:
                raise ValueError('Unknown fixture action')
            print(json.dumps({'result': result}, ensure_ascii=False), flush=True)
    finally:
        connection.close()
        execution.shutdown()
        for server, thread in zip(servers, threads):
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    main()
