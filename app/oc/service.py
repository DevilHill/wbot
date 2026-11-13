"""本机联调版 OC：版本目录、流程部署及对独立 Assistant 的作业编排。"""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
from uuid import uuid4

from app.automation_package import MAX_ARCHIVE_BYTES, inspect_package, resolve_parameters
from .agent_service import AgentService, TERMINAL_STATES
from .element_service import ElementRepositoryService
from .assistant_releases import AssistantReleases
from .client import AssistantClient, AssistantRejected
from .store import OcStore, public_record as _public
from .resources import Resources, text as _text
from .job_queue import JobQueue


ACTIVE_STATES = {'preparing', 'running', 'stopping'}


def _fingerprint(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class OcService:
    def __init__(self, state_dir, *, database_url=None, redis_url=None, namespace='wbot_oc'):
        self.state_dir = Path(state_dir).resolve()
        self.packages_dir = self.state_dir / 'packages'
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.database = None
        self.runtime = None
        self._lock = threading.RLock()
        if database_url:
            from .postgres import PostgresDatabase, PostgresElementStore, PostgresOcStore
            self.database = PostgresDatabase(database_url, namespace)
            self.store = PostgresOcStore(self.database)
            self.elements = ElementRepositoryService(store=PostgresElementStore(self.database))
        else:
            self.store = OcStore(self.state_dir / 'oc.sqlite3')
            self.elements = ElementRepositoryService(self.state_dir / 'elements.sqlite3')
        if redis_url:
            from .runtime_cache import RobotRuntimeCache
            self.runtime = RobotRuntimeCache(redis_url, namespace)
        self.agents = AgentService(self.store, self._lock, runtime=self.runtime)
        self.releases = AssistantReleases(self.state_dir, self.store, self._lock)
        self.resources = Resources(self.store, self._lock)
        self.queue = JobQueue(self)
        from .auth import AuthService
        self.auth = AuthService(self.store, self._lock)

    def close(self):
        if self.runtime is not None:
            self.runtime.close()
        if self.database is not None:
            self.database.close()

    def import_package(self, path):
        source = Path(path)
        if source.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError('发布包超过 516 MiB')
        with self._lock, tempfile.TemporaryDirectory(prefix='.import-', dir=self.packages_dir) as temporary:
            staged = Path(temporary) / 'package.zip'
            shutil.copyfile(source, staged)
            manifest = inspect_package(staged)
            digest = _fingerprint(staged)
            identifier = f'{manifest["name"]}@{manifest["version"]}'
            existing = next((item for item in self.store.list('packages') if item['id'] == identifier), None)
            if existing:
                if existing['_fingerprint'] != digest:
                    raise ValueError('同名同版本的发布包内容不同，请增加版本号')
                return _public(existing)
            destination = self.packages_dir / f'{digest}.zip'
            if destination.exists():
                raise ValueError('发布包文件已存在但目录记录不完整，请检查 OC 数据目录')
            record = {'id': identifier, 'manifest': manifest, 'created_at': time.time(),
                      'size_bytes': staged.stat().st_size, '_fingerprint': digest, '_archive': str(destination)}
            staged.replace(destination)
            try:
                self.store.insert('packages', record)
            except Exception:
                destination.unlink()
                raise
            return _public(record)

    def list_packages(self):
        return [_public(item) for item in self.store.list('packages')]

    def add_device(self, name, state_dir):
        name = _text(name, '设备名称')
        path = Path(_text(state_dir, 'Assistant 数据目录', 4096)).expanduser()
        if not path.is_absolute():
            raise ValueError('Assistant 数据目录必须为本机完整路径')
        path = path.resolve()
        if not (path / 'service.json').is_file():
            raise ValueError('找不到 Assistant 服务记录，请先启动该目录的 Assistant')
        with self._lock:
            if any(item.get('state_dir') and Path(item['state_dir']) == path for item in self.store.list('devices')):
                raise ValueError('这个 Assistant 数据目录已经接入')
            device = {'id': uuid4().hex, 'name': name, 'state_dir': str(path), 'status': 'offline',
                      'maintenance': False, 'active_jobs': 0, 'last_seen': None, 'error': '',
                      'transport': 'local', 'binding_state': 'approved', 'created_at': time.time()}
            self.store.insert('devices', device)
            return self._refresh_device(device)

    def _refresh_device(self, device, persist=False):
        if device.get('transport') == 'agent':
            return self.agents.refresh(device, persist=persist)
        device.setdefault('transport', 'local')
        device.setdefault('binding_state', 'approved')
        try:
            client = AssistantClient(device['state_dir'])
            client.health()
            device['active_jobs'] = sum(job.get('state') in ACTIVE_STATES for job in client.jobs())
            device['status'] = 'busy' if device['active_jobs'] else 'online'
            device['last_seen'] = time.time()
            device['error'] = ''
        except (OSError, AssistantRejected) as exc:
            device['status'] = 'offline'
            device['active_jobs'] = 0
            device['error'] = str(exc)
        self.store.replace('devices', device)
        return _public(device)

    def update_device(self, identifier, maintenance):
        if not isinstance(maintenance, bool):
            raise ValueError('maintenance 必须为布尔值')
        with self._lock:
            device = self.store.get('devices', identifier)
            device['maintenance'] = maintenance
            return self._refresh_device(device, persist=True)

    def _process_values(self, body):
        allowed = {'name', 'description', 'package_id', 'device_id', 'environment_id',
                   'defaults', 'enabled', 'asset_bindings'}
        if not isinstance(body, dict) or body.keys() - allowed:
            raise ValueError('流程包含不支持的字段')
        name = _text(body.get('name'), '流程名称')
        description = body.get('description', '')
        if not isinstance(description, str) or len(description) > 2000:
            raise ValueError('流程说明必须是最多 2000 字符的文本')
        package_id = _text(body.get('package_id'), '发布包标识', 200)
        package = self.store.get('packages', package_id)
        device_id, environment_id = body.get('device_id', ''), body.get('environment_id', '')
        if not isinstance(device_id, str) or not isinstance(environment_id, str) or bool(device_id) == bool(environment_id):
            raise ValueError('必须选择一个 Robot 或一个 Environment')
        if environment_id:
            environment_id = _text(environment_id, 'Environment ID')
            self.store.get('environments', environment_id)
        else:
            device_id = _text(device_id, 'Robot ID')
            device = self.store.get('devices', device_id)
            if device.get('binding_state', 'approved') != 'approved':
                raise RuntimeError('只能选择已批准的 Robot')
        bindings = body.get('asset_bindings', {})
        self.resources.bindings(package['manifest'], bindings)
        defaults = body.get('defaults', {})
        manifest = dict(package['manifest'])
        manifest['parameters'] = {key: dict(value, required=False) for key, value in manifest['parameters'].items()}
        resolve_parameters(manifest, defaults)
        enabled = body.get('enabled', True)
        if not isinstance(enabled, bool):
            raise ValueError('enabled 必须为布尔值')
        return {'name': name, 'description': description, 'package_id': package_id,
                'device_id': device_id, 'environment_id': environment_id, 'asset_bindings': bindings,
                'defaults': defaults, 'enabled': enabled}

    def create_process(self, body):
        with self._lock:
            record = self._process_values(body)
            record.update(id=uuid4().hex, created_at=time.time(), updated_at=time.time())
            self.store.insert('processes', record)
            return record

    def update_process(self, identifier, body):
        if not isinstance(body, dict):
            raise ValueError('流程更新必须是对象')
        with self._lock:
            existing = self.store.get('processes', identifier)
            values = {key: value for key, value in existing.items() if key not in ('id', 'created_at', 'updated_at')}
            record = self._process_values(dict(values, **body))
            record.update(id=identifier, created_at=existing['created_at'], updated_at=time.time())
            self.store.replace('processes', record)
            return record

    def run_process(self, identifier, parameters, request_id):
        request_id = _text(request_id, '请求标识', 128)
        if not isinstance(parameters, dict):
            raise ValueError('parameters 必须是对象')
        signature = json.dumps([identifier, parameters], sort_keys=True, ensure_ascii=False, allow_nan=False)
        with self._lock:
            existing = self.store.job_for_request(request_id)
            if existing:
                if existing['_request_signature'] != signature:
                    raise ValueError('请求标识已用于不同的流程或参数')
                return self.get_job(existing['id'])
            process = self.store.get('processes', identifier)
            if process.get('environment_id'):
                raise ValueError('Environment 流程请通过运行队列提交')
            package = self.store.get('packages', process['package_id'])
            resolved, snapshots = self.resources.resolve_inputs(process, package['manifest'], parameters)
            device = self._refresh_device(self.store.get('devices', process['device_id']))
            self._require_ready(process, device)
            job = self._new_job(process, device, resolved, request_id, signature)
            job['asset_snapshots'] = snapshots
            self.store.insert('jobs', job)
            if device.get('transport') != 'agent':
                self._dispatch(job, device, package)
            return _public(job)

    @staticmethod
    def _require_ready(process, device):
        if device.get('transport') == 'agent' and device['binding_state'] != 'approved':
            raise RuntimeError('设备绑定尚未批准或已失效，不能创建作业')
        if not process['enabled']:
            raise RuntimeError('流程已停用，不能创建作业')
        if device['maintenance']:
            raise RuntimeError('设备处于维护模式，不能创建作业')
        if device['status'] == 'offline':
            raise RuntimeError('执行设备离线，请先启动 Assistant 后台服务')
        if device['status'] == 'busy':
            raise RuntimeError('执行设备忙，请等待当前任务结束')

    @staticmethod
    def _new_job(process, device, parameters, request_id, signature):
        identifier = uuid4().hex
        return {'id': identifier, 'request_id': request_id, 'process_id': process['id'], 'process_name': process['name'],
                'package_id': process['package_id'], 'device_id': device['id'], 'device_name': device['name'],
                'parameters': parameters, 'state': 'dispatching', 'created_at': time.time(), 'started_at': None,
                'finished_at': None, 'assistant_job_id': None, 'result': None, 'error': '', 'sync_error': '',
                'last_synced_at': None, '_request_signature': signature, '_assistant_request_id': 'oc-' + identifier,
                '_log_complete': False, '_transport': device.get('transport', 'local')}

    def _dispatch(self, job, device, package):
        client = AssistantClient(device['state_dir'])
        submitted = False
        try:
            archive = Path(package['_archive'])
            if _fingerprint(archive) != package['_fingerprint']:
                raise ValueError('OC 存储的发布包内容已变化，拒绝执行')
            inspect_package(archive)
            client.request('/api/packages', {'path': str(archive)})
            submitted = True
            response = client.request('/api/jobs', {'package_id': package['id'], 'parameters': job['parameters'],
                                                   'request_id': job['_assistant_request_id']})
            self._accept_job(job, response.get('job'))
        except AssistantRejected as exc:
            job.update(state='failed', error=str(exc), finished_at=time.time())
        except (OSError, ValueError, KeyError) as exc:
            if submitted:
                job.update(state='unknown', sync_error='派发响应未确认；将核对执行端记录，不会自动重跑')
            else:
                job.update(state='failed', error=str(exc), finished_at=time.time())
        self.store.replace('jobs', job)

    @staticmethod
    def _accept_job(job, remote):
        if (not isinstance(remote, dict) or not isinstance(remote.get('id'), str)
                or remote.get('state') not in ACTIVE_STATES | TERMINAL_STATES
                or remote.get('package_id') != job['package_id']
                or remote.get('request_id') != job['_assistant_request_id']):
            raise ValueError('Assistant 返回的作业与派发身份不符')
        job['assistant_job_id'] = remote['id']
        for key in ('state', 'started_at', 'finished_at', 'result', 'error'):
            job[key] = remote.get(key)
        job['sync_error'] = ''
        job['last_synced_at'] = time.time()

    def _synchronize(self, job):
        if job['state'] == 'queued' or job.get('_transport') == 'unassigned':
            return job
        if job.get('_transport') == 'agent':
            return job
        if job['state'] in TERMINAL_STATES and (not job['assistant_job_id'] or job.get('_log_complete')):
            return job
        device = self.store.get('devices', job['device_id'])
        client = AssistantClient(device['state_dir'])
        try:
            if job['assistant_job_id']:
                remote = client.request('/api/jobs/' + job['assistant_job_id']).get('job')
            else:
                remote = next((item for item in client.jobs() if item.get('request_id') == job['_assistant_request_id']), None)
                if remote is None:
                    job['state'] = 'unknown'
                    raise ConnectionError('执行端尚无可确认的派发记录；不会自动重跑，请核实')
            self._accept_job(job, remote)
            if job['state'] in TERMINAL_STATES:
                self._cache_log(job, client)
        except (OSError, ValueError) as exc:
            job['sync_error'] = str(exc)
        self.store.replace('jobs', job)
        return job

    def get_job(self, identifier):
        with self._lock:
            return _public(self._synchronize(self.store.get('jobs', identifier)))

    def list_jobs(self):
        with self._lock:
            return [_public(self._synchronize(job)) for job in self.store.list('jobs')]

    def _cache_log(self, job, client):
        content = client.request('/api/jobs/' + job['assistant_job_id'] + '/log').get('log')
        if not isinstance(content, str):
            raise ValueError('Assistant 日志格式无效')
        self.store.save_log(job['id'], content)
        job['_log_complete'] = job['state'] in TERMINAL_STATES
        return content

    def read_log(self, identifier):
        with self._lock:
            job = self._synchronize(self.store.get('jobs', identifier))
            cached = self.store.read_log(identifier)
            if job.get('_transport') == 'agent':
                return {'log': cached or '', 'cached': True, 'sync_error': job['sync_error']}
            if job['state'] in TERMINAL_STATES and cached is not None:
                return {'log': cached, 'cached': True, 'sync_error': job['sync_error']}
            if not job['assistant_job_id']:
                return {'log': cached or '', 'cached': True, 'sync_error': job['sync_error']}
            device = self.store.get('devices', job['device_id'])
            try:
                content = self._cache_log(job, AssistantClient(device['state_dir']))
                return {'log': content, 'cached': False, 'sync_error': ''}
            except (OSError, ValueError) as exc:
                return {'log': cached or '', 'cached': True, 'sync_error': str(exc)}

    def stop_job(self, identifier):
        with self._lock:
            job = self._synchronize(self.store.get('jobs', identifier))
            if job['state'] in TERMINAL_STATES:
                return _public(job)
            if job['state'] == 'queued':
                job.update(state='stopped', finished_at=time.time(), _log_complete=True, queue_reason='')
                self.store.replace('jobs', job)
                return _public(job)
            if job.get('_transport') == 'agent':
                if not job.get('_agent_claimed'):
                    job.update(state='stopped', finished_at=time.time(), _log_complete=True)
                else:
                    job['_stop_requested'] = True
                self.store.replace('jobs', job)
                return _public(job)
            if not job['assistant_job_id']:
                raise RuntimeError('作业派发状态尚未核实，不能发送停止请求')
            device = self.store.get('devices', job['device_id'])
            client = AssistantClient(device['state_dir'])
            try:
                self._accept_job(job, client.request('/api/jobs/' + job['assistant_job_id'] + '/stop', {}).get('job'))
                self._cache_log(job, client)
            except (OSError, ValueError) as exc:
                job['sync_error'] = f'停止结果尚未确认：{exc}'
            self.store.replace('jobs', job)
            return _public(job)

    def snapshot(self):
        with self._lock:
            jobs = self.list_jobs()
            devices = [self._refresh_device(device) for device in self.store.list('devices')]
            return {'packages': self.list_packages(), 'processes': self.store.list('processes'),
                    'devices': devices, 'jobs': jobs, 'robots': devices,
                    'environments': self.store.list('environments'), 'assets': self.store.list('assets')}

    def agent_package(self, device, job_id):
        with self._lock:
            current = self.store.get('devices', device['id'])
            self.agents.require_approved(current)
            job = self.agents.owned_job(device, job_id)
            package = self.store.get('packages', job['package_id'])
            archive = Path(package['_archive'])
            if archive.stat().st_size != package['size_bytes'] or _fingerprint(archive) != package['_fingerprint']:
                raise ValueError('OC 存储的发布包内容已变化，拒绝下载')
            return archive
