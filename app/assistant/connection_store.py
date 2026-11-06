"""保存 OC 连接身份及远程作业的幂等执行记录。"""
from contextlib import contextmanager
import json
import sqlite3


class ConnectionStore:
    def __init__(self, path):
        self.path = path
        with self.database() as database:
            database.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            database.execute('''CREATE TABLE IF NOT EXISTS connection_profiles (
                device_id TEXT PRIMARY KEY, server_url TEXT NOT NULL,
                device_name TEXT NOT NULL, payload TEXT NOT NULL)''')
            database.execute('''CREATE TABLE IF NOT EXISTS remote_jobs (
                device_id TEXT NOT NULL, job_id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (device_id, job_id))''')

    @contextmanager
    def database(self):
        database = sqlite3.connect(self.path, timeout=10)
        try:
            with database:
                yield database
        finally:
            database.close()

    def settings(self):
        with self.database() as database:
            row = database.execute('SELECT payload FROM settings WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def save_settings(self, settings):
        payload = json.dumps(settings, ensure_ascii=False, allow_nan=False)
        with self.database() as database:
            database.execute('INSERT OR REPLACE INTO settings VALUES (1, ?)',
                             (payload,))
            database.execute('INSERT OR REPLACE INTO connection_profiles VALUES (?, ?, ?, ?)',
                             (settings['device_id'], settings['server_url'], settings['device_name'], payload))

    def profile(self, server_url, device_name):
        with self.database() as database:
            row = database.execute('''SELECT payload FROM connection_profiles
                WHERE server_url=? AND device_name=? ORDER BY rowid DESC LIMIT 1''',
                (server_url, device_name)).fetchone()
        return json.loads(row[0]) if row else None

    def profile_for_device(self, device_id):
        with self.database() as database:
            row = database.execute('SELECT payload FROM connection_profiles WHERE device_id=?',
                                   (device_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def job(self, device_id, job_id):
        with self.database() as database:
            row = database.execute('SELECT payload FROM remote_jobs WHERE device_id=? AND job_id=?',
                                   (device_id, job_id)).fetchone()
        return json.loads(row[0]) if row else None

    def save_job(self, job):
        with self.database() as database:
            database.execute('INSERT OR REPLACE INTO remote_jobs VALUES (?, ?, ?)',
                             (job['device_id'], job['command']['id'],
                              json.dumps(job, ensure_ascii=False, allow_nan=False)))

    def unfinished_jobs(self):
        with self.database() as database:
            rows = database.execute('SELECT payload FROM remote_jobs ORDER BY rowid').fetchall()
        jobs = [json.loads(row[0]) for row in rows]
        return [job for job in jobs if not job['terminal_reported']]

    def unfinished_job(self, device_id):
        return next((job for job in self.unfinished_jobs() if job['device_id'] == device_id), None)
