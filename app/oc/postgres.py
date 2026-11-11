"""PostgreSQL 持久化：连接池、JSONB 记录及共享元素事务。"""
from contextlib import contextmanager
import re

from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .store import OcStore, TABLES


class PostgresDatabase:
    def __init__(self, url, namespace='wbot_oc'):
        if not re.fullmatch(r'[a-z_][a-z0-9_]{0,47}', namespace):
            raise ValueError('数据库命名空间必须为小写字母、数字或下划线，最多 48 字符')
        self.namespace = namespace
        self.pool = ConnectionPool(url, min_size=1, max_size=8, timeout=5,
            kwargs={'row_factory': dict_row, 'connect_timeout': 5,
                    'options': f'-c search_path={namespace},pg_catalog -c statement_timeout=15000'}, open=False)
        try:
            self.pool.open(wait=True, timeout=10)
            with self.connection() as database:
                database.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(namespace)))
                for table in sorted(TABLES):
                    request_column = ', request_id TEXT NOT NULL UNIQUE' if table == 'jobs' else ''
                    database.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {} (seq BIGSERIAL UNIQUE, '
                        'id TEXT PRIMARY KEY, payload JSONB NOT NULL' + request_column + ')').format(sql.Identifier(table)))
                database.execute('CREATE TABLE IF NOT EXISTS job_logs (id TEXT PRIMARY KEY, content TEXT NOT NULL)')
                database.execute("CREATE INDEX IF NOT EXISTS jobs_state ON jobs ((payload->>'state'))")
                database.execute("CREATE INDEX IF NOT EXISTS jobs_device_state ON jobs ((payload->>'device_id'), (payload->>'state'))")
                database.execute('''CREATE TABLE IF NOT EXISTS element_records (
                    seq BIGSERIAL UNIQUE, kind TEXT NOT NULL, id TEXT NOT NULL,
                    repository_id TEXT NOT NULL, payload JSONB NOT NULL, PRIMARY KEY(kind,id))''')
                database.execute('CREATE INDEX IF NOT EXISTS element_records_repo ON element_records(kind,repository_id)')
                database.execute('''CREATE TABLE IF NOT EXISTS element_commits (
                    seq BIGSERIAL UNIQUE, id TEXT PRIMARY KEY, repository_id TEXT NOT NULL,
                    payload JSONB NOT NULL, items JSONB NOT NULL)''')
                database.execute('CREATE INDEX IF NOT EXISTS element_commits_repo ON element_commits(repository_id,seq DESC)')
                database.execute('''CREATE TABLE IF NOT EXISTS element_operations (
                    actor TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    result JSONB NOT NULL, PRIMARY KEY(actor,request_id))''')
        except Exception:
            self.pool.close()
            raise

    @contextmanager
    def connection(self):
        with self.pool.connection() as connection:
            yield connection

    def close(self):
        self.pool.close()


