"""Portable Assistant release format, shared by OC and the updater."""
import hashlib
import json
from pathlib import Path
import re
import stat
import zipfile

MAX_RELEASE_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
RELEASE_FILE = 'assistant-release.json'
CHECKSUM_FILE = 'checksums.sha256.json'
PLATFORM = 'windows-x64'
ARCHIVE_NAME = 'WBotAssistant-windows-x64.zip'
UPDATE_FILE = 'assistant-update.json'


def version_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})', value):
        raise ValueError('版本须为三个非负整数，例如 0.7.0')
    return tuple(int(part) for part in value.split('.'))


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def release_metadata(value):
    if (not isinstance(value, dict) or value.get('schema') != 1
            or value.get('product') != 'wbot-assistant' or value.get('platform') != PLATFORM):
        raise ValueError('不是兼容的 Windows x64 Assistant 更新包')
    version_key(value.get('version'))
    if not isinstance(value.get('notes'), str) or len(value['notes']) > 8000:
        raise ValueError('更新说明须为不超过 8000 字的文本')
    return {key: value[key] for key in ('schema', 'product', 'platform', 'version', 'notes')}


def update_metadata(value):
    metadata = release_metadata(value)
    if (type(value.get('size')) is not int or not 0 < value['size'] <= MAX_RELEASE_BYTES
            or not isinstance(value.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', value['sha256'])):
        raise ValueError('更新包大小或 SHA-256 校验值无效')
    return dict(metadata, size=value['size'], sha256=value['sha256'])


def _relative_name(name):
    if not name.startswith('WBotAssistant/'):
        raise ValueError('更新包必须包含 WBotAssistant 顶层目录')
    relative = name.removeprefix('WBotAssistant/').removesuffix('/')
    for part in relative.split('/'):
        if (not part or part in ('.', '..') or part.rstrip(' .') != part
                or any(ord(char) < 32 or char in '\\:<>"|?*' for char in part)
                or part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                    *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}):
            raise ValueError('更新包包含不安全的文件路径')
    return relative


def inspect_release(source, destination=None):
    source = Path(source)
    if not 0 < source.stat().st_size <= MAX_RELEASE_BYTES:
        raise ValueError('更新包为空或超过 128 MiB')
    try:
        with zipfile.ZipFile(source) as archive:
            files = {}
            names = set()
            expanded = 0
            for info in archive.infolist():
                if info.filename == 'WBotAssistant/':
                    continue
                name = _relative_name(info.filename)
                if name.casefold() in names or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                    raise ValueError('更新包包含重名、链接或加密文件')
                names.add(name.casefold())
                expanded += info.file_size
                if expanded > MAX_EXPANDED_BYTES or len(names) > 5000:
                    raise ValueError('更新包解压内容超过限制')
                if not info.is_dir():
                    files[name] = info
            required = {RELEASE_FILE, CHECKSUM_FILE, 'WBotAssistant.exe', 'python/python.exe',
                        'runtime/app/assistant/__main__.py'}
            if not required <= files.keys():
                raise ValueError('更新包缺少启动程序、运行环境或版本清单')
            if files[CHECKSUM_FILE].file_size > 1024 * 1024 or files[RELEASE_FILE].file_size > 65536:
                raise ValueError('更新清单超过大小限制')
            checksums = json.loads(archive.read(files[CHECKSUM_FILE]))
            metadata = release_metadata(json.loads(archive.read(files[RELEASE_FILE])))
            if not isinstance(checksums, dict) or checksums.keys() != files.keys() - {CHECKSUM_FILE}:
                raise ValueError('更新包文件与校验清单不一致')
            target = Path(destination) / 'WBotAssistant' if destination is not None else None
            if target is not None:
                target.mkdir(parents=True, exist_ok=False)
            for name, info in files.items():
                digest = hashlib.sha256()
                output = None
                try:
                    if target is not None:
                        path = target / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        output = path.open('xb')
                    with archive.open(info) as stream:
                        while chunk := stream.read(1024 * 1024):
                            digest.update(chunk)
                            if output is not None:
                                output.write(chunk)
                    if name != CHECKSUM_FILE and digest.hexdigest() != checksums[name]:
                        raise ValueError(f'更新包校验失败：{name}')
                finally:
                    if output is not None:
                        output.close()
            return metadata
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('更新包损坏或清单格式无效') from exc


def verify_prepared(directory, archive_path):
    directory = Path(directory)
    with zipfile.ZipFile(archive_path) as archive:
        expected = archive.read('WBotAssistant/' + CHECKSUM_FILE)
    if (directory / CHECKSUM_FILE).read_bytes() != expected:
        raise ValueError('待安装校验清单已变化，请重新下载更新')
    checksums = json.loads(expected)
    actual = set()
    for path in directory.rglob('*'):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('待安装目录包含文件系统链接')
        if path.is_file():
            name = path.relative_to(directory).as_posix()
            actual.add(name)
            if name != CHECKSUM_FILE and file_digest(path) != checksums.get(name):
                raise ValueError('待安装文件已变化，请重新下载更新')
    if actual != checksums.keys() | {CHECKSUM_FILE}:
        raise ValueError('待安装文件清单不一致，请重新下载更新')
