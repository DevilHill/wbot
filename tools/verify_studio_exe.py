"""验证真实打包编码版：离线编辑器、项目文件、内置 Python 运行及停止。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', required=True)
    args = parser.parse_args()
    exe = Path(args.exe).resolve()
    work = Path(tempfile.mkdtemp(prefix='verify-studio-', dir=ROOT / 'build'))
    os.environ['USERPROFILE'] = str(work / 'user')
    os.environ['LOCALAPPDATA'] = str(work / 'local')
    from tools import verify_exe as helper
    helper.EXE = str(exe)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def call(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(helper.BASE + path, data, headers={'Content-Type': 'application/json'})
        return json.load(opener.open(request, timeout=15))
    proc = subprocess.Popen([str(exe), '--serve', '--port', str(helper.PORT)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try: state = call('/api/studio/state'); break
            except Exception:
                if proc.poll() is not None: raise AssertionError('编码版提前退出')
                time.sleep(.1)
        else: raise AssertionError('编码版未就绪')
        print('[OK] 编码接口和会话凭据就绪', flush=True)
        for asset in ('index.html', 'studio.js', 'studio.css', 'vendor/monaco/vs/loader.js',
                      'vendor/monaco/vs/editor/editor.main.js'):
            raw = opener.open(helper.BASE + '/' + asset, timeout=10).read()
            assert raw == (ROOT / 'app/web' / asset).read_bytes(), asset
        print('[OK] Monaco 和编码界面内嵌资源与源码逐字节一致', flush=True)
        token = state['token']
        def api(action, **body):
            result = call('/api/studio/' + action, {'token': token, 'project': state.get('project'), **body})
            assert result.get('ok'), result
            return result
        state = api('open', path=str(work / 'project'), create=True)
        file = api('read', path='main.py')
        api('write', path='main.py', text='import wbot\nprint("内置 Python 执行成功", wbot.__version__)\n', version=file['version'])
        api('run', path='main.py')
        for _ in range(200):
            run = api('status')
            if not run['running']: break
            time.sleep(.1)
        assert run['exitCode'] == 0 and '内置 Python 执行成功' in run['log'], run
        print('[OK] 内置 Python 实际执行用户 .py 并成功导入 wbot', flush=True)
        file = api('read', path='main.py')
        api('write', path='main.py', text='import time\nprint("运行中",flush=True)\ntime.sleep(60)\n', version=file['version'])
        api('run', path='main.py')
        run = api('stop')
        assert not run['running'] and run['stopped'], run
        print('[OK] 停止按钮对应接口清理自己的脚本进程组', flush=True)
        return 0
    finally:
        helper.close_test_process(proc)


if __name__ == '__main__': raise SystemExit(main())
