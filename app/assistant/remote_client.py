"""Assistant 主动访问所选 OC；凭据仅发送到配置的原始地址。"""
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, build_opener, ProxyHandler

from .lifecycle import NoRedirect


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 68 * 1024 * 1024


def normalize_server_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError('请填写 OC 接入地址，例如 https://oc.example.com')
    value = value.strip()
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError('OC 地址不能包含空白或控制字符')
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.path not in ('', '/')):
        raise ValueError('OC 地址须为 http(s)://主机[:端口]，不能包含账号、路径或查询参数')
    port = parsed.port
    if port == 0:
        raise ValueError('OC 端口必须大于 0')
    hostname = parsed.hostname.lower()
    if ':' in hostname:
        hostname = '[' + hostname + ']'
    return urlunsplit((parsed.scheme.lower(), hostname + (f':{port}' if port else ''), '', '', ''))


class GatewayError(ConnectionError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class GatewayClient:
    def __init__(self, settings, timeout=5, stop=None):
        self.url = normalize_server_url(settings['server_url'])
        self.device_id = settings['device_id']
        self.secret = settings['secret']
        self.timeout = timeout
        self.stop = stop
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _request(self, endpoint, body=None):
        if not endpoint.startswith('/api/agent/') or any(character in endpoint for character in '?\r\n#'):
            raise ValueError('无效的 OC 接口地址')
        headers = {'X-WBot-Device': self.device_id, 'X-WBot-Device-Token': self.secret}
        content = None
        if body is not None:
            content = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(content) > 6 * 1024 * 1024:
                raise ValueError('OC 同步内容超过 6 MiB')
            headers['Content-Type'] = 'application/json'
        request = Request(self.url + endpoint, content, headers)
        try:
            return self.opener.open(request, timeout=self.timeout)
        except HTTPError as exc:
            try:
                if 300 <= exc.code < 400:
                    raise GatewayError('OC 返回重定向，请填写最终接入地址；设备凭据未被转发', exc.code) from None
                try:
                    payload = json.loads(exc.read1(65536).decode('utf-8'))
                    message = str(payload.get('error') or f'OC 请求被拒绝（{exc.code}）')[:1000]
                except (ValueError, UnicodeError, AttributeError):
                    message = f'OC 请求被拒绝（{exc.code}）'
            finally:
                exc.close()
            raise GatewayError(message, exc.code) from None
        except OSError as exc:
            raise GatewayError('无法连接 OC，请检查地址、网络和服务器证书') from exc

    def request(self, endpoint, body=None):
        content = bytearray()
        deadline = time.monotonic() + 15
        with self._request(endpoint, body) as response:
            while chunk := response.read1(65536):
                if self.stop is not None and self.stop.is_set():
                    raise InterruptedError('Assistant 执行服务正在停止')
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise GatewayError('OC 返回的数据超过 8 MiB')
                if time.monotonic() > deadline:
                    raise GatewayError('OC 响应超时')
        try:
            payload = json.loads(content.decode('utf-8'))
        except (ValueError, UnicodeError) as exc:
            raise GatewayError('OC 返回的数据格式无效') from exc
        if not isinstance(payload, dict):
            raise GatewayError('OC 返回的数据必须是对象')
        return payload

    def download(self, command, destination, stop):
        endpoint = '/api/agent/jobs/' + command['id'] + '/package'
        if command.get('package_url') != endpoint:
            raise ValueError('OC 发布包地址与当前作业不匹配')
        expected_size = command.get('package_size')
        if type(expected_size) is not int or not 0 < expected_size <= MAX_ARCHIVE_BYTES:
            raise ValueError('OC 发布包大小无效或超过 68 MiB')
        digest = hashlib.sha256()
        received = 0
        deadline = time.monotonic() + 120
        with self._request(endpoint) as response, Path(destination).open('xb') as output:
            while chunk := response.read1(65536):
                if stop.is_set():
                    raise InterruptedError('Assistant 执行服务正在停止')
                received += len(chunk)
                if received > expected_size or time.monotonic() > deadline:
                    raise ValueError('OC 发布包下载超出声明大小或超时')
                digest.update(chunk)
                output.write(chunk)
        if received != expected_size or digest.hexdigest() != command.get('package_sha256'):
            raise ValueError('OC 发布包校验失败，未执行自动化')
