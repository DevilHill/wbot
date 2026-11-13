"""Resolve and validate a flow-owned environment without creating or modifying it."""
import json
import os
from pathlib import Path
import platform
import subprocess


ENVIRONMENT_CHECK = '''import importlib.metadata as metadata, json, sys
requirements = json.load(sys.stdin)
errors = []
for name, expected in requirements.items():
    try:
        actual = metadata.version(name)
    except metadata.PackageNotFoundError:
        errors.append(name + '==' + expected + ': not installed')
        continue
    if actual != expected:
        errors.append(name + '==' + expected + ': installed ' + actual)
print(json.dumps({'prefix': sys.prefix, 'base': sys.base_prefix, 'version': list(sys.version_info[:3]), 'paths': sys.path, 'errors': errors}))
'''


def project_interpreter(project, requirements):
    project = Path(project)
    environment = project / '.venv'
    executable = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    for component in (environment, executable.parent, executable):
        if component.is_symlink() or getattr(component, 'is_junction', lambda: False)():
            raise ValueError('流程虚拟环境不能链接到外部目录，请使用独立环境（venv --copies）')
    configuration = environment / 'pyvenv.cfg'
    if not configuration.is_file() or not executable.is_file():
        raise ValueError('流程缺少可用的 .venv 虚拟环境，请在开发或部署阶段准备；Assistant 不会创建或安装环境')
    settings = dict(line.lower().split('=', 1) for line in configuration.read_text(encoding='utf-8').splitlines() if '=' in line)
    settings = {key.strip(): value.strip() for key, value in settings.items()}
    if settings.get('include-system-site-packages') != 'false':
        raise ValueError('流程虚拟环境必须隔离系统依赖：include-system-site-packages=false')
    try:
        result = subprocess.run([str(executable), '-I', '-B', '-X', 'utf8', '-c', ENVIRONMENT_CHECK],
            input=json.dumps(requirements), capture_output=True, text=True, encoding='utf-8',
            timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f'流程虚拟环境无法启动或检查超时：{error}') from error
    if result.returncode:
        raise ValueError(f'流程虚拟环境检查失败：{result.stderr.strip()}')
    observed = json.loads(result.stdout)
    if observed['version'] < [3, 10]:
        raise ValueError('流程虚拟环境需要 Python 3.10 或更新版本')
    if (Path(observed['prefix']).resolve() != environment.resolve()
            or Path(observed['prefix']).resolve() == Path(observed['base']).resolve()):
        raise ValueError('流程解释器没有使用本项目的独立虚拟环境')
    if observed['errors']:
        raise ValueError('流程虚拟环境的依赖不满足要求（不会自动安装）：' + '; '.join(observed['errors']))
    return executable


def bundled_interpreter(project, manifest):
    runtime = manifest['runtime']
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('此流程环境仅支持 Windows x64，请在匹配的平台部署')
    environment = Path(project).resolve() / '_runtime'
    executable = environment / 'python.exe'
    try:
        result = subprocess.run([str(executable), '-I', '-B', '-X', 'utf8', '-c', ENVIRONMENT_CHECK],
            input=json.dumps(manifest['requirements']), capture_output=True, text=True, encoding='utf-8',
            timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError('流程自带 Python 无法启动：' + result.stderr.strip())
        observed = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f'流程自带 Python 无法启动：{error}') from error
    if (Path(observed['prefix']).resolve() != environment
            or Path(observed['base']).resolve() != environment
            or '.'.join(map(str, observed['version'])) != runtime['python']
            or any(not Path(path).resolve().is_relative_to(environment) for path in observed['paths'])):
        raise ValueError('流程 Python 版本或隔离路径不符，不能依赖开发机环境')
    if observed['errors']:
        raise ValueError('流程发布包缺少依赖：' + '; '.join(observed['errors']))
    return executable
