"""持久化优先级队列；派发前在同一服务锁内预留 Robot。"""
import json
import time

from .agent_service import RESERVED_STATES, TERMINAL_STATES
from .resources import text
from .store import public_record


class JobQueue:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    def enqueue(self, process_id, body):
        if not isinstance(body, dict) or body.keys() - {'parameters', 'request_id', 'priority'}:
            raise ValueError('入队请求包含不支持的字段')
        request_id = text(body.get('request_id'), '请求标识', 128)
        parameters, priority = body.get('parameters', {}), body.get('priority', 50)
        if not isinstance(parameters, dict) or type(priority) is not int or not 0 <= priority <= 100:
            raise ValueError('parameters 必须为对象，priority 必须为 0–100 的整数')
        signature = json.dumps(['queue', process_id, parameters, priority], sort_keys=True,
                               ensure_ascii=False, allow_nan=False)
        with self.service._lock:
            existing = self.store.job_for_request(request_id)
            if existing:
                if existing['_request_signature'] != signature:
                    raise ValueError('请求标识已用于不同的流程、参数或优先级')
                return public_record(existing)
            process = self.store.get('processes', process_id)
            if not process['enabled']:
                raise RuntimeError('流程已停用，不能提交任务')
            package = self.store.get('packages', process['package_id'])
            resolved, snapshots = self.service.resources.resolve_inputs(process, package['manifest'], parameters)
            environment_id = process.get('environment_id', '')
            if environment_id:
                environment = self.store.get('environments', environment_id)
                target = {'id': '', 'name': '等待分配 Robot', 'transport': 'unassigned'}
            else:
                target = self.store.get('devices', process['device_id'])
                if target.get('binding_state', 'approved') != 'approved':
                    raise RuntimeError('Robot 绑定未批准或已撤销')
            job = self.service._new_job(process, target, resolved, request_id, signature)
            job.update(state='queued', priority=priority, environment_id=environment_id,
                       environment_name=environment['name'] if environment_id else '',
                       asset_snapshots=snapshots, queue_reason='等待调度')
            self.store.insert('jobs', job)
            return public_record(job)

    def dispatch(self):
        with self.service._lock:
            pending = sorted(reversed(self.store.jobs_in_states({'queued'})),
                             key=lambda job: (-job['priority'], job['created_at']))
            if not pending:
                return
            occupied = set()
            for job in self.store.jobs_in_states(RESERVED_STATES):
                current = self.service._synchronize(job)
                if current['state'] not in TERMINAL_STATES:
                    occupied.add(job['device_id'])
            devices = {item['id']: self.service._refresh_device(item) for item in self.store.list('devices')}
            for job in pending:
                self._dispatch_one(job, devices, occupied)

    def _dispatch_one(self, job, devices, occupied):
        process = self.store.get('processes', job['process_id'])
        if not process['enabled']:
            return self._wait(job, '流程已停用，启用后继续调度')
        if job['environment_id']:
            environment = self.store.get('environments', job['environment_id'])
            if not environment['enabled']:
                return self._wait(job, 'Environment 已暂停')
            candidates = [devices[identifier] for identifier in environment['robot_ids'] if identifier in devices]
        else:
            candidates = [devices[job['device_id']]]
            if candidates[0].get('binding_state', 'approved') != 'approved':
                job.update(state='failed', error='Robot 绑定已撤销', finished_at=time.time(),
                           _log_complete=True, queue_reason='')
                self.store.replace('jobs', job)
                return
        device = next((item for item in candidates if item['id'] not in occupied
                       and item.get('binding_state', 'approved') == 'approved'
                       and item['status'] == 'online' and not item['maintenance']), None)
        if device is None:
            return self._wait(job, '等待已批准、在线、空闲且未维护的 Robot')
        job.update(state='dispatching', device_id=device['id'], device_name=device['name'],
                   _transport=device.get('transport', 'local'), queue_reason='', dispatched_at=time.time())
        self.store.replace('jobs', job)
        occupied.add(device['id'])
        if device.get('transport') != 'agent':
            self.service._dispatch(job, device, self.store.get('packages', job['package_id']))

    def _wait(self, job, reason):
        if job.get('queue_reason') != reason:
            job['queue_reason'] = reason
            self.store.replace('jobs', job)
