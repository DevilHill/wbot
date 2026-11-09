"""构建 Windows Qt Assistant 便携目录，携带独立的任务 Python。

在安装 requirements-assistant.txt 和 PyInstaller 的 Python 中运行本脚本。
构建只复制明确的 CPython 运行文件、依赖和执行源码，不复制开发环境。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
import zipfile
from uuid import uuid4


ROOT = Path(__file__).resolve().parent
SKIP_DIRECTORIES = {'__pycache__', 'site-packages', 'test', 'tests', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip'}


def run(command, **options):
    return subprocess.run(command, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **options)


def copy_tree(source, destination):
    shutil.copytree(source, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo', 'tests'))


def copy_stdlib(base, target):
    library = base / 'Lib'
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for directory, names, files in os.walk(library):
            names[:] = sorted(name for name in names if name not in SKIP_DIRECTORIES)
            for name in sorted(files):
                source = Path(directory) / name
                if source.suffix not in {'.pyc', '.pyo'} and name not in {'sitecustomize.py', 'usercustomize.py'}:
                    archive.write(source, source.relative_to(library).as_posix())


def copy_distribution_metadata(name, destination):
    distribution = importlib.metadata.distribution(name)
    for entry in distribution.files or []:
        if not entry.parts[0].endswith('.dist-info') or entry.name == 'direct_url.json':
            continue
        target = destination / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(distribution.locate_file(entry), target)


def copy_licenses(bundle):
    licenses = bundle / 'licenses'
    licenses.mkdir(exist_ok=True)
    shutil.copy2(Path(sys.base_prefix) / 'LICENSE.txt', licenses / 'Python-LICENSE.txt')
    shutil.copy2(ROOT / 'LICENSE', licenses / 'WBot-LICENSE.txt')
    copy_tree(ROOT / 'licenses' / 'qt', licenses / 'Qt')
    copy_tree(ROOT / 'licenses' / 'pyside6-fluent-ui', licenses / 'pyside6-fluent-ui')
    for name in ('PySide6-Essentials', 'shiboken6', 'lxml', 'PyInstaller'):
        distribution = importlib.metadata.distribution(name)
        for entry in distribution.files or []:
            if not any(word in str(entry).lower() for word in ('license', 'copying')):
                continue
            source = Path(distribution.locate_file(entry))
            if source.is_file():
                target = licenses / name / entry
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)


def copy_runtime(bundle):
    base = Path(sys.base_prefix)
    python = bundle / 'python'
    python.mkdir()
    for pattern in ('python.exe', 'pythonw.exe', 'python3.dll', 'python3*.dll', 'vcruntime*.dll', 'LICENSE.txt'):
        for source in base.glob(pattern):
            shutil.copy2(source, python / source.name)
    extensions = python / 'DLLs'
    extensions.mkdir()
    for source in (base / 'DLLs').iterdir():
        if source.suffix.lower() in {'.pyd', '.dll'} and source.stem != '_tkinter':
            shutil.copy2(source, extensions / source.name)
    version = f'python{sys.version_info.major}{sys.version_info.minor}'
    copy_stdlib(base, python / f'{version}.zip')
    site_packages = python / 'Lib' / 'site-packages'
    site_packages.mkdir(parents=True)
    # ensurepip 需按原 wheel 文件名安装；保留目录可避免 zip 资源的临时文件前缀。
    copy_tree(base / 'Lib' / 'ensurepip', python / 'Lib' / 'ensurepip')
    lxml = Path(importlib.util.find_spec('lxml').origin).parent
    copy_tree(lxml, site_packages / 'lxml')
    copy_distribution_metadata('lxml', site_packages)
    source_root = bundle / 'runtime'
    app = source_root / 'app'
    assistant = app / 'assistant'
    assistant.mkdir(parents=True)
    for name in ('__init__.py', 'automation_package.py', 'assistant_release.py', 'processes.py'):
        shutil.copy2(ROOT / 'app' / name, app / name)
    for source in (ROOT / 'app' / 'assistant').glob('*.py'):
        if not source.name.startswith('qt_'):
            shutil.copy2(source, assistant / source.name)
    (assistant / 'web').mkdir()
    for name in ('index.html', 'assistant.js', 'assistant.css'):
        shutil.copy2(ROOT / 'app' / 'assistant' / 'web' / name, assistant / 'web' / name)
    for source in (ROOT / 'wbot').rglob('*.py'):
        target = source_root / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    from wbot import __version__ as wbot_version
    metadata = site_packages / f'wbot-{wbot_version}.dist-info'
    metadata.mkdir()
    (metadata / 'METADATA').write_text(
        f'Metadata-Version: 2.1\nName: wbot\nVersion: {wbot_version}\nRequires-Dist: lxml>=5.0\n', encoding='utf-8')
    # ._pth 固定搜索范围，禁止继承开发机 PYTHONPATH 和用户 site-packages。
    (python / f'{version}._pth').write_text(
        f'{version}.zip\nDLLs\nLib\nLib/site-packages\n../runtime\nimport site\n', encoding='utf-8')
    return python / 'python.exe'


def stop_verified_service(state):
    """停止本次验证的服务，并等进程释放日志句柄后再删除临时目录。"""
    import ctypes
    from ctypes import wintypes
    from app.assistant.lifecycle import _read_metadata, stop_service

    metadata = _read_metadata(state)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    process = kernel.OpenProcess(0x00100000, False, metadata['pid']) if metadata else None
    if metadata and not process and ctypes.get_last_error() != 87:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        stop_service(state)
        if process:
            result = kernel.WaitForSingleObject(process, 5000)
            if result == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            if result != 0:
                raise RuntimeError('验证服务已关闭接口，但进程未按时退出')
    finally:
        if process:
            kernel.CloseHandle(process)


def verify_runtime(bundle):
    interpreter = bundle / 'python' / 'python.exe'
    source_root = bundle / 'runtime'
    probe = '''import importlib.metadata as m, json, pathlib, site, ssl, sqlite3, sys, lxml, wbot
from wbot import element_versions
from wbot.elements import normalize_element
root = pathlib.Path(sys.executable).resolve().parent.parent
assert pathlib.Path(sys.base_prefix).resolve() == root / 'python'
assert pathlib.Path(lxml.__file__).resolve().is_relative_to(root)
assert pathlib.Path(wbot.__file__).resolve().is_relative_to(root)
assert pathlib.Path(element_versions.__file__).resolve().is_relative_to(root)
element = normalize_element({'id': 'portable-check', 'name': 'portable-check', 'xpath': '//button'})
assert element_versions.canonical_items([element])[0]['id'] == 'portable-check'
assert site.ENABLE_USER_SITE is False
assert all(pathlib.Path(path).resolve().is_relative_to(root) for path in sys.path)
print(json.dumps({'python':sys.version.split()[0], 'wbot':m.version('wbot'), 'lxml':m.version('lxml')}))
'''
    result = run([str(interpreter), '-I', '-X', 'utf8', '-c', probe], cwd=source_root,
                 capture_output=True, text=True, encoding='utf-8', timeout=20)
    print('内置运行环境：' + result.stdout.strip())
    run([str(interpreter), '-I', '-X', 'utf8', '-m', 'ensurepip', '--version'], cwd=source_root,
        capture_output=True, text=True, encoding='utf-8', timeout=20)
    with tempfile.TemporaryDirectory(prefix='assistant-bundle-check-') as temporary:
        state = Path(temporary) / 'state'
        command = [str(interpreter), '-m', 'app.assistant']
        try:
            run([*command, 'start', '--state-dir', str(state), '--port', '0'], cwd=source_root,
                capture_output=True, text=True, encoding='utf-8', timeout=25)
            # 由便携运行环境自己构建、导入并执行，校验冻结界面之外的真实任务路径。
            check = '''import importlib.metadata, json, pathlib, tempfile, time, sys
from app.automation_package import create_project, build_package
from app.assistant.lifecycle import _read_metadata, _request
state = pathlib.Path(sys.argv[1]); metadata = _read_metadata(state)
with tempfile.TemporaryDirectory() as directory:
    project = pathlib.Path(directory) / 'demo'
    manifest = create_project(project, 'portable-check')
    manifest['requirements'] = {name: importlib.metadata.version(name) for name in ('wbot', 'lxml')}
    (project / 'wbot.json').write_text(json.dumps(manifest), encoding='utf-8')
    (project / 'main.py').write_text('from wbot import runtime\\nprint("portable-ok")\\nruntime.set_result({"portable": True})\\n', encoding='utf-8')
    archive = build_package(project)
    package = _request(metadata, '/api/packages', {'path':str(archive)})['package']
    job = _request(metadata, '/api/jobs', {'package_id':package['id'], 'parameters':{}, 'request_id':'portable-check'})['job']
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        job=_request(metadata, '/api/jobs/'+job['id'])['job']
        if job['state'] in ('succeeded','failed','stopped'): break
        time.sleep(.1)
    assert job['state']=='succeeded', job
    assert job['result']=={'portable':True}, job
    assert 'portable-ok' in _request(metadata, '/api/jobs/'+job['id']+'/log')['log']
    print('便携包真实作业执行通过')
'''
            result = run([str(interpreter), '-I', '-X', 'utf8', '-c', check, str(state)], cwd=Path(temporary),
                         capture_output=True, text=True, encoding='utf-8', timeout=25)
            print(result.stdout.strip())
        finally:
            stop_verified_service(state)


def write_manifest(bundle):
    records = {}
    for source in sorted(bundle.rglob('*')):
        if source.is_file() and source != bundle / 'checksums.sha256.json':
            records[source.relative_to(bundle).as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
    (bundle / 'checksums.sha256.json').write_text(json.dumps(records, indent=2), encoding='utf-8')


def verify_remote_connection(bundle):
    """用随包后台完成真实 OC 绑定、发布包下载与执行结果回报。"""
    from app.automation_package import build_package, create_project
    from app.assistant.lifecycle import _read_metadata, _request
    from app.oc.agent_server import create_agent_server
    from app.oc.service import OcService

    with tempfile.TemporaryDirectory(prefix='assistant-remote-check-') as temporary:
        root = Path(temporary)
        state = root / 'assistant'
        service = OcService(root / 'oc')
        gateway = create_agent_server(service, port=0)
        thread = threading.Thread(target=gateway.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
        thread.start()
        command = [str(bundle / 'python' / 'python.exe'), '-m', 'app.assistant']
        try:
            run([*command, 'start', '--state-dir', str(state), '--port', '0'], cwd=bundle / 'runtime',
                capture_output=True, text=True, encoding='utf-8', timeout=25)
            metadata = _read_metadata(state)
            settings = _request(metadata, '/api/settings')['settings']
            if settings['binding_state'] != 'unconfigured' or 'secret' in settings:
                raise RuntimeError('便携后台设置接口未处于初始状态或暴露设备凭据')
            settings = _request(metadata, '/api/settings/connect', {
                'server_url': gateway.origin, 'device_name': '便携包远程验证'})['settings']
            deadline = time.monotonic() + 15
            device = None
            while time.monotonic() < deadline:
                device = next((item for item in service.snapshot()['devices'] if item['id'] == settings['device_id']), None)
                if device:
                    break
                time.sleep(0.1)
            if device is None or device['binding_state'] != 'pending':
                raise RuntimeError('便携后台未能在 OC 创建待审批绑定')
            service.agents.decide(device['id'], 'approve')
            while time.monotonic() < deadline:
                device = next(item for item in service.snapshot()['devices'] if item['id'] == device['id'])
                if device['status'] == 'online':
                    break
                time.sleep(0.1)
            if device['status'] != 'online':
                raise RuntimeError('批准后便携设备未上线')
            project = root / 'project'
            create_project(project, 'portable-remote-check')
            (project / 'main.py').write_text(
                'import sys\nimport wbot\nfrom wbot import runtime\nprint("portable-remote-ok")\n'
                'runtime.set_result({"portable_remote": True, "python": sys.executable, "wbot": wbot.__file__})\n',
                encoding='utf-8')
            package = service.import_package(build_package(project))
            process = service.create_process({'name': '便携远程执行', 'device_id': device['id'],
                                              'package_id': package['id']})
            job = service.run_process(process['id'], {}, 'portable-remote-check')
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                job = service.get_job(job['id'])
                if job['state'] in {'succeeded', 'failed', 'stopped', 'interrupted'}:
                    break
                time.sleep(0.1)
            if job['state'] != 'succeeded' or not job['result'].get('portable_remote'):
                raise RuntimeError(f'便携远程任务未成功：{job["state"]} {job["error"]}')
            if any(not Path(job['result'][key]).resolve().is_relative_to(bundle.resolve())
                   for key in ('python', 'wbot')):
                raise RuntimeError('远程任务未使用随包 Python 和 wbot')
            if 'portable-remote-ok' not in service.read_log(job['id'])['log']:
                raise RuntimeError('远程任务未回报日志')
            print('便携后台设置、OC 绑定审批、下载执行与结果日志回报通过')
        finally:
            try:
                stop_verified_service(state)
            finally:
                gateway.shutdown()
                gateway.server_close()
                thread.join(timeout=5)


def verify_desktop(bundle):
    """无可见窗口地验证冻结 Qt 与它实际启动的独立后端。"""
    from app.automation_package import build_package, create_project
    from app.assistant.lifecycle import _read_metadata, _request, service_status

    with tempfile.TemporaryDirectory(prefix='assistant-desktop-check-') as temporary:
        state = Path(temporary) / 'state'
        environment = os.environ.copy()
        windows = Path(os.environ['SYSTEMROOT'])
        environment.update(QT_QPA_PLATFORM='offscreen',
                           PYTHONHOME=str(Path(temporary) / 'no-host-python'),
                           PYTHONPATH=str(Path(temporary) / 'no-host-modules'),
                           PATH=os.pathsep.join((str(windows / 'System32'), str(windows))))
        command = [str(bundle / 'WBotAssistant.exe'), 'open', '--state-dir', str(state), '--port', '0']
        child = subprocess.Popen(command, cwd=temporary, env=environment,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not (state / '.desktop.lock').exists():
                if child.poll() is not None:
                    raise RuntimeError(f'冻结 Qt 界面启动失败，退出码：{child.returncode}')
                time.sleep(0.1)
            if not (state / '.desktop.lock').exists() or not service_status(state)['running']:
                raise RuntimeError('冻结 Qt 界面未能完成启动，请检查 Qt DLL 与便携运行目录')
            settings = _request(_read_metadata(state), '/api/settings')['settings']
            if settings['binding_state'] != 'unconfigured' or 'secret' in settings:
                raise RuntimeError('冻结界面启动的后台设置接口无效')
            shared = _request(_read_metadata(state), '/api/shared-elements/status', {
                'library_path': str(Path(temporary) / '元素工作副本.sqlite3')})
            if 'binding' not in shared or shared['binding'] is not None or shared.get('dirty') is not False:
                raise RuntimeError('冻结界面启动的后台共享元素接口未返回干净的未绑定工作副本')
            run(command, cwd=temporary, env=environment, timeout=10,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if child.poll() is not None:
                raise RuntimeError('主界面在第二实例唤起时意外退出')
            project = Path(temporary) / 'continue-after-ui'
            create_project(project, 'continue-after-ui')
            (project / 'main.py').write_text(
                'import time\nfrom wbot import runtime\ntime.sleep(2)\n'
                'print("continued-after-ui")\nruntime.set_result({"continued": True})\n', encoding='utf-8')
            metadata = _read_metadata(state)
            package = _request(metadata, '/api/packages', {'path': str(build_package(project))})['package']
            job = _request(metadata, '/api/jobs', {
                'package_id': package['id'], 'parameters': {}, 'request_id': 'continue-after-ui'})['job']
            deadline = time.monotonic() + 10
            while job['state'] == 'preparing' and time.monotonic() < deadline:
                time.sleep(0.05)
                job = _request(metadata, '/api/jobs/' + job['id'])['job']
            if job['state'] != 'running':
                raise RuntimeError(f'冻结界面创建的后台未能运行任务：{job["state"]}')
            child.terminate()
            child.wait(timeout=10)
            while job['state'] == 'running' and time.monotonic() < deadline:
                time.sleep(0.1)
                job = _request(metadata, '/api/jobs/' + job['id'])['job']
            if job['state'] != 'succeeded' or job['result'] != {'continued': True}:
                raise RuntimeError('退出冻结界面后，后台任务未能独立完成')
            if 'continued-after-ui' not in _request(metadata, '/api/jobs/' + job['id'] + '/log')['log']:
                raise RuntimeError('冻结界面退出后未取得任务日志')
            print('冻结 Qt 启动、共享元素状态、单实例唤起与界面退出后任务继续执行通过')
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
            stop_verified_service(state)


def remove_generated_bytecode(bundle):
    root = bundle.resolve()
    for cache in bundle.rglob('__pycache__'):
        if not cache.is_symlink() and cache.resolve().is_relative_to(root):
            shutil.rmtree(cache)


def create_desktop_icon(path, environment):
    script = '''import sys
from PySide6.QtWidgets import QApplication
from app.assistant.qt_theme import make_app_icon
application = QApplication([])
if not make_app_icon().pixmap(256, 256).save(sys.argv[1], 'ICO'):
    raise SystemExit('无法生成 Assistant 桌面图标')
'''
    run([sys.executable, '-X', 'utf8', '-c', script, str(path)], cwd=ROOT,
        env=dict(environment, QT_QPA_PLATFORM='offscreen'), timeout=20)
    return path


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='构建 Qt Assistant Windows 便携目录')
    parser.add_argument('--distpath', type=Path, default=ROOT / 'dist')
    parser.add_argument('--verify-only', action='store_true', help='只验证已有便携包的 Qt、Python 与真实执行链路')
    parser.add_argument('--release-notes', type=Path, help='UTF-8 更新说明文本（最多 8000 字）')
    args = parser.parse_args(argv)
    if sysconfig.get_platform() != 'win-amd64':
        parser.error('此构建脚本当前只支持 Windows x64 Python')
    destination = args.distpath.resolve()
    bundle = destination / 'WBotAssistant'
    if args.verify_only:
        verify_runtime(bundle)
        verify_desktop(bundle)
        verify_remote_connection(bundle)
        return 0
    for module in ('PySide6', 'PyInstaller', 'lxml'):
        if importlib.util.find_spec(module) is None:
            parser.error(f'缺少 {module}；请安装 requirements-assistant.txt 和 PyInstaller')
    work = ROOT / 'build' / 'assistant-pyinstaller'
    work.mkdir(parents=True, exist_ok=True)
    # 仅在构建子进程中清理搜索路径，避免把其他桌面工具的同名 ICU DLL 打进 Qt 包。
    environment = os.environ.copy()
    windows = Path(os.environ['SYSTEMROOT'])
    environment['PATH'] = os.pathsep.join(str(path) for path in (
        Path(sys.executable).parent, Path(sys.base_prefix), Path(sys.base_prefix) / 'DLLs',
        windows / 'System32', windows))
    icon = create_desktop_icon(work / 'assistant.ico', environment)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
               '--name', 'WBotAssistant', '--distpath', str(destination), '--workpath', str(work / 'work'),
               '--specpath', str(work), '--exclude-module', 'webview', '--exclude-module', 'playwright',
               '--exclude-module', 'openpyxl', '--exclude-module', 'app.oc',
               '--exclude-module', 'app.assistant.execution', '--exclude-module', 'app.assistant.server',
               '--icon', str(icon), str(ROOT / 'launch_assistant.py')]
    run(command, cwd=ROOT, env=environment)
    copy_runtime(bundle)
    copy_licenses(bundle)
    verify_runtime(bundle)
    verify_desktop(bundle)
    verify_remote_connection(bundle)
    remove_generated_bytecode(bundle)
    from app.assistant.version import VERSION
    from app.assistant_release import release_metadata, RELEASE_FILE, PLATFORM
    notes = args.release_notes.read_text(encoding='utf-8') if args.release_notes else 'Assistant 界面、执行与在线更新功能改进。'
    release = release_metadata(dict(schema=1, product='wbot-assistant', platform=PLATFORM, version=VERSION, notes=notes))
    (bundle / RELEASE_FILE).write_text(json.dumps(release, ensure_ascii=False), encoding='utf-8')
    write_manifest(bundle)
    archive = destination / 'WBotAssistant-windows-x64.zip'
    # 直接继承输出目录 ACL；Windows 的私有临时目录会把 ZIP 的读取权限一并带走。
    temporary_archive = destination / f'.WBotAssistant-{uuid4().hex}.zip'
    try:
        prepared = shutil.make_archive(str(temporary_archive.with_suffix('')),
                                       'zip', root_dir=destination, base_dir='WBotAssistant')
        Path(prepared).replace(archive)
    finally:
        temporary_archive.unlink(missing_ok=True)
    print(json.dumps({'directory': str(bundle), 'executable': str(bundle / 'WBotAssistant.exe'),
                      'archive': str(archive)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
