"""Standalone update worker; runs from a separate copied Python environment."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def write_json(path, payload):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def request(metadata, endpoint, body=None):
    headers = {'X-WBot-Token': metadata['token'], 'Content-Type': 'application/json'}
    content = json.dumps(body).encode() if body is not None else None
    with build_opener(ProxyHandler({}), NoRedirect()).open(
            Request(metadata['url'] + endpoint, content, headers), timeout=3) as response:
        return json.load(response)


def wait_process(pid, seconds=40):
    """Wait for a process handle without terminating an existing user process."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if kernel.WaitForSingleObject(handle, seconds * 1000) != 0:
            raise RuntimeError('旧版进程尚未退出，已取消程序替换')
    finally:
        kernel.CloseHandle(handle)


def validate_plan(plan):
    install, staged, backup, work = (Path(plan[key]) for key in ('install', 'staged', 'backup', 'work'))
    for path in (install, staged, backup, work, Path(plan['state_dir'])):
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError('更新计划必须使用规范的绝对路径')
        for ancestor in (path, *path.parents):
            if ancestor.is_symlink() or getattr(ancestor, 'is_junction', lambda: False)():
                raise ValueError('更新目录不能经过文件系统链接')
    if (work.parent != install.parent or backup.parent != install.parent
            or not work.name.startswith('.wbot-update-') or not backup.name.startswith('.wbot-backup-')
            or staged != work / 'prepared' / 'WBotAssistant' or backup.exists()
            or install in (work, backup) or Path(plan['state_dir']).is_relative_to(install)):
        raise ValueError('更新目录边界无效，未替换任何程序')
    if not (install / 'WBotAssistant.exe').is_file() or not (staged / 'WBotAssistant.exe').is_file():
        raise ValueError('新旧程序目录不完整')
    return install, staged, backup


def swap_directories(install, staged, backup):
    install.rename(backup)
    try:
        staged.rename(install)
    except BaseException:
        backup.rename(install)
        raise


def restore_directories(install, staged, backup):
    if install.exists():
        install.rename(staged)
    backup.rename(install)


def launch_gui(install, state, environment):
    return subprocess.Popen([str(install / 'WBotAssistant.exe'), 'open', '--state-dir', str(state), '--port', '0'],
                            cwd=install, env=environment, stdin=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def read_service(state):
    return json.loads((state / 'service.json').read_text(encoding='utf-8'))


def wait_for_backend(state, process, version):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('新版后台启动失败')
        try:
            metadata = read_service(state)
            health = request(metadata, '/api/health')
            if metadata['pid'] == process.pid and health.get('version') == version and health.get('updating'):
                return metadata
        except (OSError, ValueError):
            pass
        time.sleep(0.15)
    raise RuntimeError('新版后台健康检查超时')


def wait_for_gui(state, process, token, version):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('新版界面启动失败')
        try:
            receipt = json.loads((state / 'update-ui-ready.json').read_text(encoding='utf-8'))
            if receipt == {'token': token, 'version': version}:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.15)
    raise RuntimeError('新版界面未确认就绪')


def run(plan):
    install, staged, backup = validate_plan(plan)
    state = Path(plan['state_dir'])
    result_path = state / 'update-result.json'
    old_metadata = read_service(state)
    token = plan['token']
    clean_environment = dict(os.environ)
    clean_environment.pop('WBOT_UPDATE_TOKEN', None)
    environment = dict(clean_environment, WBOT_UPDATE_TOKEN=token)
    replaced = False
    stopped = False
    committed = False
    backend = gui = None
    try:
        wait_process(plan['desktop_pid'])
        request(old_metadata, '/api/updates/stop', {'token': token})
        wait_process(old_metadata['pid'])
        stopped = True
        swap_directories(install, staged, backup)
        replaced = True
        write_json(result_path, {'status': 'installing', 'version': plan['version'], 'backup': str(backup)})
        with (state / 'service.log').open('ab') as log:
            backend = subprocess.Popen([str(install / 'python/python.exe'), '-m', 'app.assistant',
                'serve', '--state-dir', str(state), '--port', '0'], cwd=install / 'runtime',
                env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        metadata = wait_for_backend(state, backend, plan['version'])
        gui = launch_gui(install, state, environment)
        wait_for_gui(state, gui, token, plan['version'])
        write_json(result_path, {'status': 'updated', 'version': plan['version'], 'backup': str(backup),
                                 'message': '更新完成，旧版程序已保留。'})
        committed = True
        request(metadata, '/api/updates/resume', {'token': token})
        return 0
    except Exception as exc:
        if committed:
            write_json(result_path, {'status': 'updated', 'version': plan['version'], 'backup': str(backup),
                                     'message': '新版已启动；接单恢复尚未确认，请检查后台状态。'})
            return 1
        # Only processes created by this worker are terminated; their task gate is still closed.
        for process in (gui, backend):
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
        if backend is not None:
            try:
                if read_service(state)['pid'] == backend.pid:
                    (state / 'service.json').unlink(missing_ok=True)
            except (OSError, ValueError):
                pass
        if replaced:
            restore_directories(install, staged, backup)
        if not stopped:
            try:
                request(old_metadata, '/api/updates/resume', {'token': token})
            except (OSError, ValueError):
                pass
        write_json(result_path, {'status': 'rolled_back' if replaced else 'failed',
                                 'version': plan['version'], 'message': str(exc)[:1000]})
        launch_gui(install, state, clean_environment)
        return 1


if __name__ == '__main__':
    plan_path = Path(sys.argv[1]).resolve()
    try:
        raise SystemExit(run(json.loads(plan_path.read_text(encoding='utf-8'))))
    except Exception as error:
        write_json(plan_path.parent / 'worker-error.json', {'error': str(error)})
        raise
