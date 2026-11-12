"""用本机 VS Code 运行隔离的扩展宿主测试，不修改日常 VS Code 配置。"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--code', required=True, help='VS Code 可执行文件的绝对路径')
parser.add_argument('--python', default=sys.executable, help='已安装 wbot 与 lxml 的解释器')
parser.add_argument('--debugger-extension', help='已安装的 ms-python.debugpy 扩展目录；只复制到隔离测试目录，不联网安装')
args = parser.parse_args()
extension = Path(__file__).resolve().parents[1]
test_root = extension.parent / 'build' / 'vscode-tests'
test_root.mkdir(parents=True, exist_ok=True)
run_dir = Path(tempfile.mkdtemp(prefix='run-', dir=test_root))
workspace = run_dir / 'workspace'
workspace.mkdir()

extensions_dir = run_dir / 'extensions'
extensions_dir.mkdir()
if args.debugger_extension:
    debugger_dir = Path(args.debugger_extension).resolve()
    installed = {}
    for manifest_path in debugger_dir.parent.glob('*/package.json'):
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            identity = f'{manifest["publisher"]}.{manifest["name"]}'
            version = tuple(int(part) for part in re.findall(r'\d+', manifest.get('version', '0'))[:3])
            if identity not in installed or version > installed[identity][0]:
                installed[identity] = (version, manifest_path.parent, manifest)
        except (OSError, ValueError, KeyError):
            continue
    debugger_manifest = json.loads((debugger_dir / 'package.json').read_text(encoding='utf-8'))
    if f'{debugger_manifest.get("publisher")}.{debugger_manifest.get("name")}' != 'ms-python.debugpy':
        parser.error('--debugger-extension 必须指向 ms-python.debugpy 的已安装目录')
    copied = set()

    def copy_extension(source, manifest):
        identity = f'{manifest["publisher"]}.{manifest["name"]}'
        if identity in copied:
            return
        copied.add(identity)
        target = extensions_dir / source.name
        if not target.resolve().is_relative_to(extensions_dir.resolve()):
            raise ValueError('扩展复制目标越出测试目录')
        shutil.copytree(source, target)
        for dependency in manifest.get('extensionDependencies', []):
            if dependency not in installed:
                raise RuntimeError(f'本机缺少调试扩展依赖 {dependency}，未自动下载')
            _, dependency_dir, dependency_manifest = installed[dependency]
            copy_extension(dependency_dir, dependency_manifest)

    copy_extension(debugger_dir, debugger_manifest)
    print('隔离调试扩展：' + ', '.join(sorted(copied)), flush=True)
env = dict(os.environ, WBOT_TEST_PYTHON=str(Path(args.python).resolve()))
env['WBOT_TEST_SETTINGS_FILE'] = str(run_dir / 'user-data' / 'User' / 'settings.json')
env['WBOT_TEST_DEBUGGER'] = '1' if args.debugger_extension else '0'
env.pop('ELECTRON_RUN_AS_NODE', None)
env.pop('VSCODE_IPC_HOOK_CLI', None)
command = [args.code, '--disable-gpu', '--disable-updates',
           '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes',
           '--no-proxy-server',
           f'--user-data-dir={run_dir / "user-data"}',
           f'--extensions-dir={extensions_dir}',
           f'--extensionDevelopmentPath={extension}',
           f'--extensionTestsPath={extension / "test/integration.js"}', str(workspace)]
if not args.debugger_extension:
    command.insert(1, '--disable-extensions')
print(f'测试目录：{run_dir}', flush=True)
with (run_dir / 'host.log').open('w', encoding='utf-8') as log:
    try:
        result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        print('扩展宿主测试超时，请检查 host.log')
        raise SystemExit(1)
report = workspace / 'integration-report.json'
if report.exists():
    print(report.read_text(encoding='utf-8'))
else:
    print((run_dir / 'host.log').read_text(encoding='utf-8')[-8000:])
raise SystemExit(result.returncode if report.exists() else 1)
