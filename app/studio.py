"""独立编码工作区：限定项目文件、冲突检测和自有 Python 进程。"""
from __future__ import annotations
import atexit
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from .processes import windows_job

SKIP = {'.git', '.venv', 'venv', '__pycache__', 'node_modules', 'build', 'dist', '.workbuddy-ai'}
TEXT = {'.py', '.txt', '.md', '.json', '.toml', '.ini', '.yaml', '.yml', '.csv', '.xml', '.html', '.css', '.js', '.gitignore'}
TEMPLATE = '''# 在这里编写 Python 自动化代码。Ctrl+S 保存，F5 运行。
from wbot import web

print("WBot Studio 编码版已就绪")

# 点击顶部「抓取元素」，确认后用「插入代码」添加定位器。
# 也可从左侧元素库插入已保存元素。
'''


class Studio:
    def __init__(self, config=None, runs=None):
        self.config = Path(config or Path.home() / '.xpath_studio/studio.json')
        self.runs = Path(runs or Path(tempfile.gettempdir()) / 'xpath-studio-runs')
        self.root = None
        self.project = ''
        self.lock = threading.RLock()
        self.proc = None
        self.close_job = None
        self.run_id = ''
        self.log_file = None
        self.run_path = ''
        self.started = 0
        self.stopped = False
        self.token = secrets.token_urlsafe(32)
        try:
            value = json.loads(self.config.read_text(encoding='utf-8'))
            if Path(value['root']).is_dir():
                self.root = Path(value['root']).resolve()
                self.project = secrets.token_hex(12)
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def state(self):
        return {'root': str(self.root) if self.root else '', 'project': self.project,
                'name': self.root.name if self.root else '未打开项目', 'token': self.token,
                'defaultParent': str(Path.home() / '.xpath_studio/projects'),
                'python': f'Python {sys.version.split()[0]}' + (' · 内置' if getattr(sys, 'frozen', False) else '')}

    def _path(self, project, relative, directory=False):
        if not self.root or project != self.project:
            raise ValueError('项目已切换，请重新打开文件')
        if not isinstance(relative, str) or '\x00' in relative or Path(relative).is_absolute():
            raise ValueError('需要项目内的相对路径')
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('路径超出当前项目')
        if not directory and (path == self.root or path.suffix.lower() not in TEXT and path.name != '.gitignore'):
            raise ValueError('仅支持项目中的文本文件')
        return path

    def open_project(self, path, create=False):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                raise ValueError('请先停止当前脚本，再切换项目')
            if not isinstance(path, str) or not path.strip() or not Path(path).expanduser().is_absolute():
                raise ValueError('请输入项目目录的完整路径')
            root = Path(path).expanduser().resolve()
            if create:
                root.mkdir(parents=True, exist_ok=False)
                (root / 'main.py').write_text(TEMPLATE, encoding='utf-8')
            if not root.is_dir():
                raise ValueError('项目目录不存在')
            self.config.parent.mkdir(parents=True, exist_ok=True)
            self.config.write_text(json.dumps({'root': str(root)}, ensure_ascii=False), encoding='utf-8')
            self.root, self.project = root, secrets.token_hex(12)
            return self.state()

    def tree(self, project, path=''):
        with self.lock:
            folder = self._path(project, path, True)
            entries = []
            for item in folder.iterdir():
                if item.name in SKIP or item.is_symlink():
                    continue
                if item.is_dir() or item.suffix.lower() in TEXT or item.name == '.gitignore':
                    entries.append({'name': item.name, 'path': item.relative_to(self.root).as_posix(), 'directory': item.is_dir()})
                if len(entries) > 2000:
                    raise ValueError('此目录文件过多，请打开更具体的项目目录')
            return sorted(entries, key=lambda x: (not x['directory'], x['name'].lower()))

    def read(self, project, path):
        with self.lock:
            file = self._path(project, path)
            if file.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('文件超过 2 MiB，请使用外部编辑器')
            raw = file.read_bytes()
            return {'path': path, 'text': raw.decode('utf-8-sig'), 'version': hashlib.sha256(raw).hexdigest()}

    def write(self, project, path, text, version=None, create=False):
        with self.lock:
            file = self._path(project, path)
            if not isinstance(text, str) or len(text.encode('utf-8')) > 2 * 1024 * 1024:
                raise ValueError('文本过大或格式错误')
            if create:
                file.parent.mkdir(parents=True, exist_ok=True)
                with file.open('x', encoding='utf-8', newline='') as stream: stream.write(text)
            else:
                current = hashlib.sha256(file.read_bytes()).hexdigest()
                if not version or current != version:
                    raise ValueError('文件已被外部修改。请先复制未保存内容，再重新打开文件，避免覆盖磁盘改动')
                temp = file.with_name('.' + file.name + '.' + secrets.token_hex(8) + '.tmp')
                try:
                    temp.write_text(text, encoding='utf-8', newline='')
                    temp.replace(file)
                finally:
                    temp.unlink(missing_ok=True)
            return self.read(project, path)

    def run(self, project, path, bridge, library):
        with self.lock:
            file = self._path(project, path)
            if file.suffix.lower() != '.py' or not file.is_file():
                raise ValueError('请选择已保存的 Python 文件')
            if self.proc and self.proc.poll() is None:
                raise ValueError('已有脚本在运行，请先停止')
            self._release_job()
            self.runs.mkdir(parents=True, exist_ok=True)
            self.run_id = secrets.token_hex(16)
            self.log_file = self.runs / (self.run_id + '.log')
            self.log_file.write_text('', encoding='utf-8')
            runtime = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
            env = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1',
                       WBOT_BRIDGE_URL=bridge, WBOT_ELEMENT_LIBRARY=str(library),
                       PYTHONPATH=str(runtime) + os.pathsep + os.environ.get('PYTHONPATH', ''))
            args = [sys.executable, '--wbot-worker'] if getattr(sys, 'frozen', False) else [sys.executable, '-X', 'utf8', str(Path(__file__).with_name('script_worker.py'))]
            self.proc = subprocess.Popen(args + [str(file), str(self.log_file)], cwd=self.root, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), start_new_session=os.name != 'nt')
            try:
                if os.name == 'nt': self.close_job = windows_job(self.proc)
            except Exception:
                self.proc.terminate(); self.proc.wait(timeout=5)
                raise
            self.run_path, self.started, self.stopped = path, time.time(), False
            return self.status()

    def _release_job(self):
        if self.close_job:
            self.close_job(); self.close_job = None

    def status(self):
        with self.lock:
            code = self.proc.poll() if self.proc else None
            running = bool(self.proc and code is None)
            if not running: self._release_job()
            raw = b''
            if self.log_file and self.log_file.exists():
                with self.log_file.open('rb') as stream:
                    size = stream.seek(0, 2); stream.seek(max(0, size - 256 * 1024)); raw = stream.read()
            return {'runId': self.run_id, 'running': running, 'exitCode': code, 'stopped': self.stopped,
                    'path': self.run_path, 'started': self.started, 'log': raw.decode('utf-8', 'replace')}

    def stop(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.stopped = True
                if os.name == 'nt': self._release_job()
                else: os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(timeout=5)
            return self.status()


STUDIO = Studio()
atexit.register(STUDIO.stop)
