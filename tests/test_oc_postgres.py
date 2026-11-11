"""真实 PostgreSQL/Redis 集成测试；只连接显式配置的隔离测试库。"""
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from uuid import uuid4

from app.automation_package import build_package, create_project
from app.oc.service import OcService
from tests import test_oc_elements as element_tests
from tests import test_oc_resources_queue as queue_tests
from tests import test_oc_auth as auth_tests


@unittest.skipUnless(os.environ.get('WBOT_TEST_DATABASE_URL'), '需要隔离的 PostgreSQL 测试地址')
class PostgresAuthTests(auth_tests.AuthTests):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = OcService(self.temp.name, database_url=os.environ['WBOT_TEST_DATABASE_URL'],
                                 namespace='test_auth_' + uuid4().hex)
        self.addCleanup(self.service.close)
        self.auth = self.service.auth
        self.admin = self.auth.bootstrap('owner', 'temporary-pass')


@unittest.skipUnless(os.environ.get('WBOT_TEST_DATABASE_URL') and os.environ.get('WBOT_TEST_REDIS_URL'),
                     '需要隔离的 PostgreSQL 与 Redis 测试地址')
class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = OcService(self.root, database_url=os.environ['WBOT_TEST_DATABASE_URL'],
                                 redis_url=os.environ['WBOT_TEST_REDIS_URL'], namespace='test_' + uuid4().hex)
        self.addCleanup(self.service.close)

    def test_jsonb_records_report_and_idempotent_request(self):
        robot = self.service.agents.enroll({'device_id': uuid4().hex, 'name': '云端 Robot',
                                            'secret': secrets.token_urlsafe(32)})
        self.service.agents.decide(robot['id'], 'approve')
        self.service.agents.status(robot)
        project = self.root / 'project'
        create_project(project, 'pg-' + uuid4().hex[:12])
        package = self.service.import_package(build_package(project))
        process = self.service.create_process({'name': 'PG 流程', 'package_id': package['id'], 'device_id': robot['id']})
        body = {'request_id': uuid4().hex}
        first = self.service.queue.enqueue(process['id'], body)
        self.assertEqual(self.service.queue.enqueue(process['id'], body)['id'], first['id'])
        self.service.queue.dispatch()
        device = self.service.store.get('devices', robot['id'])
        claim = self.service.agents.poll(device, {})['job']
        self.assertEqual(claim['id'], first['id'])
        self.service.agents.report(device, first['id'], {'sequence': 1, 'assistant_job_id': 'pg-local',
            'state': 'succeeded', 'started_at': 1, 'finished_at': 2, 'result': {'中文': True},
            'error': '', 'log': 'PostgreSQL 日志\n'})
        self.assertEqual(self.service.read_log(first['id'])['log'], 'PostgreSQL 日志\n')
        self.assertEqual(self.service.get_job(first['id'])['result'], {'中文': True})
        self.assertFalse((self.root / 'oc.sqlite3').exists())
        self.assertFalse((self.root / 'elements.sqlite3').exists())

    def test_element_transactions_are_persisted_in_postgres(self):
        body = {'request_id': uuid4().hex, 'name': '共享库-' + uuid4().hex}
        repository = self.service.elements.create_repository(body)
        self.assertEqual(self.service.elements.create_repository(body), repository)
        detail = self.service.elements.get_repository(repository['id'])
        self.assertEqual(detail['head']['items'], [])
        self.assertEqual(detail['commits'][0]['id'], repository['head'])

    def test_redis_heartbeat_avoids_repeated_postgres_writes(self):
        from unittest.mock import patch
        robot = self.service.agents.enroll({'device_id': uuid4().hex, 'name': '心跳缓存',
                                            'secret': secrets.token_urlsafe(32)})
        self.service.agents.decide(robot['id'], 'approve')
        self.service.agents.status(robot)
        with patch.object(self.service.store, 'replace', wraps=self.service.store.replace) as replace:
            for _ in range(4):
                self.assertEqual(self.service.agents.status(robot)['device']['status'], 'online')
            self.assertEqual(replace.call_count, 0)
        self.assertIsNotNone(self.service.runtime.read(robot['id']))

    def test_redis_outage_falls_back_and_revocation_is_not_cached(self):
        from app.oc.runtime_cache import RobotRuntimeCache
        robot = self.service.agents.enroll({'device_id': uuid4().hex, 'name': '缓存故障',
                                            'secret': secrets.token_urlsafe(32)})
        self.service.agents.decide(robot['id'], 'approve')
        self.service.agents.status(robot)
        outage = RobotRuntimeCache('redis://127.0.0.1:1/0', 'unreachable')
        self.addCleanup(outage.close)
        self.service.agents.runtime = outage
        self.assertEqual(self.service.agents.status(robot)['device']['status'], 'online')
        self.assertIsNotNone(self.service.store.get('devices', robot['id'])['last_seen'])
        self.service.agents.decide(robot['id'], 'revoke')
        self.service.agents.runtime = self.service.runtime
        self.assertEqual(self.service.agents.status(robot)['device']['binding_state'], 'revoked')
        self.assertIsNone(self.service.agents.poll(robot, {})['job'])

    def test_migration_preserves_values_history_logs_and_archive_bytes(self):
        from app.oc.migrate import migrate
        source = self.root / 'sqlite'
        target = self.root / 'migrated'
        original = OcService(source)
        original.resources.save_asset(None, {'name': '开关', 'type': 'boolean', 'value': False})
        repo = original.elements.create_repository({'request_id': 'repo', 'name': '迁移元素'})
        project = self.root / 'migration-project'
        create_project(project, 'migrate-demo')
        package = original.import_package(build_package(project))
        namespace = 'test_' + uuid4().hex
        result = migrate(source, target, os.environ['WBOT_TEST_DATABASE_URL'], namespace)
        self.assertEqual(result['assets'], 1)
        migrated = OcService(target, database_url=os.environ['WBOT_TEST_DATABASE_URL'], namespace=namespace)
        self.addCleanup(migrated.close)
        self.assertIs(migrated.store.list('assets')[0]['value'], False)
        self.assertEqual(migrated.elements.get_repository(repo['id'])['repository'], repo)
        archive = Path(migrated.store.get('packages', package['id'])['_archive'])
        self.assertTrue(archive.is_relative_to(target))
        self.assertEqual(archive.read_bytes(), Path(original.store.get('packages', package['id'])['_archive']).read_bytes())
        with self.assertRaises(RuntimeError):
            migrate(source, target, os.environ['WBOT_TEST_DATABASE_URL'], namespace)


@unittest.skipUnless(os.environ.get('WBOT_TEST_DATABASE_URL'), '需要隔离的 PostgreSQL 测试地址')
class PostgresElementTests(element_tests.ElementRepositoryTests):
    def setUp(self):
        from unittest.mock import patch
        from app.oc.postgres import PostgresDatabase, PostgresElementStore
        self.database = PostgresDatabase(os.environ['WBOT_TEST_DATABASE_URL'], 'test_' + uuid4().hex)
        self.addCleanup(self.database.close)
        patcher = patch('app.oc.element_service.ElementStore', lambda path: PostgresElementStore(self.database))
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()


@unittest.skipUnless(os.environ.get('WBOT_TEST_DATABASE_URL'), '需要隔离的 PostgreSQL 测试地址')
class PostgresQueueTests(queue_tests.ResourcesQueueTests):
    def setUp(self):
        from unittest.mock import patch
        namespace = 'test_' + uuid4().hex

        def service_for_test(path):
            service = OcService(path, database_url=os.environ['WBOT_TEST_DATABASE_URL'], namespace=namespace)
            self.addCleanup(service.close)
            return service

        patcher = patch.object(queue_tests, 'OcService', service_for_test)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()
