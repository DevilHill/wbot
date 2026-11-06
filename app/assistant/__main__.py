"""Assistant 启动入口；界面和后台服务分别拥有生命周期。"""
import argparse
import json
from pathlib import Path
import sys
import webbrowser

from .lifecycle import serve, service_status, start_service, stop_service


def load_desktop():
    try:
        from .qt_app import open_desktop
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith('PySide6'):
            raise RuntimeError('未安装 Qt 桌面依赖，请执行 python -m pip install -r requirements-assistant.txt；'
                               '仅需旧网页诊断界面时可使用 open --browser') from exc
        raise
    return open_desktop


def report(payload, error=False):
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        print(json.dumps(payload, ensure_ascii=False), file=stream)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="WBot Assistant 本地执行客户端")
    parser.add_argument("action", choices=("start", "serve", "open", "status", "stop"))
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".wbot-assistant",
                        help="发布包与运行记录目录")
    parser.add_argument("--port", type=int, default=8791, help="本机端口；0 为自动分配")
    parser.add_argument("--browser", action="store_true", help="open 时使用旧网页诊断界面；默认打开 Qt 桌面窗口")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("端口须为 0–65535")
    try:
        if args.action == "serve":
            serve(args.state_dir, args.port)
            return 0
        if args.action in ("start", "open"):
            desktop = load_desktop() if args.action == 'open' and not args.browser else None
            result = start_service(args.state_dir, args.port)
            if args.action == "open":
                if args.browser:
                    webbrowser.open(result['url'])
                else:
                    exit_code = desktop(args.state_dir)
                    if exit_code:
                        return exit_code
        elif args.action == "stop":
            result = stop_service(args.state_dir)
        else:
            result = service_status(args.state_dir)
        report(result)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        report({'error': str(exc)}, error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
