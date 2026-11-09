"""独立于 Assistant 界面的本地自动化包执行服务。

服务同时只执行一个作业。各作业使用独立目录，但 Python 依赖仍来自指定解释器，
不提供代码沙箱。宿主必须先取得状态目录的独占锁，再创建执行服务。
"""
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
from uuid import uuid4

from app.automation_package import CHECKSUMS, MANIFEST, extract_package, resolve_parameters
from app.processes import windows_job
from wbot.elements import ElementLibrary
from wbot.runtime import MAX_RESULT_BYTES
from .store import JobStore

MAX_LOG_BYTES = 4 * 1024 * 1024
LOG_TRUNCATED = '\n[日志超过 4 MiB，后续输出已省略]\n'.encode('utf-8')
DEPENDENCY_CHECK = '''import importlib.metadata as metadata, json, sys
requirements = json.load(sys.stdin)
errors = []
for name, expected in requirements.items():
    try:
        actual = metadata.version(name)
    except metadata.PackageNotFoundError:
        errors.append(name + '==' + expected + ': not installed')
        continue
    if actual != expected:
        errors.append(name + '==' + expected + ': installed ' + actual)
print(json.dumps(errors))
'''


def _reject_nonfinite(value):
    raise ValueError(f'运行结果包含无效数值：{value}')


