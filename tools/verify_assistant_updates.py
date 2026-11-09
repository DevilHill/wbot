"""Exercise the real updater with isolated portable copies and an ephemeral OC."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.assistant.lifecycle import _read_metadata, service_status
from app.assistant.update_worker import wait_process
from app.automation_package import build_package, create_project
from app.oc.service import OcService
from app.oc.agent_server import create_agent_server
from build_assistant import stop_verified_service


def call(state, endpoint, body=None):
    metadata = _read_metadata(state)
    if metadata is None:
        raise OSError('backend is restarting')
    headers = {'X-WBot-Token': metadata['token'], 'Content-Type': 'application/json'}
    content = json.dumps(body).encode() if body is not None else None
    with build_opener(ProxyHandler({})).open(Request(metadata['url'] + endpoint, content, headers), timeout=30) as response:
        return json.load(response)


def until(check, seconds=40):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(.15)
    raise RuntimeError('verification timed out')


def stop_gui(state):
    lock = state / '.desktop.lock'
    if lock.exists():
        pid = int(lock.read_text().splitlines()[0])
        try:
            os.kill(pid, signal.SIGTERM)
            wait_process(pid, 10)
        except (ProcessLookupError, OSError):
            pass


def broken_release(source, target):
    with zipfile.ZipFile(source) as original:
        files = {name: original.read(name) for name in original.namelist() if not name.endswith('/')}
    prefix = 'WBotAssistant/'
    files[prefix + 'WBotAssistant.exe'] = b'INTENTIONAL INVALID GUI FOR ROLLBACK TEST'
    metadata = json.loads(files[prefix + 'assistant-release.json'])
    major, minor, patch = (int(part) for part in metadata['version'].split('.'))
    broken_version = f'{major}.{minor}.{patch + 1}'
    files[prefix + 'runtime/app/assistant/version.py'] = f"VERSION = '{broken_version}'\n".encode()
    metadata.update(version=broken_version, notes='Isolated rollback fixture; never distribute')
    files[prefix + 'assistant-release.json'] = json.dumps(metadata).encode()
    files[prefix + 'checksums.sha256.json'] = json.dumps({name.removeprefix(prefix): hashlib.sha256(data).hexdigest()
        for name, data in files.items() if name != prefix + 'checksums.sha256.json'}).encode()
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return broken_version


bundle = Path(sys.argv[1]).resolve()
archive = bundle.parent / 'WBotAssistant-windows-x64.zip'
target_version = json.loads((bundle / 'assistant-release.json').read_text(encoding='utf-8'))['version']
with tempfile.TemporaryDirectory(prefix='online-update-check-', dir=ROOT / 'build') as directory:
    root = Path(directory).resolve()
    install = root / 'Assistant'
    state = root / 'data'
    state.mkdir()
    shutil.copytree(bundle, install)
    # Simulate an older compatible bootstrap service, while using a real frozen GUI.
    (install / 'runtime/app/assistant/version.py').write_text("VERSION = '0.0.0'\n")
    (state / 'appearance.ini').write_text('[appearance]\nmode=dark\n')
    service = OcService(root / 'oc')
    gateway = create_agent_server(service, port=0)
    gateway_thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    gateway_thread.start()
    environment = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    desktop = subprocess.Popen([str(install / 'WBotAssistant.exe'), 'open', '--state-dir', str(state), '--port', '0'],
                               cwd=root, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        until(lambda: service_status(state)['running'] and (state / '.desktop.lock').exists())
        assert call(state, '/api/health')['version'] == '0.0.0'
        call(state, '/api/settings/connect', {'server_url': gateway.origin, 'device_name': '升级验证设备'})
        device = until(lambda: next(iter(service.store.list('devices')), None))
        service.agents.decide(device['id'], 'approve')
        until(lambda: call(state, '/api/settings')['settings']['binding_state'] == 'approved')
        record = service.releases.upload(archive)
        service.releases.publish(record['id'], {'published': True, 'device_ids': [device['id']]})
        call(state, '/api/updates/check', {})
        until(lambda: call(state, '/api/updates')['update']['status'] == 'available')
        call(state, '/api/updates/download', {})
        until(lambda: call(state, '/api/updates')['update']['status'] in ('ready', 'failed'), 90)
        assert call(state, '/api/updates')['update']['status'] == 'ready', call(state, '/api/updates')
        project = root / 'job'
        create_project(project, 'update-preservation')
        (project / 'main.py').write_text('import time\nfrom wbot import runtime\ntime.sleep(3)\nruntime.set_result({"retained": True})\n')
        package = call(state, '/api/packages', {'path': str(build_package(project))})['package']
        job = call(state, '/api/jobs', {'package_id': package['id'], 'parameters': {}})['job']
        from urllib.error import HTTPError
        try:
            call(state, '/api/updates/install', {'desktop_pid': desktop.pid})
            raise AssertionError('installation accepted while a job was active')
        except HTTPError as error:
            assert error.code == 409
        until(lambda: call(state, '/api/jobs/' + job['id'])['job']['state'] == 'succeeded')
        desktop.terminate()
        desktop.wait(10)
        ui_update = subprocess.Popen([sys.executable, str(Path(__file__).with_name('assistant_update_gui.py')), str(state)],
                                     cwd=ROOT, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        assert ui_update.wait(30) == 0, 'Qt update action did not exit cleanly'
        until(lambda: (state / 'update-result.json').exists() and json.loads((state / 'update-result.json').read_text(encoding='utf-8')).get('status') == 'updated', 100)
        until(lambda: call(state, '/api/health')['version'] == target_version and not call(state, '/api/health')['updating'])
        assert call(state, '/api/jobs/' + job['id'])['job']['result'] == {'retained': True}
        assert call(state, '/api/settings')['settings']['device_id'] == device['id']
        assert 'mode=dark' in (state / 'appearance.ini').read_text()
        print('PASS: real portable upgrade via Qt button with clean GUI exit, busy rejection, GUI readiness, task/connection/theme preservation', flush=True)

        broken = root / 'broken.zip'
        broken_version = broken_release(archive, broken)
        service.releases.upload(broken)
        service.releases.publish(broken_version, {'published': True, 'device_ids': [device['id']]})
        call(state, '/api/updates/check', {})
        until(lambda: call(state, '/api/updates')['update']['status'] == 'available')
        call(state, '/api/updates/download', {})
        until(lambda: call(state, '/api/updates')['update']['status'] in ('ready', 'failed'), 90)
        assert call(state, '/api/updates')['update']['status'] == 'ready', call(state, '/api/updates')
        gui_pid = int((state / '.desktop.lock').read_text().splitlines()[0])
        call(state, '/api/updates/install', {'desktop_pid': gui_pid})
        stop_gui(state)
        until(lambda: json.loads((state / 'update-result.json').read_text(encoding='utf-8')).get('status') == 'rolled_back', 100)
        until(lambda: call(state, '/api/health')['version'] == target_version and not call(state, '/api/health')['updating'])
        assert call(state, '/api/jobs/' + job['id'])['job']['result'] == {'retained': True}
        assert (state / '.desktop.lock').exists()
        print('PASS: invalid new GUI rolled back to original program and restarted; task history retained', flush=True)
    except Exception:
        for path in root.glob('.wbot-update-*/worker*.json'):
            print(path.name, path.read_text(encoding='utf-8'), flush=True)
        for path in root.glob('.wbot-update-*/worker.log'):
            print(path.name, path.read_text(encoding='utf-8', errors='replace')[-4000:], flush=True)
        if (state / 'update-result.json').exists():
            print((state / 'update-result.json').read_text(encoding='utf-8'), flush=True)
        if (state / 'service.log').exists():
            print((state / 'service.log').read_text(encoding='utf-8', errors='replace')[-6000:], flush=True)
        raise
    finally:
        if desktop.poll() is None:
            desktop.terminate()
            desktop.wait(10)
        stop_gui(state)
        if service_status(state)['running']:
            stop_verified_service(state)
        gateway.shutdown()
        gateway.server_close()
        gateway_thread.join(5)
        time.sleep(1)
