"""Developer-side packaging of an existing Windows project environment."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import stat
import sys
import zipfile

from app.automation_package import (MANIFEST, CHECKSUMS, _assert_no_links,
    _check_file_paths, _json_bytes, _project_contents, validate_manifest)
from app.portable_package import (MAX_EXPANDED_BYTES, MAX_FILE_BYTES,
    MAX_METADATA_BYTES, MAX_FILES, MAX_ARCHIVE_BYTES)


def _tree_files(directory, prefix, excluded=()):
    for root, directories, files in os.walk(directory, followlinks=False):
        for name in directories:
            _assert_no_links(Path(root) / name)
        directories[:] = sorted(name for name in directories if name not in {'__pycache__', *excluded})
        for name in sorted(files):
            source = Path(root) / name
            if source.suffix in {'.pyc', '.pyo'}:
                continue
            _assert_no_links(source)
            if not source.is_file():
                raise ValueError(f'环境包含非常规文件：{source}')
            yield f'{prefix}/{source.relative_to(directory).as_posix()}', source


def _environment_files(project, requirements):
    environment = project / '.venv'
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64') or sys.maxsize <= 2**32:
        raise ValueError('跨电脑发布目前支持 Windows x64；请在目标平台构建环境')
    if Path(sys.prefix).resolve() != environment.resolve() or sys.prefix == sys.base_prefix:
        raise ValueError('请选择项目 .venv/Scripts/python.exe 构建发布包')
    configuration = (environment / 'pyvenv.cfg').read_text(encoding='utf-8')
    settings = dict(line.lower().split('=', 1) for line in configuration.splitlines() if '=' in line)
    if {key.strip(): value.strip() for key, value in settings.items()}.get('include-system-site-packages') != 'false':
        raise ValueError('项目环境必须隔离系统 site-packages')
    site = environment / 'Lib' / 'site-packages'
    installed = {}
    for distribution in importlib.metadata.distributions(path=[str(site)]):
        name = distribution.metadata['Name']
        if not name:
            raise ValueError('环境包含缺少名称的依赖元数据')
        direct = distribution.read_text('direct_url.json')
        if direct and json.loads(direct).get('dir_info', {}).get('editable'):
            raise ValueError(f'{name} 使用 editable 安装；请先在开发端安装普通 wheel')
        installed[name] = distribution.version
    normalize = lambda name: name.lower().replace('_', '-').replace('.', '-')
    versions = {normalize(name): version for name, version in installed.items()}
    for name, version in requirements.items():
        if versions.get(normalize(name)) != version:
            raise ValueError(f'项目环境不满足 {name}=={version}；请先在开发端准备依赖')
    for source in site.glob('*.pth'):
        for line in source.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith(('import ', 'import\t')):
                if source.name == 'distutils-precedence.pth':
                    continue
                raise ValueError(f'环境包含不可移植的 .pth 启动代码：{source.name}；请使用普通 wheel')
            candidate = Path(line)
            if candidate.is_absolute() or not (site / candidate).resolve().is_relative_to(site.resolve()):
                raise ValueError(f'环境 .pth 引用了外部路径：{source.name}')
    if list(site.glob('*.egg-link')):
        raise ValueError('环境包含 .egg-link，请先在开发端改为普通 wheel 安装')
    base = Path(sys.base_prefix).resolve()
    files = {}
    for pattern in ('python.exe', 'python3*.dll', 'vcruntime*.dll', 'LICENSE.txt'):
        for source in base.glob(pattern):
            files[f'_runtime/{source.name}'] = source
    files.update(_tree_files(base / 'Lib', '_runtime/Lib', {'site-packages', 'test', 'tests', 'idlelib'}))
    files.update(_tree_files(base / 'DLLs', '_runtime/DLLs'))
    if (base / 'tcl').is_dir():
        files.update(_tree_files(base / 'tcl', '_runtime/tcl'))
    files.update(_tree_files(site, '_runtime/Lib/site-packages'))
    version = f'python{sys.version_info.major}{sys.version_info.minor}'
    files[f'_runtime/{version}._pth'] = b'Lib\nDLLs\nLib/site-packages\nimport site\n'
    if '_runtime/python.exe' not in files or f'_runtime/{version}.dll' not in files:
        raise ValueError('基础 Python 缺少可独立分发的解释器或 DLL')
    return files, {name: version for name, version in installed.items()
                   if normalize(name) not in {'pip', 'setuptools', 'wheel'}}


def build_portable_package(project, output=None):
    project = Path(project).absolute()
    manifest, contents = _project_contents(project)
    if manifest['schemaVersion'] != 1 or any(name.split('/')[0].casefold() == '_runtime' for name in manifest['files']):
        raise ValueError('请从 schemaVersion=1 开发项目构建；_runtime 是发布包保留目录')
    environment, requirements = _environment_files(project, manifest['requirements'])
    contents.update(environment)
    manifest = dict(manifest, schemaVersion=2, requirements=requirements,
        runtime={'kind': 'bundled-python', 'platform': 'win32-x64',
                 'python': platform.python_version(), 'executable': '_runtime/python.exe'},
        files=sorted(name for name in contents if name != MANIFEST))
    validate_manifest(manifest)
    contents[MANIFEST] = _json_bytes(manifest)
    output = Path(output or project / 'dist' / f'{manifest["name"]}-{manifest["version"]}.wbot.zip').absolute()
    _assert_no_links(output)
    _check_file_paths([*contents, CHECKSUMS])
    if len(contents) + 1 > MAX_FILES:
        raise ValueError('发布包文件数量超过 20000')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        try:
            hashes, total = {}, 0
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for name, source in sorted(contents.items()):
                    size = len(source) if isinstance(source, bytes) else source.stat().st_size
                    total += size
                    if size > MAX_FILE_BYTES or total > MAX_EXPANDED_BYTES:
                        raise ValueError('发布包超过大小限制（单文件 128 MiB，总量 512 MiB）')
                    member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    member.create_system = 3
                    member.external_attr = (stat.S_IFREG | 0o644) << 16
                    member.compress_type = zipfile.ZIP_DEFLATED
                    digest = hashlib.sha256()
                    with archive.open(member, 'w', force_zip64=True) as target:
                        if isinstance(source, bytes):
                            target.write(source)
                            digest.update(source)
                        else:
                            _assert_no_links(source)
                            observed = 0
                            with source.open('rb') as input_file:
                                while chunk := input_file.read(1024 * 1024):
                                    observed += len(chunk)
                                    if observed > size:
                                        raise ValueError(f'构建期间环境文件发生变化：{source}')
                                    target.write(chunk)
                                    digest.update(chunk)
                            if observed != size:
                                raise ValueError(f'构建期间环境文件发生变化：{source}')
                    hashes[name] = digest.hexdigest()
                checksum = _json_bytes(hashes)
                if max(len(checksum), len(contents[MANIFEST])) > MAX_METADATA_BYTES or total + len(checksum) > MAX_EXPANDED_BYTES:
                    raise ValueError('发布包元数据或总量超过上限')
                member = zipfile.ZipInfo(CHECKSUMS, date_time=(1980, 1, 1, 0, 0, 0))
                member.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(member, checksum, compress_type=zipfile.ZIP_DEFLATED)
            if stream.tell() > MAX_ARCHIVE_BYTES:
                raise ValueError('归档文件超过 516 MiB')
        except BaseException:
            stream.close()
            output.unlink()
            raise
    return output
