"""Robot 资源分组、参数快照与持久化队列的行为回归。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import tempfile
import unittest
from uuid import uuid4

from app.automation_package import build_package, create_project
from app.oc.service import OcService


class ResourcesQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = OcService(self.root / 'oc')
        project = self.root / 'project'
        create_project(project, 'queue-demo')
        self.package = self.service.import_package(build_package(project))
        self.robot = self.robot_named('Robot A')

    def robot_named(self, name):
        robot = self.service.agents.enroll({'device_id': uuid4().hex, 'name': name,
                                             'secret': secrets.token_urlsafe(32)})
        self.service.agents.decide(robot['id'], 'approve')
        self.service.agents.status(robot)
        return robot

    def environment(self, robots=None):
        return self.service.resources.save_environment(None, {'name': '生产环境',
            'robot_ids': robots or [self.robot['id']]})

    def process(self, **values):
        return self.service.create_process(dict(name='测试流程', package_id=self.package['id'],
                                                device_id=self.robot['id'], **values))

    def enqueue(self, process, key=None, **body):
        return self.service.queue.enqueue(process['id'], dict(request_id=key or uuid4().hex, **body))

    def test_environment_routes_to_idle_member_and_reserves_one_job(self):
        other = self.robot_named('Robot B')
        environment = self.environment([self.robot['id'], other['id']])
        process = self.service.create_process({'name': '环境流程', 'package_id': self.package['id'],
                                               'environment_id': environment['id']})
        jobs = [self.enqueue(process) for _ in range(3)]
        self.service.queue.dispatch()
        records = [self.service.get_job(job['id']) for job in jobs]
        self.assertEqual([item['state'] for item in records], ['dispatching', 'dispatching', 'queued'])
        self.assertEqual({item['device_id'] for item in records[:2]}, {self.robot['id'], other['id']})

    def test_priority_fifo_and_cancel_survive_restart(self):
        process = self.process()
        first = self.enqueue(process, priority=10)
        second = self.enqueue(process, priority=90)
        third = self.enqueue(process, priority=90)
        restarted = OcService(self.root / 'oc')
        restarted.queue.dispatch()
        self.assertEqual(restarted.get_job(second['id'])['state'], 'dispatching')
        self.assertEqual(restarted.get_job(third['id'])['state'], 'queued')
        self.assertEqual(restarted.stop_job(first['id'])['state'], 'stopped')
        self.assertEqual(restarted.read_log(first['id'])['log'], '')

    def test_asset_is_typed_and_captured_when_submitted(self):
        asset = self.service.resources.save_asset(None, {'name': '问候对象', 'type': 'string', 'value': '原始值'})
        process = self.process(asset_bindings={'name': asset['id']})
        job = self.enqueue(process)
        self.service.resources.save_asset(asset['id'], {'value': '新值'})
        self.assertEqual(self.service.get_job(job['id'])['parameters']['name'], '原始值')
        self.assertEqual(self.enqueue(process)['parameters']['name'], '新值')
        with self.assertRaises(ValueError):
            self.service.resources.save_asset(None, {'name': '无效布尔', 'type': 'boolean', 'value': 1})
        with self.assertRaises(RuntimeError):
            self.service.resources.delete('assets', asset['id'])

    def test_concurrent_idempotent_enqueue_creates_one_record(self):
        process = self.process()
        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs = list(pool.map(lambda _: self.enqueue(process, 'same-request'), range(12)))
        self.assertEqual(len({job['id'] for job in jobs}), 1)
        with self.assertRaises(ValueError):
            self.enqueue(process, 'same-request', priority=99)

    def test_offline_maintenance_disabled_and_revoked_do_not_dispatch(self):
        process = self.process()
        job = self.enqueue(process)
        self.service.update_device(self.robot['id'], True)
        self.service.queue.dispatch()
        self.assertEqual(self.service.get_job(job['id'])['state'], 'queued')
        self.service.update_device(self.robot['id'], False)
        self.service.update_process(process['id'], {'enabled': False})
        self.service.queue.dispatch()
        self.assertEqual(self.service.get_job(job['id'])['state'], 'queued')
        self.service.update_process(process['id'], {'enabled': True})
        self.service.agents.decide(self.robot['id'], 'revoke')
        self.service.queue.dispatch()
        self.assertEqual(self.service.get_job(job['id'])['state'], 'failed')

    def test_environment_cannot_include_unapproved_robot_or_duplicate_name(self):
        pending = self.service.agents.enroll({'device_id': uuid4().hex, 'name': '待审批',
                                              'secret': secrets.token_urlsafe(32)})
        with self.assertRaises(ValueError):
            self.environment([pending['id']])
        self.environment()
        with self.assertRaises(ValueError):
            self.environment()

    def test_claim_report_then_next_task_and_preserved_log(self):
        process = self.process()
        first, second = self.enqueue(process), self.enqueue(process)
        self.service.queue.dispatch()
        device = self.service.store.get('devices', self.robot['id'])
        claim = self.service.agents.poll(device, {'busy': False})['job']
        self.assertEqual(claim['id'], first['id'])
        self.assertEqual(self.service.agents.poll(device, {})['job']['id'], first['id'])
        self.service.agents.report(device, first['id'], {'sequence': 1, 'assistant_job_id': 'local-one',
            'state': 'succeeded', 'started_at': 1, 'finished_at': 2, 'result': {'ok': True},
            'error': '', 'log': '任务一完成\n'})
        self.service.queue.dispatch()
        self.assertEqual(self.service.agents.poll(device, {})['job']['id'], second['id'])
        restarted = OcService(self.root / 'oc')
        self.assertEqual(restarted.read_log(first['id'])['log'], '任务一完成\n')

    def test_offline_robot_waits_until_heartbeat(self):
        process = self.process()
        device = self.service.store.get('devices', self.robot['id'])
        device['last_seen'] = 0
        self.service.store.replace('devices', device)
        job = self.enqueue(process)
        self.service.queue.dispatch()
        self.assertEqual(self.service.get_job(job['id'])['state'], 'queued')
        self.service.agents.status(device)
        self.service.queue.dispatch()
        self.assertEqual(self.service.get_job(job['id'])['state'], 'dispatching')

    def test_environment_pause_membership_change_and_job_snapshot(self):
        environment = self.environment()
        process = self.service.create_process({'name': '环境流程', 'package_id': self.package['id'],
                                               'environment_id': environment['id']})
        job = self.enqueue(process)
        self.service.resources.save_environment(environment['id'], {'enabled': False})
        self.service.queue.dispatch()
        self.assertIn('暂停', self.service.get_job(job['id'])['queue_reason'])
        other = self.robot_named('Robot B')
        self.service.resources.save_environment(environment['id'], {'enabled': True, 'robot_ids': [other['id']]})
        self.service.update_process(process['id'], {'name': '改名', 'defaults': {'name': '改值'}})
        self.service.queue.dispatch()
        assigned = self.service.get_job(job['id'])
        self.assertEqual(assigned['device_id'], other['id'])
        self.assertEqual(assigned['process_name'], '环境流程')
        self.assertEqual(assigned['parameters']['name'], 'WBot')

    def test_assets_validate_types_bindings_and_protect_references(self):
        for kind, value in [('string', True), ('integer', 1.2), ('number', float('inf')),
                            ('number', 10 ** 400), ('credential', 'password')]:
            with self.subTest(kind=kind, value=str(value)[:20]), self.assertRaises(ValueError):
                self.service.resources.save_asset(None, {'name': '无效', 'type': kind, 'value': value})
        asset = self.service.resources.save_asset(None, {'name': '数字', 'type': 'integer', 'value': 0})
        with self.assertRaises(ValueError):
            self.process(asset_bindings={'name': asset['id']})
        self.service.resources.save_asset(asset['id'], {'type': 'string', 'value': '正文'})
        process = self.process(asset_bindings={'name': asset['id']})
        with self.assertRaises(RuntimeError):
            self.service.resources.save_asset(asset['id'], {'type': 'boolean', 'value': False})
        override = self.enqueue(process, parameters={'name': '手动覆盖'})
        self.assertEqual(override['parameters']['name'], '手动覆盖')
        self.assertEqual(override['asset_snapshots'], {})

    def test_concurrent_dispatch_does_not_double_book_robot(self):
        process = self.process()
        for _ in range(8):
            self.enqueue(process)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.service.queue.dispatch(), range(8)))
        states = [job['state'] for job in self.service.list_jobs()]
        self.assertEqual(states.count('dispatching'), 1)
        self.assertEqual(states.count('queued'), 7)

    def test_invalid_priority_and_empty_environment(self):
        process = self.process()
        for priority in [True, '50', -1, 101]:
            with self.assertRaises(ValueError):
                self.enqueue(process, priority=priority)
        environment = self.service.resources.save_environment(None, {'name': '空环境'})
        process = self.service.create_process({'name': '等待环境', 'package_id': self.package['id'],
                                               'environment_id': environment['id']})
        job = self.enqueue(process)
        self.service.queue.dispatch()
        self.assertEqual(self.service.get_job(job['id'])['state'], 'queued')
        with self.assertRaises(RuntimeError):
            self.service.resources.delete('environments', environment['id'])


if __name__ == '__main__':
    unittest.main()
