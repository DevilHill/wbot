"""持久保存后台设置，由独立执行服务负责绑定、拉取和回报 OC 作业。"""
import logging
from pathlib import Path
import secrets
import tempfile
import threading
import time
from uuid import uuid4

from .connection_store import ConnectionStore
from .remote_client import GatewayClient, GatewayError, normalize_server_url


ACTIVE_STATES = {'preparing', 'running', 'stopping'}
TERMINAL_STATES = {'succeeded', 'failed', 'stopped', 'interrupted'}
BINDING_STATES = {'pending', 'approved', 'rejected', 'revoked'}
LOG_SYNC_BYTES = 512 * 1024


class ConnectionService:
    def __init__(self, state_dir, execution):
        self.state_dir = Path(state_dir)
        self.execution = execution
        self.store = ConnectionStore(self.state_dir / 'connection.sqlite3')
        self._settings_lock = threading.RLock()
        self._operation = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name='assistant-oc-connection', daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=15)

    def snapshot(self):
        with self._settings_lock:
            settings = self.store.settings()
        if settings is None:
            return {'server_url': '', 'device_name': '', 'device_id': '', 'binding_state': 'unconfigured',
                    'verification_code': '', 'last_connected_at': None, 'error': '', 'transport_secure': False,
                    'pending_reports': 0}
        public = {key: settings.get(key) for key in ('server_url', 'device_name', 'device_id',
                  'binding_state', 'verification_code', 'last_connected_at', 'error')}
        if not settings['enabled']:
            public['binding_state'] = 'disconnected'
        public['transport_secure'] = settings['server_url'].startswith('https://')
        public['pending_reports'] = self._pending_reports()
        return public

    def _pending_reports(self):
        count = 0
        for journal in self.store.unfinished_jobs():
            if journal.get('failure'):
                count += 1
            elif journal['assistant_job_id']:
                try:
                    count += self.execution.get_job(journal['assistant_job_id'])['state'] in TERMINAL_STATES
                except KeyError:
                    count += 1
        return count

    def _busy(self):
        return any(job['state'] in ACTIVE_STATES for job in self.execution.job_summary()['items'])

    def _require_idle(self):
        if self._busy():
            raise ValueError('当前有任务执行，请完成后再切换或断开后台')

    def _cancel_unstarted(self, settings):
        if settings is None:
            return
        journal = self.store.unfinished_job(settings['device_id'])
        if journal is None or journal['assistant_job_id'] or journal.get('failure'):
            return
        existing = self.execution.store.job_for_request(journal['command']['request_id'])
        if existing:
            journal['assistant_job_id'] = existing['id']
        else:
            journal.update(failure='设备已断开或切换后台，此任务未启动', failure_state='stopped')
        self.store.save_job(journal)

    def connect(self, server_url, device_name):
        server_url = normalize_server_url(server_url)
        if not isinstance(device_name, str) or not device_name.strip() or len(device_name) > 120:
            raise ValueError('设备名称须为 1–120 个字符')
        device_name = device_name.strip()
        if not self._operation.acquire(blocking=False):
            raise ValueError('正在同步后台，请稍后重试')
        try:
            with self._settings_lock:
                settings = self.store.settings()
                same = (settings and settings['server_url'] == server_url and settings['device_name'] == device_name)
                if same and settings['binding_state'] not in ('rejected', 'revoked'):
                    settings.update(enabled=True, error='')
                else:
                    self._require_idle()
                    self._cancel_unstarted(settings)
                    profile = self.store.profile(server_url, device_name)
                    if profile and profile['binding_state'] not in ('rejected', 'revoked'):
                        settings = dict(profile, enabled=True, error='')
                    else:
                        settings = {'server_url': server_url, 'device_name': device_name, 'device_id': uuid4().hex,
                                    'secret': secrets.token_urlsafe(32), 'binding_state': 'connecting',
                                    'verification_code': '', 'last_connected_at': None, 'error': '',
                                    'enabled': True, 'enrolled': False}
                self.store.save_settings(settings)
        finally:
            self._operation.release()
        self._wake.set()
        return self.snapshot()

    def disconnect(self):
        if not self._operation.acquire(blocking=False):
            raise ValueError('正在同步后台，请稍后重试')
        try:
            with self._settings_lock:
                settings = self.store.settings()
                self._require_idle()
                self._cancel_unstarted(settings)
                if settings:
                    settings.update(enabled=False, error='')
                    self.store.save_settings(settings)
        finally:
            self._operation.release()
        return self.snapshot()

    def _save_device(self, settings, device):
        if (not isinstance(device, dict) or device.get('id') != settings['device_id']
                or device.get('binding_state') not in BINDING_STATES):
            raise ValueError('OC 返回的绑定身份或状态无效')
        settings.update(binding_state=device['binding_state'], verification_code=device.get('verification_code', ''),
                        last_connected_at=time.time(), error='', enrolled=True)
        with self._settings_lock:
            self.store.save_settings(settings)

    def _run(self):
        while not self._stop.is_set():
            self._wake.clear()
            previous = self.store.settings()
            try:
                self.synchronize()
            except Exception as exc:
                if not isinstance(exc, (OSError, ValueError, RuntimeError)):
                    logging.exception('Assistant OC 同步发生异常')
                with self._settings_lock:
                    settings = self.store.settings()
                    if settings and previous and settings['device_id'] == previous['device_id']:
                        settings['error'] = str(exc)[:1000] or '连接同步失败，请检查后台服务'
                        self.store.save_settings(settings)
            self._wake.wait(2)

    def synchronize(self):
        with self._operation:
            settings = self.store.settings()
            if settings is None or not settings['enabled'] or self._stop.is_set():
                return
            client = GatewayClient(settings, stop=self._stop)
            self._report_previous_identity(settings)
            if not settings['enrolled']:
                health = client.request('/api/agent/health')
                if health.get('product') != 'wbot-oc-agent' or health.get('protocol_version') != 1:
                    raise ValueError('该地址不是兼容的 OC 设备接入服务，请确认接入端口')
                response = client.request('/api/agent/enroll', {'device_id': settings['device_id'],
                                          'name': settings['device_name'], 'secret': settings['secret']})
                self._save_device(settings, response.get('device'))
            journal = self.store.unfinished_job(settings['device_id'])
            if journal:
                self._report(client, journal)
            response = client.request('/api/agent/poll', {
                'active_job_id': journal['command']['id'] if journal and not journal['terminal_reported'] else None,
                'busy': self._busy()})
            self._save_device(settings, response.get('device'))
            self._stop_requested(journal, response.get('stop_job_ids', []))
            if journal and not journal['terminal_reported']:
                if journal['assistant_job_id'] is None and not journal.get('failure'):
                    if settings['binding_state'] == 'approved':
                        self._execute(client, journal)
                    else:
                        journal['failure'] = '设备绑定已撤销或拒绝，未启动本机任务'
                        self.store.save_job(journal)
                return
            command = response.get('job')
            if command is not None and settings['binding_state'] == 'approved':
                self._receive_job(client, settings, command)

    def _report_previous_identity(self, settings):
        for journal in self.store.unfinished_jobs():
            if journal['device_id'] == settings['device_id'] or journal.get('retry_at', 0) > time.time():
                continue
            profile = self.store.profile_for_device(journal['device_id'])
            if profile is None or profile['server_url'] != settings['server_url']:
                continue
            # 只向当前选中的 OC 补报旧身份，切换后台不会继续联系此前的服务器。
            try:
                self._report(GatewayClient(profile, stop=self._stop), journal)
            except (OSError, ValueError, KeyError) as exc:
                journal.update(retry_at=time.time() + 30, report_error=str(exc)[:1000])
                self.store.save_job(journal)
            break

    def _receive_job(self, client, settings, command):
        if (not isinstance(command, dict) or not isinstance(command.get('id'), str)
                or not command['id'].isalnum() or len(command['id']) > 128
                or not isinstance(command.get('request_id'), str)
                or command['request_id'] != 'oc-' + command['id']
                or not isinstance(command.get('parameters'), dict)):
            raise ValueError('OC 作业格式无效')
        journal = self.store.job(settings['device_id'], command['id'])
        if journal is None:
            journal = {'device_id': settings['device_id'], 'command': command, 'assistant_job_id': None,
                       'sequence': 1, 'pending_report': None, 'terminal_reported': False, 'failure': ''}
            self.store.save_job(journal)
        elif journal['command'] != command:
            raise ValueError('OC 已领取作业内容发生变化，拒绝重复执行')
        if not journal['terminal_reported']:
            self._execute(client, journal)

    def _execute(self, client, journal):
        command = journal['command']
        existing = self.execution.store.job_for_request(command['request_id'])
        if existing is not None:
            if existing['package_id'] != command['package_id'] or existing['parameters'] != command['parameters']:
                raise ValueError('远程作业与已持久化的本机任务不符')
            journal['assistant_job_id'] = existing['id']
            self.store.save_job(journal)
            return
        if self._busy() or self._stop.is_set():
            return
        try:
            with tempfile.TemporaryDirectory(prefix='.oc-download-', dir=self.state_dir) as directory:
                archive = Path(directory) / 'automation.wbot.zip'
                client.download(command, archive, self._stop)
                if self._stop.is_set():
                    return
                package = self.execution.install_package(archive)
                if package['id'] != command['package_id']:
                    raise ValueError('下载的发布包与 OC 作业不匹配')
                job = self.execution.submit(package['id'], command['parameters'], command['request_id'])
                journal['assistant_job_id'] = job['id']
        except (OSError, ValueError, RuntimeError) as exc:
            journal['failure'] = str(exc)[:2000]
        self.store.save_job(journal)

    @staticmethod
    def _log_tail(content):
        encoded = content.encode('utf-8')
        if len(encoded) <= LOG_SYNC_BYTES:
            return content
        note = '[远程仅同步最近 512 KiB 日志；完整本机日志请在 Assistant 查看]\n'
        return note + encoded[-(LOG_SYNC_BYTES - len(note.encode('utf-8'))):].decode('utf-8', errors='ignore')

    def _report(self, client, journal):
        if journal['pending_report'] is None:
            if journal['assistant_job_id'] is None and not journal.get('failure'):
                return
            if journal.get('failure'):
                report = {'state': journal.get('failure_state', 'failed'), 'assistant_job_id': None, 'started_at': None,
                          'finished_at': time.time(), 'result': None, 'error': journal['failure'], 'log': ''}
            else:
                job = self.execution.get_job(journal['assistant_job_id'])
                report = {key: job.get(key) for key in ('state', 'started_at', 'finished_at', 'result', 'error')}
                report.update(assistant_job_id=job['id'], log=self._log_tail(self.execution.read_log(job['id'])))
            report['sequence'] = journal['sequence']
            journal['pending_report'] = report
            self.store.save_job(journal)
        report = journal['pending_report']
        response = client.request('/api/agent/jobs/' + journal['command']['id'] + '/report', report)
        if not isinstance(response.get('job'), dict) or response['job'].get('id') != journal['command']['id']:
            raise GatewayError('OC 未确认运行结果，请稍后重试')
        journal.update(sequence=journal['sequence'] + 1, pending_report=None,
                       terminal_reported=report['state'] in TERMINAL_STATES)
        self.store.save_job(journal)
        if response.get('stop_requested'):
            self._stop_requested(journal, [journal['command']['id']])

    def _stop_requested(self, journal, identifiers):
        if not journal or journal['terminal_reported'] or journal['command']['id'] not in identifiers:
            return
        if journal['assistant_job_id']:
            self.execution.stop_job(journal['assistant_job_id'])
        else:
            journal['failure'] = 'OC 已取消此任务，未启动本机执行'
            journal['failure_state'] = 'stopped'
            self.store.save_job(journal)
