"""执行单个包的入口，避免任务目录中的同名模块遮蔽执行器。"""
import io
import json
from pathlib import Path
import runpy
import sys
import traceback


def main():
    # 父进程先建立进程树所有权，再发送启动信号。
    if sys.stdin.readline().strip() != 'start':
        return 125
    sys.stdin = io.StringIO('')
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    try:
        context = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        entry = Path(context['entry'])
        sys.argv = [str(entry)]
        sys.path.insert(0, str(entry.parent))
        runpy.run_path(str(entry), run_name='__main__')
        return 0
    except SystemExit as error:
        if error.code is None:
            return 0
        if isinstance(error.code, int):
            return error.code
        print(error.code, file=sys.stderr)
        return 1
    except BaseException:
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
