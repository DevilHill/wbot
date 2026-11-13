"""真实启动客户端退出后，后台服务和作业仍然可用。"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import ProxyHandler, Request, build_opener

from app.automation_package import create_project
from app.assistant.lifecycle import ServiceLock, service_status


ROOT = Path(__file__).resolve().parents[1]


class AssistantLifecycleTests(unittest.TestCase):
    def test_other_service_json_is_not_mistaken_for_assistant(self):
        class OtherServiceHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'[]')

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), OtherServiceHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                Path(temporary, "service.json").write_text(json.dumps({
                    "url": f"http://127.0.0.1:{server.server_port}", "token": "expired-session"
                }), encoding="utf-8")
                self.assertFalse(service_status(temporary)["running"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_service_health_never_follows_redirects_with_session_token(self):
        received = []

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/api/health":
                    self.send_response(302)
                    self.send_header("Location", "/stolen")
                    self.end_headers()
                    return
                received.append(self.headers.get("X-WBot-Token"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"product":"wbot-assistant"}')

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                Path(temporary, "service.json").write_text(json.dumps({
                    "url": f"http://127.0.0.1:{server.server_port}", "token": "local-secret"
                }), encoding="utf-8")
                self.assertFalse(service_status(temporary)["running"])
                self.assertEqual(received, [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_state_directory_is_exclusively_owned(self):
        with tempfile.TemporaryDirectory() as temporary:
            with ServiceLock(temporary):
                with self.assertRaisesRegex(RuntimeError, "已有"):
                    with ServiceLock(temporary):
                        self.fail("second service acquired the same directory")
            with ServiceLock(temporary):
                pass

    def test_detached_service_executes_jobs_and_restores_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "assistant state"
            project = Path(temporary) / "project"
            create_project(project, "lifecycle-demo")
            (project / "main.py").write_text(
                'import time\nfrom wbot import runtime\n'
                'time.sleep(0.3)\nprint("background complete")\n'
                'runtime.set_result({"continued": True})\n', encoding="utf-8")

            def command(action):
                completed = subprocess.run(
                    [sys.executable, "-m", "app.assistant", action, "--state-dir", str(state), "--port", "0"],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                return json.loads(completed.stdout)

            opened = command("start")
            opener = build_opener(ProxyHandler({}))

            def api(path, body=None):
                session = json.load(opener.open(opened["url"] + "/api/session", timeout=3))
                headers = {"X-WBot-Token": session["token"]}
                if body is not None:
                    headers["Content-Type"] = "application/json"
                request = Request(opened["url"] + path,
                                  None if body is None else json.dumps(body).encode(), headers)
                return json.load(opener.open(request, timeout=5))

            try:
                self.assertTrue(command("status")["running"])
                self.assertEqual(command("start")["url"], opened["url"])
                from tests.flow_environment import prepare_environment
                prepare_environment(project)
                package = api("/api/projects", {"path": str(project)})["package"]
                job = api("/api/jobs", {"package_id": package["id"], "parameters": {}})["job"]
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    job = api("/api/jobs/" + job["id"])["job"]
                    if job["state"] not in ("preparing", "running"):
                        break
                    time.sleep(0.05)
                self.assertEqual(job["state"], "succeeded", job)
                self.assertEqual(job["result"], {"continued": True})
                self.assertIn("background complete", api("/api/jobs/" + job["id"] + "/log")["log"])
                command("stop")
                opened = command("start")
                self.assertEqual(api("/api/jobs/" + job["id"])["job"]["state"], "succeeded")
            finally:
                command("stop")
            self.assertFalse(command("status")["running"])


if __name__ == "__main__":
    unittest.main()
