"""远程设备的人工审批、幂等领取及任务结果接收。"""
import hashlib
import json
import re
import secrets
import time

from .store import public_record


TERMINAL_STATES = {'succeeded', 'failed', 'stopped', 'interrupted'}
RESERVED_STATES = {'dispatching', 'preparing', 'running', 'stopping', 'unknown'}
REPORT_STATES = {'preparing', 'running', 'stopping'} | TERMINAL_STATES
MAX_LOG_BYTES = 512 * 1024
MAX_RESULT_BYTES = 1024 * 1024
HEARTBEAT_TIMEOUT = 30


class AgentDenied(PermissionError):
    pass


class AgentService:
    def __init__(self, store, lock, runtime=None):
        self.store = store
        self.lock = lock
        self.runtime = runtime

    def enroll(self, body):
        if set(body) != {'device_id', 'name', 'secret'}:
            raise ValueError('绑定申请必须包含 device_id、name 和 secret')
        identifier, name, secret = body['device_id'], body['name'], body['secret']
        if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{32}', identifier):
            raise ValueError('device_id 必须是小写 UUID hex')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise ValueError('设备名称必须是 1–120 字符的文本')
        if not isinstance(secret, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', secret):
            raise ValueError('设备密钥格式无效')
        digest = hashlib.sha256(secret.encode('ascii')).hexdigest()
        with self.lock:
            devices = self.store.list('devices')
            existing = next((item for item in devices if item['id'] == identifier), None)
            if existing:
                if not secrets.compare_digest(existing.get('_secret_hash', ''), digest):
                    raise AgentDenied('设备身份或凭据无效')
                return public_record(existing)
            pending = [item for item in devices if item.get('binding_state') == 'pending']
            if len(pending) >= 100:
                raise RuntimeError('待审批设备已达 100 台，请先处理现有申请')
            used_codes = {item['verification_code'] for item in pending}
            code = f'{secrets.randbelow(1000000):06d}'
            while code in used_codes:
                code = f'{secrets.randbelow(1000000):06d}'
            device = {'id': identifier, 'name': name.strip(), 'transport': 'agent',
                      'binding_state': 'pending', 'verification_code': code, 'created_at': time.time(),
                      'status': 'offline', 'maintenance': False, 'active_jobs': 0,
                      'last_seen': None, 'error': '', '_secret_hash': digest, '_reported_busy': False}
            self.store.insert('devices', device)
            return public_record(device)

    def authenticate(self, identifier, secret):
        if not isinstance(secret, str) or not secret or len(secret) > 128:
            raise AgentDenied('设备身份或凭据无效')
        try:
            device = self.store.get('devices', identifier)
        except KeyError as exc:
            raise AgentDenied('设备身份或凭据无效') from exc
        digest = hashlib.sha256(secret.encode('utf-8')).hexdigest()
        if device.get('transport') != 'agent' or not secrets.compare_digest(device['_secret_hash'], digest):
            raise AgentDenied('设备身份或凭据无效')
        return device

    @staticmethod
    def require_approved(device):
        if device.get('binding_state') != 'approved':
            raise AgentDenied('设备绑定尚未批准或已失效')

    def refresh(self, device, heartbeat=False, busy=None, persist=False):
        cached = self.runtime.read(device['id']) if self.runtime else None
        if cached and cached['last_seen'] >= (device['last_seen'] or 0):
            device['last_seen'] = cached['last_seen']
            device['_reported_busy'] = cached['busy']
        if heartbeat:
            device['last_seen'] = time.time()
        if busy is not None:
            device['_reported_busy'] = busy
        active = self.store.jobs_in_states(RESERVED_STATES, device['id'])
        device['active_jobs'] = max(len(active), int(device.get('_reported_busy', False)))
        online = (device['binding_state'] == 'approved' and device['last_seen'] is not None
                  and time.time() - device['last_seen'] < HEARTBEAT_TIMEOUT)
        device['status'] = ('busy' if device['active_jobs'] else 'online') if online else 'offline'
        device['error'] = ''
        saved_at = cached['saved_at'] if cached else 0
        save_due = persist or time.time() - saved_at >= 15
        cached_ok = self.runtime and device['last_seen'] is not None and self.runtime.write(
            device['id'], device['last_seen'], device.get('_reported_busy', False),
            time.time() if save_due else saved_at)
        if not cached_ok or save_due:
            self.store.replace('devices', device)
        return public_record(device)

    def status(self, device):
        with self.lock:
            return {'device': self.refresh(self.store.get('devices', device['id']), heartbeat=True)}

    def decide(self, identifier, action):
        transitions = {'approve': ('pending', 'approved'), 'reject': ('pending', 'rejected'),
                       'revoke': ('approved', 'revoked')}
        if action not in transitions:
            raise ValueError('不支持的审批操作')
        before, after = transitions[action]
        with self.lock:
            device = self.store.get('devices', identifier)
            if device.get('transport') != 'agent':
                raise ValueError('本机设备不使用远程绑定审批')
            if action in ('reject', 'revoke') and device['binding_state'] == after:
                return public_record(device)
            if device['binding_state'] != before:
                raise RuntimeError('设备当前绑定状态不允许此操作')
            device['binding_state'] = after
            device['binding_updated_at'] = time.time()
            if after == 'revoked':
                for job in self.store.list('jobs'):
                    if (job['device_id'] == identifier and job['state'] == 'dispatching'
                            and not job.get('_agent_claimed')):
                        job.update(state='failed', error='任务领取前设备绑定已被撤销',
                                   finished_at=time.time(), _log_complete=True)
                        self.store.replace('jobs', job)
            return self.refresh(device, persist=True)

    def owned_job(self, device, identifier):
        job = self.store.get('jobs', identifier)
        if (job['device_id'] != device['id'] or not job.get('_agent_claimed')
                or not secrets.compare_digest(job.get('_agent_secret_hash', ''), device['_secret_hash'])):
            raise KeyError('找不到该设备已领取的作业')
        return job

    def poll(self, device, body):
        if body.keys() - {'active_job_id', 'busy'}:
            raise ValueError('轮询包含不支持的字段')
        active_id, busy = body.get('active_job_id'), body.get('busy', False)
        if (active_id is not None and not isinstance(active_id, str)) or type(busy) is not bool:
            raise ValueError('active_job_id 或 busy 格式无效')
        with self.lock:
            device = self.store.get('devices', device['id'])
            if active_id is not None:
                self.owned_job(device, active_id)
            jobs = list(reversed(self.store.jobs_in_states(RESERVED_STATES, device['id'])))
            stops = [job['id'] for job in jobs if job.get('_agent_claimed') and job.get('_stop_requested')]
            selected = None
            if device['binding_state'] == 'approved':
                selected = next((job for job in jobs if job.get('_agent_claimed')), None)
                if selected is None and not busy and not device['maintenance']:
                    selected = next((job for job in jobs if job['state'] == 'dispatching'), None)
                    if selected:
                        selected.update(_agent_claimed=True, _agent_secret_hash=device['_secret_hash'],
                                        claimed_at=time.time())
                        self.store.replace('jobs', selected)
            response = {'device': self.refresh(device, heartbeat=True, busy=busy),
                        'job': None, 'stop_job_ids': stops}
            if selected:
                package = self.store.get('packages', selected['package_id'])
                response['job'] = {'id': selected['id'], 'package_id': selected['package_id'],
                                   'parameters': selected['parameters'], 'request_id': selected['_assistant_request_id'],
                                   'package_sha256': package['_fingerprint'], 'package_size': package['size_bytes'],
                                   'package_url': '/api/agent/jobs/' + selected['id'] + '/package'}
            return response

    @staticmethod
    def _validate_report(body):
        fields = {'sequence', 'assistant_job_id', 'state', 'started_at', 'finished_at', 'result', 'error', 'log'}
        if set(body) != fields:
            raise ValueError('任务上报字段不完整或包含不支持的字段')
        if type(body['sequence']) is not int or not 0 <= body['sequence'] <= 2 ** 53:
            raise ValueError('sequence 必须为非负整数')
        if not isinstance(body['state'], str) or body['state'] not in REPORT_STATES:
            raise ValueError('任务状态无效')
        identifier = body['assistant_job_id']
        if identifier is not None and (not isinstance(identifier, str) or not 1 <= len(identifier) <= 128):
            raise ValueError('assistant_job_id 无效')
        for key in ('started_at', 'finished_at'):
            value = body[key]
            if value is not None and (type(value) not in (int, float) or not 0 <= value <= 253402300799):
                raise ValueError('任务时间必须为有效时间戳或 null')
        if not isinstance(body['error'], str) or len(body['error']) > 8192:
            raise ValueError('错误信息最多 8192 字符')
        if not isinstance(body['log'], str) or len(body['log'].encode('utf-8')) > MAX_LOG_BYTES:
            raise ValueError('上报日志最多 512 KiB（包括截断提示）')
        if len(json.dumps(body['result'], ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_RESULT_BYTES:
            raise ValueError('运行结果最多 1 MiB')

    def report(self, device, identifier, body):
        self._validate_report(body)
        signature = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                             allow_nan=False).encode('utf-8')).hexdigest()
        with self.lock:
            job = self.owned_job(device, identifier)
            sequence = body['sequence']
            previous = job.get('_report_sequence', -1)
            if sequence <= previous:
                if sequence != previous or signature != job.get('_report_signature'):
                    raise RuntimeError('任务上报序号已过期或正文不一致')
                return {'job': {'id': job['id'], 'state': job['state']},
                        'stop_requested': bool(job.get('_stop_requested'))}
            if job['state'] in TERMINAL_STATES:
                raise RuntimeError('任务已结束，不能覆盖最终记录')
            if job['assistant_job_id'] and job['assistant_job_id'] != body['assistant_job_id']:
                raise RuntimeError('作业已关联其他 Assistant 执行记录')
            progress = {'dispatching': 0, 'preparing': 1, 'running': 2, 'stopping': 3}
            if body['state'] in progress and progress[body['state']] < progress.get(job['state'], 0):
                raise RuntimeError('任务上报不能回退执行状态')
            for key in ('assistant_job_id', 'state', 'started_at', 'finished_at', 'result', 'error'):
                job[key] = body[key]
            job.update(_report_sequence=sequence, _report_signature=signature, sync_error='',
                       last_synced_at=time.time(), _log_complete=body['state'] in TERMINAL_STATES)
            self.store.save_report(job, body['log'])
            self.refresh(self.store.get('devices', device['id']), heartbeat=True)
            return {'job': {'id': job['id'], 'state': job['state']},
                    'stop_requested': bool(job.get('_stop_requested'))}
