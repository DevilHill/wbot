"""使用 SQLite 持久保存已安装的包和本地作业历史。"""
from contextlib import contextmanager
import json
import sqlite3
import time


class JobStore:
    def __init__(self, path):
        self.path = path
        with self._connection() as database:
            database.execute('''CREATE TABLE IF NOT EXISTS packages (
                id TEXT PRIMARY KEY, manifest TEXT NOT NULL, fingerprint TEXT NOT NULL)''')
            database.execute('''CREATE TABLE IF NOT EXISTS project_bindings (
                package_id TEXT PRIMARY KEY, project_path TEXT NOT NULL UNIQUE)''')
            database.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, package_id TEXT NOT NULL, request_id TEXT UNIQUE,
                payload_hash TEXT NOT NULL, parameters TEXT NOT NULL, state TEXT NOT NULL,
                created_at REAL NOT NULL, started_at REAL, finished_at REAL,
                exit_code INTEGER, result TEXT, error TEXT NOT NULL DEFAULT '',
                log_truncated INTEGER NOT NULL DEFAULT 0)''')

    @contextmanager
    def _connection(self):
        database = sqlite3.connect(self.path, timeout=15)
        database.row_factory = sqlite3.Row
        try:
            with database:
                yield database
        finally:
            database.close()

    def recover_interrupted(self):
        with self._connection() as database:
            database.execute("""UPDATE jobs SET state='interrupted', finished_at=?,
                error='执行服务中断；未确认的作业不会自动重跑'
                WHERE state IN ('preparing', 'running', 'stopping')""", (time.time(),))

    def save_package(self, package_id, manifest, fingerprint, project_path=''):
        with self._connection() as database:
            database.execute('INSERT INTO packages VALUES (?, ?, ?)',
                (package_id, json.dumps(manifest, ensure_ascii=False), fingerprint))
            if project_path:
                database.execute('INSERT INTO project_bindings VALUES (?, ?)', (package_id, project_path))

    def bind_project(self, package_id, project_path):
        with self._connection() as database:
            database.execute('''INSERT INTO project_bindings VALUES (?, ?)
                ON CONFLICT(package_id) DO UPDATE SET project_path=excluded.project_path''', (package_id, project_path))

    def package(self, package_id):
        with self._connection() as database:
            row = database.execute('''SELECT p.*, COALESCE(b.project_path, '') AS project_path
                FROM packages p LEFT JOIN project_bindings b ON b.package_id=p.id WHERE p.id=?''', (package_id,)).fetchone()
        if row is None:
            raise KeyError(f'自动化包不存在：{package_id}')
        return {'id': row['id'], 'manifest': json.loads(row['manifest']), 'fingerprint': row['fingerprint'],
                'project_path': row['project_path']}

    def list_packages(self):
        with self._connection() as database:
            rows = database.execute('''SELECT p.id, p.manifest, COALESCE(b.project_path, '') AS project_path
                FROM packages p LEFT JOIN project_bindings b ON b.package_id=p.id ORDER BY p.id''').fetchall()
        return [{'id': row['id'], 'manifest': json.loads(row['manifest']), 'project_path': row['project_path']} for row in rows]

    @staticmethod
    def _job(row):
        if row is None:
            return None
        job = dict(row)
        job['parameters'] = json.loads(job['parameters'])
        job['result'] = json.loads(job['result']) if job['result'] is not None else None
        job['log_truncated'] = bool(job['log_truncated'])
        return job

    def create_job(self, job_id, package_id, parameters, request_id, payload_hash):
        with self._connection() as database:
            database.execute('''INSERT INTO jobs
                (id, package_id, parameters, request_id, payload_hash, state, created_at)
                VALUES (?, ?, ?, ?, ?, 'preparing', ?)''',
                (job_id, package_id, json.dumps(parameters, ensure_ascii=False), request_id, payload_hash, time.time()))
        return self.job(job_id)

    def job(self, job_id):
        with self._connection() as database:
            row = database.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise KeyError(f'作业不存在：{job_id}')
        return self._job(row)

    def job_for_request(self, request_id):
        with self._connection() as database:
            row = database.execute('SELECT * FROM jobs WHERE request_id=?', (request_id,)).fetchone()
        return self._job(row)

    def list_jobs(self):
        with self._connection() as database:
            rows = database.execute('SELECT * FROM jobs ORDER BY created_at DESC, id').fetchall()
        return [self._job(row) for row in rows]

    def job_summary(self):
        with self._connection() as database:
            rows = database.execute('''SELECT id, package_id, state, created_at,
                started_at, finished_at FROM jobs
                ORDER BY state IN ('preparing', 'running', 'stopping') DESC,
                created_at DESC, id LIMIT 200''').fetchall()
            total = database.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
        return {'items': [dict(row) for row in rows], 'total': total}

    def update_job(self, job_id, **changes):
        allowed = {'state', 'started_at', 'finished_at', 'exit_code', 'result', 'error', 'log_truncated'}
        if not changes or changes.keys() - allowed:
            raise ValueError('无效的作业更新字段')
        values = dict(changes)
        if 'result' in values:
            values['result'] = json.dumps(values['result'], ensure_ascii=False, allow_nan=False)
        assignments = ', '.join(f'{field}=?' for field in values)
        with self._connection() as database:
            database.execute(f'UPDATE jobs SET {assignments} WHERE id=?', (*values.values(), job_id))
