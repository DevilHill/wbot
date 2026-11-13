"""Assistant 本机接口的授权、路径和任务请求边界。"""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from app.assistant.server import create_server


class RecordingExecution:
    def __init__(self, state_dir):
        self.submissions = []
        self.state_dir = Path(state_dir)
        self.updating = False

    def list_packages(self):
        return [{"id": "demo-1", "manifest": {"name": "演示", "version": "1.0.0"}}]

    def list_jobs(self):
        return []

    def job_summary(self):
        return {"items": [{"id": "job-1", "state": "running"}], "total": 1}

    def submit(self, package_id, parameters, request_id=None):
        self.submissions.append((package_id, parameters, request_id))
        return {"id": "job-1", "state": "preparing"}

    def host_project(self, path):
        self.submissions.append(str(path))
        return {'id': 'hosted@1.0.0'}

    def get_job(self, job_id):
        raise KeyError(job_id)


class AssistantServerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.execution = RecordingExecution(temporary.name)
        self.server = create_server(self.execution)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.address = f"127.0.0.1:{self.server.server_port}"
        self.origin = "http://" + self.address

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, body=None, headers=None):
        connection = http.client.HTTPConnection(self.address, timeout=3)
        actual_headers = {"Host": self.address}
        if body is not None:
            actual_headers["Content-Type"] = "application/json"
        actual_headers.update(headers or {})
        connection.request("POST" if body is not None else "GET", path,
                           None if body is None else json.dumps(body), actual_headers)
        response = connection.getresponse()
        content = response.read()
        result = response.status, dict(response.getheaders()), content
        connection.close()
        return result

    def test_same_origin_session_can_submit_and_read_packages(self):
        status, headers, body = self.request("/api/session")
        self.assertEqual(status, 200)
        token = json.loads(body)["token"]
        self.assertIn("no-store", headers["Cache-Control"])
        auth = {"X-WBot-Token": token, "Origin": self.origin}
        status, _, body = self.request("/api/packages", headers=auth)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["items"][0]["id"], "demo-1")
        status, _, body = self.request("/api/jobs", {
            "package_id": "demo-1", "parameters": {"name": "测试"}, "request_id": "request-1"
        }, auth)
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body)["job"]["id"], "job-1")
        self.assertEqual(self.execution.submissions, [("demo-1", {"name": "测试"}, "request-1")])

    def test_cross_origin_invalid_host_and_missing_token_are_rejected(self):
        cases = [
            ("/api/session", None, {"Host": "attacker.example"}),
            ("/api/session", None, {"Origin": "https://attacker.example"}),
            ("/api/session", None, {"Sec-Fetch-Site": "cross-site"}),
            ("/api/jobs", {"package_id": "demo-1"}, {}),
            ("/api/jobs", {"package_id": "demo-1"}, {"X-WBot-Token": "é"}),
            ("/api/jobs", {"package_id": "demo-1"}, {
                "X-WBot-Token": self.server.token, "Origin": "null"
            }),
        ]
        for path, body, headers in cases:
            with self.subTest(path=path, headers=headers):
                self.assertEqual(self.request(path, body, headers)[0], 403)
        self.assertEqual(self.execution.submissions, [])

    def test_project_registration_requires_local_authorization_and_absolute_directory(self):
        auth = {'X-WBot-Token': self.server.token}
        project = str(Path(self.execution.state_dir) / 'flow')
        self.assertEqual(self.request('/api/projects', {'path': project})[0], 403)
        self.assertEqual(self.request('/api/projects', {'path': 'relative'}, auth)[0], 400)
        self.assertEqual(self.request('/api/projects', {'path': project, 'python': 'shared'}, auth)[0], 400)
        self.assertEqual(self.request('/api/projects', {'path': project}, auth)[0], 201)
        self.assertEqual(self.execution.submissions, [project])

    def test_malformed_inputs_are_rejected_before_execution(self):
        auth = {"X-WBot-Token": self.server.token}
        for body in ([], {"package_id": ""}, {"package_id": "demo-1", "parameters": []}):
            with self.subTest(body=body):
                self.assertEqual(self.request("/api/jobs", body, auth)[0], 400)
        self.assertEqual(self.execution.submissions, [])

    def test_only_known_static_assets_and_jobs_are_accessible(self):
        self.assertEqual(self.request("/")[0], 200)
        self.assertEqual(self.request("/../server.py")[0], 404)
        self.assertEqual(self.request("/api/jobs/missing", headers={"X-WBot-Token": self.server.token})[0], 404)

    def test_job_summary_is_authorized_and_has_total(self):
        self.assertEqual(self.request("/api/jobs/summary")[0], 403)
        status, _, body = self.request("/api/jobs/summary", headers={"X-WBot-Token": self.server.token})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), self.execution.job_summary())


if __name__ == "__main__":
    unittest.main()