class PostgresOcStore(OcStore):
    def __init__(self, database):
        self.database = database
        self.connection = database.connection

    def get(self, table, identifier):
        table = self._table(table)
        with self.connection() as database:
            row = database.execute(sql.SQL('SELECT payload FROM {} WHERE id=%s').format(sql.Identifier(table)),
                                   (identifier,)).fetchone()
        if row is None:
            raise KeyError(f'找不到 {table} 记录：{identifier}')
        return row['payload']

    def list(self, table):
        table = self._table(table)
        with self.connection() as database:
            rows = database.execute(sql.SQL('SELECT payload FROM {} ORDER BY seq DESC').format(sql.Identifier(table))).fetchall()
        return [row['payload'] for row in rows]

    def jobs_in_states(self, states, device_id=None):
        query = "SELECT payload FROM jobs WHERE payload->>'state'=ANY(%s)"
        values = [list(states)]
        if device_id is not None:
            query += " AND payload->>'device_id'=%s"
            values.append(device_id)
        with self.connection() as database:
            rows = database.execute(query + ' ORDER BY seq DESC', values).fetchall()
        return [row['payload'] for row in rows]

    def insert(self, table, record):
        table = self._table(table)
        with self.connection() as database:
            if table == 'jobs':
                database.execute('INSERT INTO jobs(id,request_id,payload) VALUES(%s,%s,%s)',
                                 (record['id'], record['request_id'], Jsonb(record)))
            else:
                database.execute(sql.SQL('INSERT INTO {}(id,payload) VALUES(%s,%s)').format(sql.Identifier(table)),
                                 (record['id'], Jsonb(record)))

    def replace(self, table, record):
        table = self._table(table)
        with self.connection() as database:
            changed = database.execute(sql.SQL('UPDATE {} SET payload=%s WHERE id=%s').format(sql.Identifier(table)),
                                       (Jsonb(record), record['id']))
            if changed.rowcount != 1:
                raise KeyError(record['id'])

    def delete(self, table, identifier):
        table = self._table(table)
        with self.connection() as database:
            database.execute(sql.SQL('DELETE FROM {} WHERE id=%s').format(sql.Identifier(table)), (identifier,))

    def job_for_request(self, request_id):
        with self.connection() as database:
            row = database.execute('SELECT payload FROM jobs WHERE request_id=%s', (request_id,)).fetchone()
        return row['payload'] if row else None

    def save_log(self, job_id, content):
        with self.connection() as database:
            self._save_log(database, job_id, content)

    @staticmethod
    def _save_log(database, job_id, content):
        database.execute('INSERT INTO job_logs VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET content=excluded.content',
                         (job_id, content))

    def save_report(self, job, content):
        with self.connection() as database:
            changed = database.execute('UPDATE jobs SET payload=%s WHERE id=%s', (Jsonb(job), job['id']))
            if changed.rowcount != 1:
                raise KeyError(job['id'])
            self._save_log(database, job['id'], content)

    def read_log(self, job_id):
        with self.connection() as database:
            row = database.execute('SELECT content FROM job_logs WHERE id=%s', (job_id,)).fetchone()
        return row['content'] if row else None


class PostgresElementStore:
    def __init__(self, database):
        self.database = database

    @contextmanager
    def connection(self, write=False):
        with self.database.connection() as database:
            # Serialize merge/head updates across database sessions, including retries.
            if write:
                database.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':elements',0))")
            yield database

    @staticmethod
    def get(database, kind, identifier, repository_id=None):
        row = database.execute('SELECT payload,repository_id FROM element_records WHERE kind=%s AND id=%s',
                               (kind, identifier)).fetchone()
        if row is None or (repository_id is not None and row['repository_id'] != repository_id):
            raise KeyError(f'找不到元素仓库记录：{identifier}')
        return row['payload']

    @staticmethod
    def list(database, kind, repository_id=None):
        query, values = 'SELECT payload FROM element_records WHERE kind=%s', [kind]
        if repository_id is not None:
            query += ' AND repository_id=%s'
            values.append(repository_id)
        return [row['payload'] for row in database.execute(query + ' ORDER BY seq DESC', values).fetchall()]

    @staticmethod
    def save(database, kind, record, repository_id):
        database.execute('''INSERT INTO element_records(kind,id,repository_id,payload) VALUES(%s,%s,%s,%s)
            ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload''',
            (kind, record['id'], repository_id, Jsonb(record)))

    @staticmethod
    def save_commit(database, commit):
        metadata = {key: value for key, value in commit.items() if key != 'items'}
        database.execute('INSERT INTO element_commits(id,repository_id,payload,items) VALUES(%s,%s,%s,%s)',
                         (commit['id'], commit['repository_id'], Jsonb(metadata), Jsonb(commit['items'])))

    @staticmethod
    def commit(database, repository_id, identifier):
        row = database.execute('SELECT payload,items FROM element_commits WHERE id=%s AND repository_id=%s',
                               (identifier, repository_id)).fetchone()
        if row is None:
            raise KeyError(f'找不到元素提交：{identifier}')
        return dict(row['payload'], items=row['items'])

    @staticmethod
    def history(database, repository_id):
        rows = database.execute('SELECT payload FROM element_commits WHERE repository_id=%s ORDER BY seq DESC LIMIT 100',
                                (repository_id,)).fetchall()
        return [row['payload'] for row in rows]

    @staticmethod
    def operation(database, actor, request_id):
        return database.execute('SELECT fingerprint,result FROM element_operations WHERE actor=%s AND request_id=%s',
                                (actor, request_id)).fetchone()

    @staticmethod
    def save_operation(database, actor, request_id, fingerprint, result):
        database.execute('INSERT INTO element_operations VALUES(%s,%s,%s,%s)',
                         (actor, request_id, fingerprint, Jsonb(result)))
