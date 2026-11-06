"""读取 Assistant 运行上下文的参数，并写入结构化结果。"""
import json
import os
from pathlib import Path
import tempfile

MAX_RESULT_BYTES = 1024 * 1024


def _context():
    path = os.environ.get('WBOT_RUN_INPUT')
    if not path:
        raise RuntimeError('没有 WBot 运行上下文，请通过 Assistant 执行发布包')
    try:
        context = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(context, dict) or not isinstance(context.get('parameters'), dict):
            raise ValueError('parameters 必须为对象')
        if not isinstance(context.get('job_id'), str) or not context['job_id']:
            raise ValueError('缺少 job_id')
        return context
    except (OSError, ValueError) as error:
        raise RuntimeError(f'无法读取 WBot 运行上下文：{error}') from error


def parameters():
    """返回当前作业经过校验并合并默认值的输入参数。"""
    return _context()['parameters']


def job_id():
    """返回执行服务与当前任务共用的作业标识。"""
    return _context()['job_id']


def set_result(result):
    """原子替换当前作业的 JSON 对象结果，上限为 1 MiB。"""
    _context()
    destination = os.environ.get('WBOT_RUN_RESULT')
    if not destination:
        raise RuntimeError('运行上下文缺少结果文件路径')
    if not isinstance(result, dict):
        raise TypeError('运行结果必须是 JSON 对象')
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_RESULT_BYTES:
        raise ValueError('运行结果超过 1 MiB，请通过文件输出较大内容')
    target = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.result-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
