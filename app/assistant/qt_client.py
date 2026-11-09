"""Qt 界面异步调用本机执行服务，不接管服务和任务的生命周期。"""
import json
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest

from .lifecycle import _read_metadata
from .protocol import MAX_REQUEST_BYTES


SETTINGS_UNSUPPORTED = ('当前本机后台不支持连接设置。请先完成正在运行的任务，再停止旧后台并从新版 Assistant 重新启动；'
                        '只关闭窗口不会停止后台。')


MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class AssistantClient(QObject):
    def __init__(self, state_dir, parent=None, timeout_ms=15000):
        super().__init__(parent)
        self.state_dir = Path(state_dir)
        self.timeout_ms = timeout_ms
        self.manager = QNetworkAccessManager(self)
        self.manager.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self.manager.setRedirectPolicy(QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        self._pending = set()
        self._closed = False

    def request(self, method, path, body=None, on_success=None, on_error=None):
        if self._closed:
            return None
        try:
            if (method not in ('GET', 'POST') or not isinstance(path, str)
                    or not path.startswith('/api/') or any(character in path for character in '\r\n#')):
                raise ValueError('仅允许 Assistant 本机接口请求')
            metadata = _read_metadata(self.state_dir)
            if metadata is None:
                raise ValueError('后台服务未启动，请重新打开 Assistant')
            request = QNetworkRequest(QUrl(metadata['url'] + path))
            request.setRawHeader(b'X-WBot-Token', metadata['token'].encode('utf-8'))
            request.setAttribute(QNetworkRequest.Attribute.Http2AllowedAttribute, False)
            request.setTransferTimeout(self.timeout_ms)
            if method == 'POST':
                content = json.dumps(body if body is not None else {}, ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')
                if len(content) > MAX_REQUEST_BYTES:
                    raise ValueError('提交内容超过 2 MiB，请缩短参数后重试')
                request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
                reply = self.manager.post(request, content)
            else:
                reply = self.manager.get(request)
        except (OSError, ValueError, TypeError) as exc:
            message = str(exc)
            QTimer.singleShot(0, lambda: self._notify_error(on_error, message))
            return None
        self._pending.add(reply)
        content = bytearray()
        failure = []
        timer = QTimer(reply)
        timer.setSingleShot(True)

        def read_content():
            content.extend(bytes(reply.readAll()))
            if len(content) > MAX_RESPONSE_BYTES:
                failure.append('后台响应超过 16 MiB，无法显示；请检查后台服务日志')
                if reply.isRunning():
                    reply.abort()

        def timed_out():
            failure.append('后台服务响应超时；运行请求可能已接受，请在运行记录中核对')
            reply.abort()

        def finished():
            timer.stop()
            self._pending.discard(reply)
            try:
                if self._closed:
                    return
                if not failure:
                    read_content()
                if failure:
                    raise ValueError(failure[0])
                status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                if status is not None and 300 <= int(status) < 400:
                    raise ValueError('后台服务返回了重定向，已拒绝转发会话')
                if status is None:
                    raise ValueError('无法连接后台服务，请检查服务是否运行')
                if int(status) == 404 and (path == '/api/settings' or path.startswith('/api/settings/')):
                    raise ValueError(SETTINGS_UNSUPPORTED)
                if int(status) == 404 and (path == '/api/updates' or path.startswith('/api/updates/')):
                    raise ValueError('当前后台尚不支持在线更新，请先完成任务并手动升级到支持在线更新的便携版。')
                try:
                    payload = json.loads(content.decode('utf-8'))
                except (ValueError, UnicodeError) as exc:
                    raise ValueError('后台服务返回了无效的 JSON 数据') from exc
                if not isinstance(payload, dict):
                    raise ValueError('后台服务返回格式无效')
                if not 200 <= int(status) < 300:
                    raise ValueError(str(payload.get('error') or f'后台请求失败（{status}）'))
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    raise ValueError('后台响应未完整接收，请重新核对运行记录')
                if on_success is not None:
                    on_success(payload)
            except (ValueError, UnicodeError) as exc:
                self._notify_error(on_error, str(exc))
            finally:
                reply.deleteLater()

        reply.readyRead.connect(read_content)
        reply.finished.connect(finished)
        timer.timeout.connect(timed_out)
        timer.start(self.timeout_ms)
        return reply

    def _notify_error(self, callback, message):
        if not self._closed and callback is not None:
            callback(message)

    def close(self):
        self._closed = True
        for reply in list(self._pending):
            reply.abort()
        self._pending.clear()
