"""保存 OC 目录、部署快照及最近一次确认的运行结果。"""
from contextlib import contextmanager
import json
import sqlite3


TABLES = {'packages', 'devices', 'processes', 'jobs', 'assistant_releases', 'environments', 'assets', 'users'}


def public_record(record):
    return {key: value for key, value in record.items() if not key.startswith('_')}


class OcStore:
    def __init__(self, path):
        self.path = path
        with self.connection() as database:
            for table in sorted(TABLES - {'jobs'}):
                database.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            database.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL)''')
            database.execute('CREATE TABLE IF NOT EXISTS job_logs (id TEXT PRIMARY KEY, content TEXT NOT NULL)')

    @contextmanager
    def connection(self):
        database = sqlite3.connect(self.path, timeout=15)
        database.row_factory = sqlite3.Row
        try:
            with database:
                yield database
        finally:
            database.close()

    @staticmethod
    def _table(table):
        if table not in TABLES:
            raise ValueError('未知的 OC 记录类型')
        return table

    def get(self, table, identifier):
        table = self._table(table)
        with self.connection() as database:
            row = database.execute(f'SELECT payload FROM {table} WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise KeyError(f'找不到 {table} 记录：{identifier}')
        return json.loads(row['payload'])

    def list(self, table):
        table = self._table(table)
        with self.connection() as database:
            rows = database.execute(f'SELECT payload FROM {table} ORDER BY rowid DESC').fetchall()
        return [json.loads(row['payload']) for row in rows]

    def insert(self, table, record):
        table = self._table(table)
        payload = json.dumps(record, ensure_ascii=False, allow_nan=False)
        with self.connection() as database:
            if table == 'jobs':
                database.execute('INSERT INTO jobs VALUES (?, ?, ?)', (record['id'], record['request_id'], payload))
            else:
                database.execute(f'INSERT INTO {table} VALUES (?, ?)', (record['id'], payload))

    def jobs_in_states(self, states, device_id=None):
        placeholders = ','.join('?' for _ in states)
        query = f"SELECT payload FROM jobs WHERE json_extract(payload,'$.state') IN ({placeholders})"
        values = list(states)
        if device_id is not None:
            query += " AND json_extract(payload,'$.device_id')=?"
            values.append(device_id)
        with self.connection() as database:
            rows = database.execute(query + ' ORDER BY rowid DESC', values).fetchall()
        return [json.loads(row['payload']) for row in rows]

    def replace(self, table, record):
        table = self._table(table)
        payload = json.dumps(record, ensure_ascii=False, allow_nan=False)
        with self.connection() as database:
            changed = database.execute(f'UPDATE {table} SET payload=? WHERE id=?', (payload, record['id']))
            if changed.rowcount != 1:
                raise KeyError(record['id'])

    def job_for_request(self, request_id):
        with self.connection() as database:
            row = database.execute('SELECT payload FROM jobs WHERE request_id=?', (request_id,)).fetchone()
        return json.loads(row['payload']) if row else None

    def delete(self, table, identifier):
        table = self._table(table)
        with self.connection() as database:
            database.execute(f'DELETE FROM {table} WHERE id=?', (identifier,))

    def save_log(self, job_id, content):
        with self.connection() as database:
            database.execute('INSERT OR REPLACE INTO job_logs VALUES (?, ?)', (job_id, content))

    def save_report(self, job, content):
        payload = json.dumps(job, ensure_ascii=False, allow_nan=False)
        with self.connection() as database:
            changed = database.execute('UPDATE jobs SET payload=? WHERE id=?', (payload, job['id']))
            if changed.rowcount != 1:
                raise KeyError(job['id'])
            database.execute('INSERT OR REPLACE INTO job_logs VALUES (?, ?)', (job['id'], content))

    def read_log(self, job_id):
        with self.connection() as database:
            row = database.execute('SELECT content FROM job_logs WHERE id=?', (job_id,)).fetchone()
        return row['content'] if row else None
