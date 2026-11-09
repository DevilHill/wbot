"""共享元素仓库的事务存储；完整快照与历史元数据分开读取。"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


class ElementStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(write=True) as database:
            database.execute('''CREATE TABLE IF NOT EXISTS records (
                kind TEXT NOT NULL, id TEXT NOT NULL, repository_id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(kind, id))''')
            database.execute('CREATE INDEX IF NOT EXISTS records_repository ON records(kind, repository_id)')
            database.execute('''CREATE TABLE IF NOT EXISTS commits (
                id TEXT PRIMARY KEY, repository_id TEXT NOT NULL, payload TEXT NOT NULL, items TEXT NOT NULL)''')
            database.execute('CREATE INDEX IF NOT EXISTS commits_repository ON commits(repository_id)')
            database.execute('''CREATE TABLE IF NOT EXISTS operations (
                actor TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY(actor, request_id))''')

    @contextmanager
    def connection(self, write=False):
        database = sqlite3.connect(self.path, timeout=15)
        database.row_factory = sqlite3.Row
        try:
            with database:
                database.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                yield database
        finally:
            database.close()

    @staticmethod
    def get(database, kind, identifier, repository_id=None):
        row = database.execute('SELECT payload,repository_id FROM records WHERE kind=? AND id=?',
                               (kind, identifier)).fetchone()
        if row is None or (repository_id is not None and row['repository_id'] != repository_id):
            raise KeyError(f'找不到元素仓库记录：{identifier}')
        return json.loads(row['payload'])

    @staticmethod
    def list(database, kind, repository_id=None):
        rows = database.execute('''SELECT payload FROM records WHERE kind=? AND (? IS NULL OR repository_id=?)
                                   ORDER BY rowid DESC''', (kind, repository_id, repository_id)).fetchall()
        return [json.loads(row['payload']) for row in rows]

    @staticmethod
    def save(database, kind, record, repository_id):
        database.execute('''INSERT INTO records(kind,id,repository_id,payload) VALUES(?,?,?,?)
            ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload''',
            (kind, record['id'], repository_id, encode(record)))

    @staticmethod
    def save_commit(database, commit):
        metadata = {key: value for key, value in commit.items() if key != 'items'}
        database.execute('INSERT INTO commits VALUES(?,?,?,?)',
                         (commit['id'], commit['repository_id'], encode(metadata), encode(commit['items'])))

    @staticmethod
    def commit(database, repository_id, identifier):
        row = database.execute('SELECT payload,items FROM commits WHERE id=? AND repository_id=?',
                               (identifier, repository_id)).fetchone()
        if row is None:
            raise KeyError(f'找不到元素提交：{identifier}')
        return dict(json.loads(row['payload']), items=json.loads(row['items']))

    @staticmethod
    def history(database, repository_id):
        rows = database.execute('SELECT payload FROM commits WHERE repository_id=? ORDER BY rowid DESC LIMIT 100',
                                (repository_id,)).fetchall()
        return [json.loads(row['payload']) for row in rows]

    @staticmethod
    def operation(database, actor, request_id):
        row = database.execute('SELECT fingerprint,result FROM operations WHERE actor=? AND request_id=?',
                               (actor, request_id)).fetchone()
        return {'fingerprint': row['fingerprint'], 'result': json.loads(row['result'])} if row else None

    @staticmethod
    def save_operation(database, actor, request_id, fingerprint, result):
        database.execute('INSERT INTO operations VALUES(?,?,?,?)', (actor, request_id, fingerprint, encode(result)))
