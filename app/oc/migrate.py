"""将已停止的 SQLite OC 目录导入空 PostgreSQL 命名空间并校验发布文件。"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import sqlite3

from app.assistant.lifecycle import ServiceLock
from .agent_service import RESERVED_STATES
from .postgres import PostgresDatabase
from .store import TABLES


def _read_sqlite(path):
    database = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    database.row_factory = sqlite3.Row
    return database


def _rows(database, table):
    exists = database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return database.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() if exists else []


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _copy_archive(record, source, destination, table):
    directory = 'packages' if table == 'packages' else 'assistant-releases'
    name = PureWindowsPath(record['_archive']).name
    original = (source / directory / name).resolve()
    if not original.is_relative_to((source / directory).resolve()):
        raise ValueError('发布包路径不在源数据目录中')
    expected = record['_fingerprint'] if table == 'packages' else record['sha256']
    if not original.is_file() or _digest(original) != expected:
        raise ValueError(f'发布包缺失或校验失败：{name}')
    target = (destination / directory / name).resolve()
    if not target.is_relative_to(destination):
        raise ValueError('目标发布包路径无效')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with original.open('rb') as incoming, target.open('xb') as outgoing:
            shutil.copyfileobj(incoming, outgoing)
    if _digest(target) != expected:
        raise ValueError(f'复制后校验失败：{name}')
    record['_archive'] = str(target)


def migrate(source, destination, database_url, namespace='wbot_oc'):
    from psycopg import sql
    from psycopg.types.json import Jsonb
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('源目录与目标目录必须独立，不能互相包含')
    if not (source / 'oc.sqlite3').is_file():
        raise ValueError('源目录缺少 oc.sqlite3')
    if (source / 'service.json').exists():
        raise RuntimeError('请先停止源 OC 服务；源目录仍有 service.json，拒绝在线迁移')
    counts = {}
    with ExitStack() as stack:
        stack.enter_context(ServiceLock(source))
        stack.enter_context(ServiceLock(destination))
        main = _read_sqlite(source / 'oc.sqlite3')
        stack.callback(main.close)
        jobs = [json.loads(row['payload']) for row in _rows(main, 'jobs')]
        if any(job['state'] in RESERVED_STATES for job in jobs):
            raise RuntimeError('仍有执行中或派发待核实任务；请先处理完毕再迁移')
        target = PostgresDatabase(database_url, namespace)
        stack.callback(target.close)
        with target.connection() as database:
            database.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':migration',0))")
            for table in sorted(TABLES | {'job_logs', 'element_records', 'element_commits', 'element_operations'}):
                if database.execute(sql.SQL('SELECT 1 FROM {} LIMIT 1').format(sql.Identifier(table))).fetchone():
                    raise RuntimeError('目标 PostgreSQL 命名空间非空，拒绝覆盖已有数据')
            for table in sorted(TABLES):
                records = _rows(main, table)
                for row in records:
                    record = json.loads(row['payload'])
                    if table in ('packages', 'assistant_releases'):
                        _copy_archive(record, source, destination, table)
                    if table == 'devices':
                        # Local Windows directories cannot address an Assistant on a Linux cloud host.
                        record.update(status='offline', active_jobs=0, last_seen=None, _reported_busy=False)
                        if record.get('transport', 'local') == 'local':
                            record['maintenance'] = True
                    if table == 'jobs':
                        database.execute('INSERT INTO jobs(id,request_id,payload) VALUES(%s,%s,%s)',
                                         (record['id'], record['request_id'], Jsonb(record)))
                    else:
                        database.execute(sql.SQL('INSERT INTO {}(id,payload) VALUES(%s,%s)').format(sql.Identifier(table)),
                                         (record['id'], Jsonb(record)))
                counts[table] = len(records)
            logs = _rows(main, 'job_logs')
            for row in logs:
                database.execute('INSERT INTO job_logs VALUES(%s,%s)', (row['id'], row['content']))
            counts['job_logs'] = len(logs)
            if (source / 'elements.sqlite3').is_file():
                elements = _read_sqlite(source / 'elements.sqlite3')
                stack.callback(elements.close)
                for table, columns, json_columns in (
                    ('records', ['kind', 'id', 'repository_id', 'payload'], {'payload'}),
                    ('commits', ['id', 'repository_id', 'payload', 'items'], {'payload', 'items'}),
                    ('operations', ['actor', 'request_id', 'fingerprint', 'result'], {'result'}),
                ):
                    rows = _rows(elements, table)
                    for row in rows:
                        values = [Jsonb(json.loads(row[column])) if column in json_columns else row[column] for column in columns]
                        database.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                            sql.Identifier('element_' + table), sql.SQL(',').join(map(sql.Identifier, columns)),
                            sql.SQL(',').join(sql.Placeholder() for _ in columns)), values)
                    counts['element_' + table] = len(rows)
        return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--state-dir', required=True, type=Path)
    args = parser.parse_args()
    url = os.environ.get('WBOT_OC_DATABASE_URL')
    if not url:
        parser.error('必须通过环境变量 WBOT_OC_DATABASE_URL 提供目标连接，不能在命令行传入密码')
    result = migrate(args.source, args.state_dir, url, os.environ.get('WBOT_OC_NAMESPACE', 'wbot_oc'))
    print(json.dumps({'migrated': result}, ensure_ascii=False))


if __name__ == '__main__':
    main()
