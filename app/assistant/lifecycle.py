"""后台服务的独占运行、发现和客户端启动。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[2]
METADATA_FILE = "service.json"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ServiceLock:
    def __init__(self, state_dir):
        self.path = Path(state_dir) / ".service.lock"
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0, os.SEEK_END)
        if self.stream.tell() == 0:
            self.stream.write(b"1")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            self.stream = None
            raise RuntimeError("这个数据目录已有 Assistant 后台服务，请连接现有服务") from exc
        return self

    def __exit__(self, *_args):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def _read_metadata(state_dir):
    path = Path(state_dir) / METADATA_FILE
    if not path.exists():
        return None
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("Assistant 服务记录格式无效")
    url = urlsplit(metadata.get("url", ""))
    if (url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port
            or url.username or url.password or url.path or url.query or url.fragment):
        raise ValueError("Assistant 服务记录包含无效的本机地址")
    if not isinstance(metadata.get("token"), str) or not metadata["token"]:
        raise ValueError("Assistant 服务记录缺少会话信息")
    return metadata


def _request(metadata, endpoint, body=None):
    headers = {"X-WBot-Token": metadata["token"]}
    content = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        content = json.dumps(body).encode("utf-8")
    request = Request(metadata["url"] + endpoint, content, headers)
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=2) as response:
        return json.load(response)


def service_status(state_dir):
    metadata = _read_metadata(state_dir)
    if metadata is None:
        return {"running": False}
    try:
        health = _request(metadata, "/api/health")
    except (OSError, ValueError):
        return {"running": False}
    if not isinstance(health, dict) or health.get("product") != "wbot-assistant":
        return {"running": False}
    return {"running": True, "url": metadata["url"], "pid": metadata.get("pid")}


def service_launch(state_dir, port):
    """冻结后的界面调用随包 Python，不能把 GUI EXE 当作解释器。"""
    interpreter = Path(sys.executable)
    directory = ROOT
    if getattr(sys, 'frozen', False):
        bundle = interpreter.parent
        interpreter = bundle / 'python' / 'python.exe'
        directory = bundle / 'runtime'
        if not interpreter.is_file() or not (directory / 'app' / 'assistant' / '__main__.py').is_file():
            raise RuntimeError('Assistant 运行资源不完整，请完整解压便携包后再启动 WBotAssistant.exe')
    command = [str(interpreter), '-m', 'app.assistant', 'serve', '--state-dir', str(state_dir), '--port', str(port)]
    return command, directory


def start_service(state_dir, port=8791):
    state_dir = Path(state_dir).resolve()
    existing = service_status(state_dir)
    if existing["running"]:
        return existing
    state_dir.mkdir(parents=True, exist_ok=True)
    command, directory = service_launch(state_dir, port)
    options = {"cwd": directory, "stdin": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    with (state_dir / "service.log").open("ab") as log:
        child = subprocess.Popen(command, stdout=log, stderr=log, **options)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        status = service_status(state_dir)
        if status["running"]:
            return status
        if child.poll() is not None:
            raise RuntimeError(f"后台服务启动失败，请查看 {state_dir / 'service.log'}")
        time.sleep(0.1)
    child.terminate()
    child.wait(timeout=5)
    raise RuntimeError(f"后台服务启动超时，请查看 {state_dir / 'service.log'}")


def stop_service(state_dir):
    if not service_status(state_dir)["running"]:
        return {"running": False, "stopped": False}
    metadata = _read_metadata(state_dir)
    _request(metadata, "/api/service/stop", {})
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if not (Path(state_dir) / METADATA_FILE).exists():
            return {"running": False, "stopped": True}
        time.sleep(0.1)
    raise RuntimeError("后台服务仍在停止，请稍后查看状态")


def serve(state_dir, port=8791):
    if getattr(sys, 'frozen', False):
        command, directory = service_launch(Path(state_dir).resolve(), port)
        subprocess.run(command, cwd=directory, check=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return
    from .execution import ExecutionService
    from .server import create_server
    from .connection import ConnectionService

    state_dir = Path(state_dir).resolve()
    with ServiceLock(state_dir):
        execution = ExecutionService(state_dir)
        connection = ConnectionService(state_dir, execution)
        server = None
        metadata_path = state_dir / METADATA_FILE
        try:
            server = create_server(execution, port, connection)
            connection.start()
            metadata = {"url": server.origin, "pid": os.getpid(), "token": server.token}
            pending = metadata_path.with_suffix(".tmp")
            pending.write_text(json.dumps(metadata), encoding="utf-8")
            pending.replace(metadata_path)
            print(json.dumps({"running": True, "url": server.origin, "pid": os.getpid()}), flush=True)
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
        finally:
            connection.close()
            if server is not None:
                server.server_close()
            execution.shutdown()
            metadata_path.unlink(missing_ok=True)
