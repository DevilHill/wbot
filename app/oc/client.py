"""通过现有会话文件连接本机 Assistant，不向浏览器暴露执行端令牌。"""
import json
from pathlib import Path
from urllib.error import HTTPError

from app.assistant.lifecycle import _read_metadata, _request


class AssistantRejected(ValueError):
    """执行端明确拒绝请求，因此可以记录为未被接受。"""


class AssistantClient:
    def __init__(self, state_dir):
        self.state_dir = Path(state_dir)

    def request(self, endpoint, body=None):
        try:
            metadata = _read_metadata(self.state_dir)
            if metadata is None:
                raise ConnectionError('Assistant 未启动或服务记录不存在')
            result = _request(metadata, endpoint, body)
        except HTTPError as exc:
            if exc.code in (400, 403, 404, 409):
                try:
                    error = json.loads(exc.read(65536)).get('error', '')
                except (ValueError, AttributeError):
                    error = ''
                raise AssistantRejected(str(error) or f'Assistant 拒绝请求（{exc.code}）') from None
            raise ConnectionError(f'Assistant 服务响应异常（{exc.code}）') from None
        except (OSError, ValueError, TypeError) as exc:
            raise ConnectionError('无法连接 Assistant，请检查其后台服务和数据目录') from exc
        if not isinstance(result, dict):
            raise ConnectionError('Assistant 返回格式无效')
        return result

    def health(self):
        if self.request('/api/health').get('product') != 'wbot-assistant':
            raise ConnectionError('数据目录指向的服务不是 WBot Assistant')

    def jobs(self):
        items = self.request('/api/jobs').get('items')
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ConnectionError('Assistant 作业列表格式无效')
        return items
