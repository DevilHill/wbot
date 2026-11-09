"""Background release checks and downloads; installation is an explicit idle-only action."""
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit

from app.assistant_release import MAX_RELEASE_BYTES, file_digest, inspect_release, release_metadata, version_key, verify_prepared
from .remote_client import GatewayClient
from .update_worker import write_json, validate_plan
from .version import VERSION


def require_update_transport(url):
    parsed = urlsplit(url)
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname == 'localhost'
    if parsed.scheme != 'https' and not loopback:
        raise ValueError('跨电脑在线更新需要 HTTPS OC 接入地址及受信任证书，请先在连接设置中配置')


def installed_bundle():
    executable = Path(sys.executable).resolve()
    bundle = executable.parent.parent
    if executable.parent.name == 'python' and (bundle / 'assistant-release.json').is_file():
        return bundle
    return None


class UpdateService:
    def __init__(self, execution, connection):
        self.execution = execution
        self.connection = connection
        self.state_dir = execution.state_dir
        self.bundle = installed_bundle()
        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()
        self._prepared = None
        self._identity = None
        self._state = {'status': 'idle', 'release': None, 'received': 0, 'message': ''}

    def snapshot(self):
        with self._lock:
            result = dict(self._state, version=VERSION, install_supported=self.bundle is not None,
                          ready=self._prepared is not None, updating=self.execution.updating)
        path = self.state_dir / 'update-result.json'
        if path.exists():
            try:
                result['last_result'] = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        return result

    def _set(self, **values):
        with self._lock:
            self._state.update(values)

    def _session(self):
        if self.connection is None:
            raise RuntimeError('请先连接 OC 并完成设备绑定')
        return self.connection.remote_session()

    def _start(self, status, operation):
        with self._lock:
            if self.execution.updating or (self._thread is not None and self._thread.is_alive()):
                raise RuntimeError('更新操作正在进行，请稍候')
            self._state.update(status=status, message='')
            self._thread = threading.Thread(target=self._run, args=(operation,), daemon=True, name='assistant-update')
            self._thread.start()
        return self.snapshot()

    def _run(self, operation):
        try:
            operation()
        except Exception as exc:
            self._set(status='failed', message=str(exc)[:1000] or '更新操作未完成')

    def check(self):
        return self._start('checking', self._check)

    def _check(self):
        with self._session() as (settings, client):
            require_update_transport(settings['server_url'])
            response = client.request('/api/agent/assistant-updates/latest', {'version': VERSION})
            release = response.get('release')
            if release is not None:
                self._validate_release(release)
            self._identity = (settings['server_url'], settings['device_id'])
        self._set(status='available' if release else 'current', release=release,
                  message='' if release else '当前没有发布给此设备的更新。')

    @staticmethod
    def _validate_release(release):
        release_metadata(release)
        if version_key(release['version']) <= version_key(VERSION):
            raise ValueError('更新版本必须高于当前版本')
        if (type(release.get('size')) is not int or not 0 < release['size'] <= MAX_RELEASE_BYTES
                or not isinstance(release.get('sha256'), str) or len(release['sha256']) != 64):
            raise ValueError('OC 更新包大小或校验值无效')

    def download(self):
        if self.bundle is None:
            raise RuntimeError('源码运行不替换开发目录；请先安装支持在线更新的便携版')
        return self._start('downloading', self._download)

    def _download(self):
        release = self._state['release']
        if release is None:
            raise ValueError('请先检查更新')
        with self._session() as (settings, client):
            self._require_same_identity(settings)
            current = client.request('/api/agent/assistant-updates/' + release['version'])['release']
            if current['sha256'] != release['sha256']:
                raise ValueError('更新内容已变化，请重新检查')
            settings = dict(settings)
        if self.state_dir.is_relative_to(self.bundle):
            raise ValueError('数据目录位于程序目录内，请先迁移数据目录再在线更新')
        if shutil.disk_usage(self.bundle.parent).free < 1024 * 1024 * 1024:
            raise ValueError('更新至少需要 1 GiB 可用磁盘空间')
        work = Path(tempfile.mkdtemp(prefix='.wbot-update-', dir=self.bundle.parent)).resolve()
        archive = work / 'release.zip'
        try:
            client = GatewayClient(settings, stop=self._stop)
            client.download_file('/api/agent/assistant-updates/' + release['version'] + '/archive',
                                 archive, release['size'], release['sha256'], self._stop,
                                 timeout=300, on_progress=lambda received: self._set(received=received))
            metadata = inspect_release(archive, work / 'prepared')
            if metadata != release_metadata(release):
                raise ValueError('更新包版本信息与 OC 声明不一致')
            # The worker's interpreter must remain outside both directories being renamed.
            shutil.copytree(self.bundle / 'python', work / 'python')
            shutil.copyfile(Path(__file__).with_name('update_worker.py'), work / 'update_worker.py')
            self._prepared = work
            self._set(status='ready', message='下载及校验完成。任务结束后可更新并重启。')
        except BaseException:
            if work.parent == self.bundle.parent and work.name.startswith('.wbot-update-'):
                shutil.rmtree(work)
            raise

    def _require_same_identity(self, settings):
        require_update_transport(settings['server_url'])
        if self._identity != (settings['server_url'], settings['device_id']):
            raise ValueError('OC 连接已变化，请重新检查更新')

    def install(self, desktop_pid):
        if type(desktop_pid) is not int or desktop_pid <= 0 or desktop_pid == os.getpid():
            raise ValueError('界面进程标识无效')
        with self._lock:
            if self._prepared is None or self._state['status'] != 'ready':
                raise ValueError('请先完成更新下载和校验')
            release = self._state['release']
            work = self._prepared
            with self._session() as (settings, client):
                self._require_same_identity(settings)
                current = client.request('/api/agent/assistant-updates/' + release['version'])['release']
                if current['sha256'] != release['sha256']:
                    raise ValueError('更新内容已变化，请重新检查')
                # Recheck prepared bytes before executing any staged code.
                if file_digest(work / 'release.zip') != release['sha256']:
                    raise ValueError('已下载更新包已变化，请重新下载')
                if inspect_release(work / 'release.zip')['version'] != release['version']:
                    raise ValueError('已下载更新版本不符')
                verify_prepared(work / 'prepared/WBotAssistant', work / 'release.zip')
                token = secrets.token_hex(24)
                plan = {'install': str(self.bundle), 'staged': str(work / 'prepared/WBotAssistant'),
                        'backup': str(self.bundle.parent / ('.wbot-backup-' + token)), 'work': str(work),
                        'state_dir': str(self.state_dir), 'version': release['version'],
                        'desktop_pid': desktop_pid, 'token': token}
                validate_plan(plan)
                self.execution.begin_update(token)
            try:
                write_json(work / 'plan.json', plan)
                with (work / 'worker.log').open('ab') as log:
                    subprocess.Popen([str(work / 'python/python.exe'), str(work / 'update_worker.py'), str(work / 'plan.json')],
                        cwd=work, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self._state.update(status='installing', desktop_pid=desktop_pid, message='正在退出并安装更新…')
            except BaseException:
                self.execution.resume_update(token)
                raise
        return self.snapshot()

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=20)
