import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from app.assistant.github_updates import GitHubUpdates, API_URL, ARCHIVE_NAME
from app.assistant.connection import ConnectionService
from app.assistant.execution import ExecutionService
from app.assistant.updates import UpdateService
from app.assistant_release import file_digest, inspect_release
from build_assistant import write_update_manifest
from tests.test_assistant_releases import release_zip


def github_release(version='99.0.0', **values):
    return dict(id=1, tag_name='assistant-v' + version, draft=False, prerelease=False,
                assets=[{'id': 11, 'name': 'assistant-update.json', 'state': 'uploaded'},
                        {'id': 12, 'name': ARCHIVE_NAME, 'state': 'uploaded', 'size': 3}], **values)


class Responses:
    def __init__(self, values):
        self.values = values
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        value = self.values[request.full_url]
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(value if isinstance(value, bytes) else json.dumps(value).encode())


class GitHubUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = release_zip(self.root / ARCHIVE_NAME, version='99.0.0')
        self.manifest = dict(inspect_release(self.archive), asset_name=ARCHIVE_NAME,
                             size=self.archive.stat().st_size, sha256=file_digest(self.archive))
        self.release = github_release()
        self.release['assets'][1]['size'] = self.manifest['size']
        self.responses = Responses({
            API_URL + '/releases?per_page=100&page=1': [self.release],
            API_URL + '/releases/tags/assistant-v99.0.0': self.release,
            API_URL + '/releases/assets/11': self.manifest,
            API_URL + '/releases/assets/12': self.archive.read_bytes(),
        })
        self.client = GitHubUpdates(threading.Event())
        self.client.opener = self.responses

    def test_pagination_product_filter_and_numeric_order(self):
        unrelated = dict(self.release, tag_name='vscode-v999.0.0')
        self.responses.values[API_URL + '/releases?per_page=100&page=1'] = [unrelated] * 100
        self.responses.values[API_URL + '/releases?per_page=100&page=2'] = [
            dict(self.release, tag_name='assistant-v100.0.0', prerelease=True),
            dict(self.release, tag_name='assistant-v101.0.0', draft=True),
            dict(self.release, tag_name='assistant-v9.0.0'), self.release]
        self.assertEqual(self.client.latest('0.9.0')['version'], '99.0.0')
        self.assertIsNone(self.client.latest('99.0.0'))

    def test_download_verifies_bytes_and_progress(self):
        release = self.client.latest('0.9.0')
        progress = []
        target = self.root / 'download.zip'
        self.client.download(release, target, on_progress=progress.append)
        self.assertEqual(target.read_bytes(), self.archive.read_bytes())
        self.assertEqual(progress[-1], self.manifest['size'])

    def test_missing_asset_or_mismatched_metadata_fails_check(self):
        for change in ({'version': '98.0.0'}, {'size': 1}, {'sha256': 'g' * 64},
                       {'asset_name': 'other.zip'}, {'platform': 'linux-x64'}):
            with self.subTest(change=change):
                self.responses.values[API_URL + '/releases/assets/11'] = dict(self.manifest, **change)
                with self.assertRaises(ValueError):
                    self.client.latest('0.9.0')
        self.release['assets'] = []
        with self.assertRaises(ValueError):
            self.client.latest('0.9.0')

    def test_corrupt_or_cancelled_download_removes_partial_file(self):
        release = self.client.latest('0.9.0')
        self.responses.values[API_URL + '/releases/assets/12'] = b'corrupt'
        target = self.root / 'download.zip'
        with self.assertRaises(ValueError):
            self.client.download(release, target)
        self.assertFalse(target.exists())
        self.client.stop.set()
        with self.assertRaises(InterruptedError):
            self.client.download(release, target)
        self.assertFalse(target.exists())

    def test_redirects_are_limited_to_github_https_without_credentials(self):
        url = API_URL + '/releases/assets/11'
        target = 'https://release-assets.githubusercontent.com/example?signature=value'
        self.responses.values[url] = HTTPError(url, 302, 'redirect', {'Location': target}, None)
        self.responses.values[target] = self.manifest
        self.assertEqual(self.client.latest('0.9.0')['version'], '99.0.0')
        self.assertNotIn('Authorization', self.responses.requests[-1].headers)
        for location in ('http://github.com/file', 'https://evil.example/file',
                         'https://user:secret@github.com/file', 'https://github.com:444/file', url):
            with self.subTest(location=location):
                self.responses.values[url] = HTTPError(url, 302, 'redirect', {'Location': location}, None)
                with self.assertRaises((ValueError, ConnectionError)):
                    self.client.latest('0.9.0')

    def test_rate_limit_and_invalid_response_are_failures(self):
        url = API_URL + '/releases?per_page=100&page=1'
        for value in (HTTPError(url, 403, 'limited', {}, None), b'not json', {}):
            with self.subTest(value=value):
                self.responses.values[url] = value
                with self.assertRaises((ValueError, ConnectionError)):
                    self.client.latest('0.9.0')

    def test_revalidation_rejects_withdrawn_release(self):
        self.release['draft'] = True
        with self.assertRaises(ValueError):
            self.client.release('99.0.0')

    def test_build_manifest_matches_actual_archive(self):
        output = write_update_manifest(self.archive)
        self.assertEqual(json.loads(output.read_text(encoding='utf-8')), self.manifest)

    def update_service(self):
        execution = ExecutionService(self.root / 'data')
        self.addCleanup(execution.shutdown)
        connection = ConnectionService(execution.state_dir, execution)
        self.addCleanup(connection.close)
        updates = UpdateService(execution, connection)
        self.addCleanup(updates.close)
        updates.bundle = self.root / 'installed'
        (updates.bundle / 'python').mkdir(parents=True)
        (updates.bundle / 'python/python.exe').write_bytes(b'python')
        (updates.bundle / 'WBotAssistant.exe').write_bytes(b'old')
        return updates, connection, execution

    def test_unconfigured_assistant_downloads_and_starts_existing_installer(self):
        updates, _, execution = self.update_service()
        with patch('app.assistant.updates.GitHubUpdates', return_value=self.client):
            updates.check()
            updates._thread.join(5)
            self.assertEqual(updates.snapshot()['source'], 'github')
            self.assertEqual(updates.snapshot()['status'], 'available')
            updates.download()
            updates._thread.join(5)
            self.assertEqual(updates.snapshot()['status'], 'ready', updates.snapshot())
            with patch('app.assistant.updates.subprocess.Popen') as launched:
                updates.install(999999)
            self.assertTrue(execution.updating)
            self.assertEqual(updates.snapshot()['status'], 'installing')
            self.assertIn('update_worker.py', launched.call_args.args[0][1])

    def test_configured_oc_never_falls_back_to_github(self):
        updates, connection, _ = self.update_service()
        connection.connect('https://oc.example.test', 'managed')
        for binding, enabled in [('pending', True), ('revoked', True), ('approved', False)]:
            settings = connection.store.settings()
            connection.store.save_settings(dict(settings, binding_state=binding, enabled=enabled))
            with patch('app.assistant.updates.GitHubUpdates') as github:
                updates.check()
                updates._thread.join(5)
                self.assertEqual(updates.snapshot()['status'], 'failed')
                self.assertEqual(updates.snapshot()['source'], 'oc')
                github.assert_not_called()

    def test_binding_after_download_blocks_github_install(self):
        updates, connection, execution = self.update_service()
        with patch('app.assistant.updates.GitHubUpdates', return_value=self.client):
            updates.check()
            updates._thread.join(5)
            updates.download()
            updates._thread.join(5)
            self.assertEqual(updates.snapshot()['status'], 'ready')
            connection.connect('https://oc.example.test', 'managed')
            with self.assertRaises((ValueError, PermissionError)):
                updates.install(999999)
        self.assertFalse(execution.updating)

    def test_failed_recheck_does_not_leave_old_release_ready(self):
        updates, _, _ = self.update_service()
        with patch('app.assistant.updates.GitHubUpdates', return_value=self.client):
            updates.check()
            updates._thread.join(5)
            updates.download()
            updates._thread.join(5)
            self.assertTrue(updates.snapshot()['ready'])
            self.responses.values[API_URL + '/releases?per_page=100&page=1'] = b'broken'
            updates.check()
            updates._thread.join(5)
            self.assertEqual(updates.snapshot()['status'], 'failed')
            self.assertFalse(updates.snapshot()['ready'])
            self.assertIsNone(updates.snapshot()['release'])


if __name__ == '__main__':
    unittest.main()
