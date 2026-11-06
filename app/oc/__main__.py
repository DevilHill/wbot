"""启动独立的 OC 本机预览；停止 OC 不终止 Assistant 作业。"""
import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import webbrowser

from app.assistant.lifecycle import ServiceLock, _read_metadata, _request
from .agent_server import create_agent_server
from .server import create_server
from .service import OcService


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEB_DIR = ROOT / 'oc-web' / 'dist'


def service_status(state_dir):
    metadata = _read_metadata(state_dir)
    if metadata is None:
        return {'running': False}
    try:
        health = _request(metadata, '/api/oc/health')
    except (OSError, ValueError):
        return {'running': False}
    if not isinstance(health, dict) or health.get('product') != 'wbot-oc':
        return {'running': False}
    return {'running': True, 'url': metadata['url'], 'pid': metadata.get('pid'),
            'agent_gateway': metadata.get('agent_gateway')}


def start_service(state_dir, port=8792, web_dir=DEFAULT_WEB_DIR, *, agent_host='127.0.0.1',
                  agent_port=8793, agent_cert=None, agent_key=None):
    state_dir = Path(state_dir).resolve()
    existing = service_status(state_dir)
    if existing['running']:
        return existing
    web_dir = Path(web_dir).resolve()
    if not (web_dir / 'index.html').is_file():
        raise ValueError('找不到 OC 前端构建，请先在 oc-web 中执行 npm ci 和 npm run build')
    state_dir.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-m', 'app.oc', 'serve', '--state-dir', str(state_dir),
               '--port', str(port), '--web-dir', str(web_dir),
               '--agent-host', agent_host, '--agent-port', str(agent_port)]
    if bool(agent_cert) != bool(agent_key):
        raise ValueError('agent TLS 证书与私钥必须同时提供')
    if agent_cert:
        command.extend(['--agent-cert', str(Path(agent_cert).resolve()),
                        '--agent-key', str(Path(agent_key).resolve())])
    options = {'cwd': ROOT, 'stdin': subprocess.DEVNULL, 'close_fds': True}
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    with (state_dir / 'service.log').open('ab') as log:
        child = subprocess.Popen(command, stdout=log, stderr=log, **options)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        status = service_status(state_dir)
        if status['running']:
            return status
        if child.poll() is not None:
            raise RuntimeError(f'OC 启动失败，请查看 {state_dir / "service.log"}')
        time.sleep(0.1)
    child.terminate()
    child.wait(timeout=5)
    raise RuntimeError(f'OC 启动超时，请查看 {state_dir / "service.log"}')


def stop_service(state_dir):
    if not service_status(state_dir)['running']:
        return {'running': False, 'stopped': False}
    _request(_read_metadata(state_dir), '/api/oc/service/stop', {})
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if not (Path(state_dir) / 'service.json').exists():
            return {'running': False, 'stopped': True}
        time.sleep(0.1)
    raise RuntimeError('OC 仍在停止，请稍后查看状态；Assistant 作业独立运行')


def serve(state_dir, port=8792, web_dir=DEFAULT_WEB_DIR, *, agent_host='127.0.0.1',
          agent_port=8793, agent_cert=None, agent_key=None):
    state_dir = Path(state_dir).resolve()
    lock = ServiceLock(state_dir)
    try:
        lock.__enter__()
    except RuntimeError as exc:
        raise RuntimeError('该数据目录已有后台服务，请使用独立 OC 目录或连接现有 OC') from exc
    server = None
    gateway = None
    gateway_thread = None
    metadata_path = state_dir / 'service.json'
    try:
        service = OcService(state_dir)
        server = create_server(service, web_dir, port)
        gateway = create_agent_server(service, agent_host, agent_port, agent_cert, agent_key)
        server.agent_gateway = gateway.connection_info()
        gateway_thread = threading.Thread(target=gateway.serve_forever,
                                          kwargs={'poll_interval': 0.2}, daemon=True)
        gateway_thread.start()
        metadata = {'url': server.origin, 'pid': os.getpid(), 'token': server.token,
                    'agent_gateway': server.agent_gateway}
        pending = metadata_path.with_suffix('.tmp')
        pending.write_text(json.dumps(metadata), encoding='utf-8')
        pending.replace(metadata_path)
        print(json.dumps({'running': True, 'url': server.origin, 'pid': os.getpid(),
                          'agent_gateway': server.agent_gateway}), flush=True)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        if gateway is not None:
            if gateway_thread is not None:
                gateway.shutdown()
                gateway_thread.join(timeout=5)
            gateway.server_close()
        if server is not None:
            server.server_close()
        metadata_path.unlink(missing_ok=True)
        lock.__exit__()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description='WBot OC 本机管理端与独立远程设备通信端口')
    parser.add_argument('action', choices=('start', 'serve', 'open', 'status', 'stop'))
    parser.add_argument('--state-dir', type=Path, default=Path.home() / '.wbot-oc',
                        help='OC 的数据库、发布包与作业日志目录；须独立于 Assistant')
    parser.add_argument('--port', type=int, default=8792, help='仅监听本机；0 为自动分配')
    parser.add_argument('--web-dir', type=Path, default=DEFAULT_WEB_DIR, help='React 构建目录')
    parser.add_argument('--agent-host', default='127.0.0.1', help='设备通信监听地址；跨电脑接入可设 0.0.0.0')
    parser.add_argument('--agent-port', type=int, default=8793, help='设备通信端口；0 为自动分配')
    parser.add_argument('--agent-cert', type=Path, help='设备通信 HTTPS 证书 PEM 文件')
    parser.add_argument('--agent-key', type=Path, help='设备通信 HTTPS 私钥 PEM 文件')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535 or not 0 <= args.agent_port <= 65535:
        parser.error('端口须为 0–65535')
    if bool(args.agent_cert) != bool(args.agent_key):
        parser.error('--agent-cert 与 --agent-key 必须同时提供')
    agent_options = {'agent_host': args.agent_host, 'agent_port': args.agent_port,
                     'agent_cert': args.agent_cert, 'agent_key': args.agent_key}
    try:
        if args.action == 'serve':
            serve(args.state_dir, args.port, args.web_dir, **agent_options)
            return 0
        if args.action in ('start', 'open'):
            result = start_service(args.state_dir, args.port, args.web_dir, **agent_options)
            if args.action == 'open':
                webbrowser.open(result['url'])
        elif args.action == 'stop':
            result = stop_service(args.state_dir)
        else:
            result = service_status(args.state_dir)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