class ExecutionService:
    def __init__(self, state_dir, python_executable=sys.executable):
        self.state_dir = Path(state_dir).resolve()
        self.packages_dir = self.state_dir / 'packages'
        self.jobs_dir = self.state_dir / 'jobs'
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.python_executable = str(python_executable)
        self.store = JobStore(self.state_dir / 'assistant.sqlite3')
        self.store.recover_interrupted()
        self._lock = threading.RLock()
        self._active_id = None
        self._thread = None
        self._process = None
        self._close_process_tree = None
        self._stop_requested = False
        self._closed = False
        self.updating = False
        self._update_token = ''

    def begin_update(self, token):
        with self._lock:
            self._require_open()
            if self._active_id is not None:
                raise RuntimeError('当前有任务执行，请等待任务结束后再更新')
            self.updating = True
            self._update_token = token

    def authorize_update(self, token):
        if not self._update_token or token != self._update_token:
            raise PermissionError('更新操作凭据无效')

    def resume_update(self, token):
        with self._lock:
            self.authorize_update(token)
            self.updating = False

    def install_package(self, path):
        with self._lock:
            self._require_open()
            with tempfile.TemporaryDirectory(prefix='.install-', dir=self.packages_dir) as temporary:
                prepared = Path(temporary) / 'package'
                manifest = extract_package(path, prepared)
                package_id = f'{manifest["name"]}@{manifest["version"]}'
                fingerprint = self._fingerprint(prepared, manifest)
                try:
                    existing = self.store.package(package_id)
                except KeyError:
                    existing = None
                if existing:
                    if existing['fingerprint'] != fingerprint:
                        raise ValueError('相同名称和版本的包内容不同，请发布新版本')
                    return {'id': package_id, 'manifest': existing['manifest']}
                destination = self.packages_dir / package_id
                if destination.exists():
                    raise ValueError('包目录已存在但记录不完整，请检查本地安装状态')
                prepared.rename(destination)
                try:
                    self.store.save_package(package_id, manifest, fingerprint)
                except Exception:
                    shutil.rmtree(destination)
                    raise
                return {'id': package_id, 'manifest': manifest}

    @staticmethod
    def _fingerprint(directory, manifest):
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode('utf-8'))
        expected = {MANIFEST, CHECKSUMS, *manifest['files']}
        actual = set()
        for path in directory.rglob('*'):
            if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                raise ValueError('已安装包不能包含文件系统链接')
            if path.is_file():
                actual.add(path.relative_to(directory).as_posix())
        if actual != expected:
            raise ValueError('已安装包的文件清单发生变化，请重新安装可信版本')
        for relative in sorted(expected):
            digest.update(relative.encode('utf-8'))
            file_hash = hashlib.sha256()
            with (directory / relative).open('rb') as stream:
                while chunk := stream.read(65536):
                    file_hash.update(chunk)
            digest.update(file_hash.digest())
        return digest.hexdigest()

    def list_packages(self):
        return self.store.list_packages()

    def submit(self, package_id, parameters, request_id=None):
        if request_id is not None and (not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200):
            raise ValueError('request_id 必须为 1–200 字符的非空字符串')
        with self._lock:
            self._require_open()
            package = self.store.package(package_id)
            resolved = resolve_parameters(package['manifest'], parameters)
            payload = json.dumps([package_id, resolved], sort_keys=True, ensure_ascii=False, allow_nan=False)
            payload_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()
            if request_id:
                existing = self.store.job_for_request(request_id)
                if existing:
                    if existing['payload_hash'] != payload_hash:
                        raise ValueError('request_id 已用于不同的运行参数或自动化包')
                    return existing
            if self._active_id is not None:
                raise ValueError('执行端忙，已有作业正在运行；本版不排队')
            job_id = uuid4().hex
            job = self.store.create_job(job_id, package_id, resolved, request_id, payload_hash)
            self._active_id = job_id
            self._stop_requested = False
            self._thread = threading.Thread(target=self._execute, args=(job, package), daemon=True,
                                            name=f'wbot-job-{job_id[:8]}')
            self._thread.start()
            return job

    def list_jobs(self):
        return self.store.list_jobs()

    def job_summary(self):
        return self.store.job_summary()

    def get_job(self, job_id):
        return self.store.job(job_id)

    def read_log(self, job_id):
        self.store.job(job_id)
        path = self.jobs_dir / job_id / 'output.log'
        return path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''

    def stop_job(self, job_id):
        with self._lock:
            job = self.store.job(job_id)
            if job_id != self._active_id:
                return job
            self._stop_requested = True
            self.store.update_job(job_id, state='stopping')
            self._terminate_process_tree()
            thread = self._thread
        thread.join(timeout=20)
        return self.get_job(job_id)

    def shutdown(self):
        with self._lock:
            self._closed = True
            job_id = self._active_id
        if job_id is not None:
            self.stop_job(job_id)

    def _require_open(self):
        if self._closed:
            raise RuntimeError('执行服务已关闭')
        if self.updating:
            raise RuntimeError('Assistant 正在更新，暂不接受新任务或安装包')

    def _prepare_job(self, job, package):
        directory = self.jobs_dir / job['id']
        directory.mkdir()
        installed = self.packages_dir / package['id']
        if self._fingerprint(installed, package['manifest']) != package['fingerprint']:
            raise ValueError('已安装包的内容发生变化，请重新安装可信版本')
        working = directory / 'work'
        shutil.copytree(installed, working)
        if self._fingerprint(working, package['manifest']) != package['fingerprint']:
            raise ValueError('准备期间包内容发生变化，请重新安装可信版本')
        library_path = directory / 'elements.sqlite3'
        library = ElementLibrary(library_path)
        elements = package['manifest'].get('elements')
        if elements:
            library.import_data(json.loads((working / elements).read_text(encoding='utf-8')))
        context = {'job_id': job['id'], 'parameters': job['parameters'],
                   'entry': str(working / package['manifest']['entry'])}
        input_path = directory / 'input.json'
        input_path.write_text(json.dumps(context, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        return directory, working, input_path, library_path

    def _check_requirements(self, requirements):
        if not requirements:
            return
        result = subprocess.run([self.python_executable, '-I', '-c', DEPENDENCY_CHECK],
            input=json.dumps(requirements), capture_output=True, text=True, encoding='utf-8',
            timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError(f'依赖检查失败：{result.stderr.strip()}')
        errors = json.loads(result.stdout)
        if errors:
            raise ValueError('所选 Python 的依赖不满足要求（不会自动安装）：' + '; '.join(errors))

    def _start_process(self, job, directory, working, input_path, library_path):
        environment = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1',
            WBOT_RUN_INPUT=str(input_path), WBOT_RUN_RESULT=str(directory / 'result.json'),
            WBOT_ELEMENT_LIBRARY=str(library_path))
        worker = Path(__file__).with_name('worker.py')
        process = subprocess.Popen([self.python_executable, '-I', '-X', 'utf8', '-u', str(worker), str(input_path)],
            cwd=working, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), start_new_session=os.name != 'nt')
        self._process = process
        try:
            if os.name == 'nt':
                self._close_process_tree = windows_job(process)
            self.store.update_job(job['id'], state='running', started_at=time.time())
            process.stdin.write(b'start\n')
            process.stdin.close()
        except Exception:
            process.kill()
            process.wait(timeout=5)
            raise
        return process

    @staticmethod
    def _capture_log(process, path, outcome):
        written = 0
        try:
            with path.open('wb') as log:
                while chunk := process.stdout.read1(65536):
                    remaining = MAX_LOG_BYTES - len(LOG_TRUNCATED) - written
                    if remaining > 0:
                        output = chunk[:remaining]
                        log.write(output)
                        log.flush()
                        written += len(output)
                    if len(chunk) > max(0, remaining):
                        outcome['truncated'] = True
                if outcome['truncated']:
                    log.write(LOG_TRUNCATED)
        except OSError as error:
            outcome['error'] = str(error)
            # 写日志失败后继续读取输出，避免管道填满导致任务阻塞。
            while process.stdout.read1(65536):
                pass

    @staticmethod
    def _read_result(directory):
        path = directory / 'result.json'
        if not path.exists():
            return None
        if path.stat().st_size > MAX_RESULT_BYTES:
            raise ValueError('运行结果超过 1 MiB')
        result = json.loads(path.read_text(encoding='utf-8'), parse_constant=_reject_nonfinite)
        if not isinstance(result, dict):
            raise ValueError('运行结果必须是 JSON 对象')
        return result

    def _terminate_process_tree(self):
        if self._close_process_tree is not None:
            self._close_process_tree()
            self._close_process_tree = None
        elif os.name != 'nt' and self._process is not None:
            try:
                os.killpg(self._process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _execute(self, job, package):
        changes = {'state': 'failed', 'exit_code': None, 'result': None, 'error': ''}
        outcome = {'truncated': False, 'error': ''}
        reader = None
        try:
            directory, working, input_path, library_path = self._prepare_job(job, package)
            self._check_requirements(package['manifest'].get('requirements', {}))
            with self._lock:
                if self._stop_requested:
                    return
                process = self._start_process(job, directory, working, input_path, library_path)
            reader = threading.Thread(target=self._capture_log,
                args=(process, directory / 'output.log', outcome), daemon=True)
            reader.start()
            changes['exit_code'] = process.wait()
            with self._lock:
                self._terminate_process_tree()
            reader.join()
            if outcome['error']:
                raise OSError('日志写入失败：' + outcome['error'])
            if changes['exit_code'] == 0:
                changes['result'] = self._read_result(directory)
                changes['state'] = 'succeeded'
            else:
                changes['error'] = f'脚本退出码 {changes["exit_code"]}；详情见运行日志'
        except Exception as error:
            changes['error'] = str(error)
        finally:
            with self._lock:
                self._terminate_process_tree()
                if self._process is not None:
                    if self._process.poll() is None:
                        self._process.kill()
                    self._process.wait(timeout=5)
                    if changes['exit_code'] is None:
                        changes['exit_code'] = self._process.returncode
                    if self._process.stdout:
                        self._process.stdout.close()
                    if self._process.stdin and not self._process.stdin.closed:
                        self._process.stdin.close()
                if self._stop_requested:
                    changes.update(state='stopped', result=None, error='作业已由用户终止，可能已有部分业务结果')
                changes.update(finished_at=time.time(), log_truncated=outcome['truncated'])
                self.store.update_job(job['id'], **changes)
                self._active_id = None
                self._process = None
