"""Streaming verification and extraction of flow-owned Python distributions.

This module never creates an environment, installs dependencies, or runs code.
"""
from contextlib import nullcontext
import hashlib
from pathlib import Path
import re
import stat
import tempfile
import zipfile

from app.automation_package import (MANIFEST, CHECKSUMS, MAX_ARCHIVE_BYTES,
    _assert_no_links, _check_file_paths, _load_json, _portable_elements, validate_manifest)

MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_FILES = 20000
RUNTIME_DIRECTORY = '_runtime'


def validate_runtime(runtime):
    if (not isinstance(runtime, dict)
            or set(runtime) != {'kind', 'platform', 'python', 'executable'}
            or runtime['kind'] != 'bundled-python'
            or runtime['platform'] != 'win32-x64'
            or runtime['executable'] != '_runtime/python.exe'
            or not isinstance(runtime['python'], str)
            or not re.fullmatch(r'3\.\d+\.\d+', runtime['python'])):
        raise ValueError('runtime 必须声明 Windows x64 独立 Python、精确版本及 _runtime/python.exe')


def is_portable_package(path):
    path = Path(path)
    _assert_no_links(path)
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('归档文件大小超出上限（516 MiB）')
    try:
        with zipfile.ZipFile(path) as archive:
            member = archive.getinfo(MANIFEST)
            if member.file_size > MAX_METADATA_BYTES:
                raise ValueError('发布包清单过大')
            manifest = _load_json(archive.read(member), MANIFEST)
            return isinstance(manifest, dict) and manifest.get('schemaVersion') == 2
    except (zipfile.BadZipFile, KeyError):
        return False
    except (NotImplementedError, RuntimeError, EOFError) as error:
        raise ValueError(f'不是有效的自动化 ZIP 包：{error}') from error


def _verify(archive, destination):
    members = archive.infolist()
    if len(members) > MAX_FILES or sum(member.file_size for member in members) > MAX_EXPANDED_BYTES:
        raise ValueError('发布包解压总量超过 512 MiB 或文件数量超过 20000')
    _check_file_paths([member.filename for member in members])
    for member in members:
        mode = member.external_attr >> 16
        limit = MAX_METADATA_BYTES if member.filename in (MANIFEST, CHECKSUMS) else MAX_FILE_BYTES
        if (member.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                or member.flag_bits & 1 or member.file_size > limit):
            raise ValueError(f'发布包包含链接、特殊文件、加密文件或文件过大：{member.filename}')
    try:
        manifest = validate_manifest(_load_json(archive.read(MANIFEST), MANIFEST))
        hashes = _load_json(archive.read(CHECKSUMS), CHECKSUMS)
    except KeyError as error:
        raise ValueError('发布包缺少清单或 SHA256 索引') from error
    if manifest['schemaVersion'] != 2:
        raise ValueError('需要 schemaVersion=2 发布包')
    declared = {MANIFEST, *manifest['files']}
    if {member.filename for member in members} != declared | {CHECKSUMS}:
        raise ValueError('包包含未声明文件或缺少声明的文件')
    if not isinstance(hashes, dict) or set(hashes) != declared:
        raise ValueError('SHA256 完整性索引未覆盖所有声明的文件')
    for member in members:
        digest = hashlib.sha256()
        size = 0
        output = nullcontext(None)
        if destination is not None:
            target = destination / member.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            output = target.open('xb')
        with archive.open(member) as source, output as target:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > member.file_size:
                    raise ValueError(f'文件实际大小与声明不符：{member.filename}')
                digest.update(chunk)
                if target is not None:
                    target.write(chunk)
        if size != member.file_size:
            raise ValueError(f'文件实际大小与声明不符：{member.filename}')
        if member.filename != CHECKSUMS and digest.hexdigest() != hashes[member.filename]:
            raise ValueError(f'SHA256 完整性校验失败：{member.filename}')
    if manifest.get('elements'):
        member = archive.getinfo(manifest['elements'])
        if member.file_size > 16 * 1024 * 1024:
            raise ValueError('元素库文件超过 16 MiB')
        elements = archive.read(member)
        if _load_json(elements, '元素库') != _load_json(_portable_elements(elements), '元素库'):
            raise ValueError('发布包元素库不能包含临时浏览器身份')
    return manifest


def verify_portable_package(path, destination=None):
    path = Path(path).absolute()
    _assert_no_links(path)
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('归档文件大小超出上限（516 MiB）')
    target = Path(destination).absolute() if destination is not None else None
    if target is not None:
        _assert_no_links(target)
        if target.exists():
            raise FileExistsError(f'目标目录已存在：{target}')
        target.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix='.deploy-', dir=target.parent) if target else nullcontext(None)
    try:
        with temporary as staging, zipfile.ZipFile(path) as archive:
            prepared = Path(staging) / 'package' if staging else None
            manifest = _verify(archive, prepared)
            if target is not None:
                if target.exists():
                    raise FileExistsError(f'目标目录已存在：{target}')
                prepared.rename(target)
            return manifest
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError) as error:
        raise ValueError(f'不是有效的自动化 ZIP 包：{error}') from error
