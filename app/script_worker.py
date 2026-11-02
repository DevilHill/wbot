"""独立脚本进程入口，源码和打包 EXE 共用；不会打开桌面窗口。"""
import io
import os
from pathlib import Path
import runpy
import sys
import traceback


class LogStream(io.TextIOBase):
    def __init__(self, stream): self.stream, self.size, self.truncated = stream, 0, False
    @property
    def encoding(self): return 'utf-8'
    def write(self, text):
        length = len(text)
        if self.size < 4 * 1024 * 1024:
            chunk = text.encode('utf-8')[:4 * 1024 * 1024 - self.size].decode('utf-8', 'ignore')
            self.stream.write(chunk); self.stream.flush()
            self.size += len(chunk.encode('utf-8'))
        elif not self.truncated:
            self.stream.write('\n[日志超过 4 MiB，后续输出已省略]\n'); self.stream.flush(); self.truncated = True
        return length
    def flush(self):
        if not self.stream.closed: self.stream.flush()


def main(args=None):
    args = list(sys.argv[1:] if args is None else args)
    file, log = map(Path, args)
    with log.open('w', encoding='utf-8', buffering=1) as stream:
        sys.stdout = sys.stderr = LogStream(stream)
        sys.stdin = io.StringIO('')
        sys.argv = [str(file)]
        sys.path.insert(0, str(file.parent))
        print(f'▶ {file.name}\n')
        try:
            # 显式导入使打包版也收集 wbot 及其本地依赖。
            import wbot  # noqa: F401
            runpy.run_path(str(file), run_name='__main__')
            return 0
        except SystemExit as exc:
            if exc.code and not isinstance(exc.code, int): print(exc.code)
            return exc.code if isinstance(exc.code, int) else int(bool(exc.code))
        except BaseException:
            traceback.print_exc()
            return 1
        finally:
            stream.flush()
            sys.stdout = sys.stderr = sys.__stdout__


if __name__ == '__main__':
    raise SystemExit(main())
