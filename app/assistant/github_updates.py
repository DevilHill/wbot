"""从公开 GitHub Releases 获取 Assistant 正式版本，不携带 OC 或 GitHub 凭据。"""
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener

from app.assistant_release import ARCHIVE_NAME, UPDATE_FILE, update_metadata, version_key
from .lifecycle import NoRedirect


REPOSITORY = 'DevilHill/wbot'
API_URL = 'https://api.github.com/repos/' + REPOSITORY
TAG_PREFIX = 'assistant-v'
DOWNLOAD_HOSTS = {'api.github.com', 'github.com', 'release-assets.githubusercontent.com',
                  'objects.githubusercontent.com'}


def require_github_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in DOWNLOAD_HOSTS
            or parsed.port not in (None, 443) or parsed.username is not None
            or parsed.password is not None or parsed.fragment):
        raise ValueError('GitHub 更新地址必须是受信任的 HTTPS 地址')


class GitHubUpdates:
    def __init__(self, stop):
        self.stop = stop
        self.opener = build_opener(NoRedirect())

    def _open(self, url, accept):
        for _ in range(6):
            self._require_running()
            require_github_url(url)
            # 每次跳转重新构造请求，只发送公开读取所需的头部。
            request = Request(url, headers={'Accept': accept, 'User-Agent': 'WBotAssistant-Updater'})
            try:
                return self.opener.open(request, timeout=10)
            except HTTPError as exc:
                with exc:
                    if exc.code in (301, 302, 303, 307, 308):
                        location = exc.headers.get('Location')
                        if not location:
                            raise ConnectionError('GitHub 更新下载缺少跳转地址') from None
                        url = urljoin(url, location)
                        continue
                    if exc.code in (403, 429):
                        raise ConnectionError('GitHub 请求受限，请稍后重试') from None
                    if exc.code == 404:
                        raise ConnectionError('GitHub 更新版本不存在、已撤回或仓库不可公开访问') from None
                    raise ConnectionError(f'GitHub 更新请求失败（HTTP {exc.code}）') from None
            except (OSError, URLError) as exc:
                raise ConnectionError('无法连接 GitHub，请检查网络、代理和服务器证书后重试') from exc
        raise ConnectionError('GitHub 更新下载跳转次数过多')

    def _require_running(self):
        if self.stop.is_set():
            raise InterruptedError('Assistant 执行服务正在停止')

    def _chunks(self, response, timeout):
        deadline = time.monotonic() + timeout
        while True:
            self._require_running()
            chunk = response.read1(65536)
            if time.monotonic() > deadline:
                raise ConnectionError('GitHub 更新响应超时，请重试')
            if not chunk:
                return
            yield chunk

    def _json(self, url, limit=8 * 1024 * 1024, accept='application/vnd.github+json'):
        content = bytearray()
        with self._open(url, accept) as response:
            for chunk in self._chunks(response, 30):
                content.extend(chunk)
                if len(content) > limit:
                    raise ValueError('GitHub 更新响应超过大小限制')
        try:
            return json.loads(content)
        except (ValueError, UnicodeError) as exc:
            raise ValueError('GitHub 更新响应不是有效的 JSON') from exc

    @staticmethod
    def _version(release):
        if not isinstance(release, dict) or release.get('draft') is not False or release.get('prerelease') is not False:
            return None
        tag = release.get('tag_name', '')
        if not isinstance(tag, str) or not tag.startswith(TAG_PREFIX):
            return None
        version = tag.removeprefix(TAG_PREFIX)
        try:
            version_key(version)
        except ValueError:
            return None
        return version

    def latest(self, current):
        newest = None
        newest_key = version_key(current)
        # GitHub 的顺序不能代替版本比较，也不能把其他产品的 latest 用作 Assistant 最新版。
        for page in range(1, 21):
            releases = self._json(f'{API_URL}/releases?per_page=100&page={page}')
            if not isinstance(releases, list):
                raise ValueError('GitHub 版本列表格式无效')
            for release in releases:
                version = self._version(release)
                if version is not None and version_key(version) > newest_key:
                    newest, newest_key = release, version_key(version)
            if len(releases) < 100:
                return self._metadata(newest) if newest is not None else None
        raise ValueError('GitHub 版本列表超过检查范围，无法确认最新版本')

    @staticmethod
    def _asset(release, name):
        assets = release.get('assets')
        if not isinstance(assets, list):
            raise ValueError('GitHub 更新附件列表无效')
        matches = [asset for asset in assets if isinstance(asset, dict) and asset.get('name') == name]
        if (len(matches) != 1 or matches[0].get('state') != 'uploaded'
                or type(matches[0].get('id')) is not int or matches[0]['id'] <= 0):
            raise ValueError(f'GitHub 正式版本缺少完整的 {name} 附件')
        return matches[0]

    def _metadata(self, release):
        version = self._version(release)
        if version is None:
            raise ValueError('该 GitHub 版本不是可安装的 Assistant 正式版本')
        manifest_asset = self._asset(release, UPDATE_FILE)
        archive_asset = self._asset(release, ARCHIVE_NAME)
        manifest = self._json(f'{API_URL}/releases/assets/{manifest_asset["id"]}',
                              limit=65536, accept='application/octet-stream')
        metadata = update_metadata(manifest)
        if (metadata['version'] != version or manifest.get('asset_name') != ARCHIVE_NAME
                or type(archive_asset.get('size')) is not int or metadata['size'] != archive_asset['size']):
            raise ValueError('GitHub 标签、清单和更新附件信息不一致')
        digest = archive_asset.get('digest')
        if digest is not None and digest != 'sha256:' + metadata['sha256']:
            raise ValueError('GitHub 附件摘要与更新清单不一致')
        return dict(metadata, asset_id=archive_asset['id'])

    def release(self, version):
        version_key(version)
        release = self._json(f'{API_URL}/releases/tags/{TAG_PREFIX}{version}')
        metadata = self._metadata(release)
        if metadata['version'] != version:
            raise ValueError('GitHub 返回了不同版本的更新包')
        return metadata

    def download(self, release, destination, *, on_progress=None):
        update_metadata(release)
        if type(release.get('asset_id')) is not int or release['asset_id'] <= 0:
            raise ValueError('GitHub 更新附件标识无效')
        destination = Path(destination)
        digest = hashlib.sha256()
        received = 0
        created = False
        try:
            with self._open(f'{API_URL}/releases/assets/{release["asset_id"]}', 'application/octet-stream') as response:
                with destination.open('xb') as output:
                    created = True
                    for chunk in self._chunks(response, 300):
                        received += len(chunk)
                        if received > release['size']:
                            raise ValueError('GitHub 更新包超过声明大小')
                        digest.update(chunk)
                        output.write(chunk)
                        if on_progress is not None:
                            on_progress(received)
            if received != release['size'] or digest.hexdigest() != release['sha256']:
                raise ValueError('GitHub 更新包校验失败，请重新下载')
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
