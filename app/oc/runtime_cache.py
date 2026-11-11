"""Redis 仅保存可丢弃的 Robot 活跃状态；不可用于授权或作业去重。"""
import json
import logging
import time


class RobotRuntimeCache:
    def __init__(self, url, namespace):
        from redis import Redis
        from redis.backoff import NoBackoff
        from redis.retry import Retry
        self.client = Redis.from_url(url, decode_responses=True, socket_connect_timeout=.3,
                                     socket_timeout=.3, retry=Retry(NoBackoff(), 0), max_connections=16)
        self.prefix = namespace + ':robot:'
        self.retry_after = 0

    def _request(self, operation):
        from redis.exceptions import RedisError
        if time.monotonic() < self.retry_after:
            return None
        try:
            return operation()
        except RedisError:
            self.retry_after = time.monotonic() + 5
            logging.warning('Redis 暂不可用，Robot 心跳回退到持久化存储')
            return None

    def read(self, identifier):
        content = self._request(lambda: self.client.get(self.prefix + identifier))
        if not content:
            return None
        try:
            value = json.loads(content)
            if (not isinstance(value, dict) or set(value) != {'last_seen', 'busy', 'saved_at'}
                    or type(value['last_seen']) not in (int, float) or type(value['saved_at']) not in (int, float)
                    or type(value['busy']) is not bool
                    or not 0 <= value['last_seen'] <= time.time() + 5
                    or not 0 <= value['saved_at'] <= time.time() + 5):
                return None
            return value
        except (ValueError, TypeError):
            return None

    def write(self, identifier, last_seen, busy, saved_at):
        content = json.dumps({'last_seen': last_seen, 'busy': busy, 'saved_at': saved_at}, allow_nan=False)
        return bool(self._request(lambda: self.client.set(self.prefix + identifier, content, ex=90)))

    def close(self):
        self.client.close()
