"""Portable, versioned Python automation packages and their manifest contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
import zipfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wbot.elements import _record as validate_element_record
from wbot.xzip import _member_path


MANIFEST = 'wbot.json'
CHECKSUMS = 'checksums.sha256.json'
MAX_FILES = 1000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_METADATA_BYTES = 256 * 1024
MANIFEST_FIELDS = {'schemaVersion', 'name', 'version', 'entry', 'files',
                   'parameters', 'requirements', 'elements'}
PARAMETER_FIELDS = {'type', 'required', 'default', 'description', 'title'}
TRANSIENT_ELEMENT_FIELDS = {'browserId', 'tabId', 'frameId', 'documentId', 'parentFrameId', 'lastPickAt'}
PACKAGE_VERSION = r'(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?(?:\+[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?'
DEPENDENCY_VERSION = r'\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?(?:\+[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*)?'


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'JSON 字段重复：{key}')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f'JSON 不支持非有限数值：{value}')


def _load_json(content, label):
    try:
        return json.loads(content.decode('utf-8-sig'), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError(f'{label} 不是有效 JSON：{error}') from error


def _check_fields(value, allowed, required, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} 必须是对象')
    if set(value) - allowed:
        raise ValueError(f'{label} 包含不支持的字段：{sorted(set(value) - allowed)}')
    if required - set(value):
        raise ValueError(f'{label} 缺少字段：{sorted(required - set(value))}')


def _relative_path(value):
    if (not isinstance(value, str) or not value or len(value) > 240 or '\\' in value
            or any(part in ('', '.', '..') for part in value.split('/'))
            or any(ord(char) < 32 or char in '<>"|?*' for char in value)):
        raise ValueError(f'需要规范且安全的项目相对路径：{value!r}')
    return _member_path(value)


def _path_key(value):
    return unicodedata.normalize('NFC', value).casefold()


def _check_file_paths(names):
    keys = set()
    for name in names:
        _relative_path(name)
        key = _path_key(name)
        if key in keys:
            raise ValueError(f'包文件路径重复（不区分大小写）：{name}')
        keys.add(key)
    for name in names:
        ancestors = Path(name).parents
        if any(_path_key(parent.as_posix()) in keys for parent in ancestors):
            raise ValueError(f'包文件与目录冲突：{name}')


def _validate_value(name, definition, value):
    kind = definition['type']
    valid = {'string': isinstance(value, str), 'integer': type(value) is int,
             'boolean': type(value) is bool,
             'number': type(value) in (int, float) and (type(value) is int or math.isfinite(value))}
    if not valid[kind]:
        raise ValueError(f'参数 {name} 必须为 {kind} 类型的有效值')


def _validate_parameters(parameters):
    if not isinstance(parameters, dict) or len(parameters) > 100:
        raise ValueError('parameters 必须是最多包含 100 个参数的对象')
    for name, definition in parameters.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', name):
            raise ValueError(f'参数名称无效：{name!r}')
        _check_fields(definition, PARAMETER_FIELDS, {'type'}, f'参数 {name}')
        if definition['type'] not in ('string', 'number', 'integer', 'boolean'):
            raise ValueError(f'参数 {name} 的类型不受支持')
        if 'required' in definition and type(definition['required']) is not bool:
            raise ValueError(f'参数 {name} 的 required 必须是布尔值')
        if 'description' in definition and not isinstance(definition['description'], str):
            raise ValueError(f'参数 {name} 的 description 必须是字符串')
        if 'title' in definition and (not isinstance(definition['title'], str) or not definition['title'].strip() or len(definition['title']) > 120):
            raise ValueError(f'参数 {name} 的 title 必须为 1–120 个字符')
        if 'default' in definition:
            _validate_value(name, definition, definition['default'])


def _validate_requirements(requirements):
    if not isinstance(requirements, dict) or len(requirements) > 100:
        raise ValueError('requirements 必须是包名称到精确版本的对象，最多 100 项')
    names = set()
    for name, version in requirements.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?', name):
            raise ValueError(f'依赖名称无效：{name!r}')
        normalized = re.sub(r'[-_.]+', '-', name).lower()
        if normalized in names:
            raise ValueError(f'依赖名称重复：{name}')
        names.add(normalized)
        if not isinstance(version, str) or not re.fullmatch(DEPENDENCY_VERSION, version):
            raise ValueError(f'依赖 {name} 必须指定精确版本，如 5.3.0')


def validate_manifest(manifest):
    """Validate the portable contract without reading files or changing input."""
    _check_fields(manifest, MANIFEST_FIELDS, MANIFEST_FIELDS - {'elements'}, MANIFEST)
    if type(manifest['schemaVersion']) is not int or manifest['schemaVersion'] != 1:
        raise ValueError('仅支持 schemaVersion=1')
    name, version = manifest['name'], manifest['version']
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', name):
        raise ValueError('name 必须以字母或数字开头，仅包含字母、数字、下划线和连字符，最多 80 字符')
    if not isinstance(version, str) or len(version) > 80 or not re.fullmatch(PACKAGE_VERSION, version):
        raise ValueError('version 必须是固定的语义版本，如 1.0.0')
    files = manifest['files']
    if not isinstance(files, list) or not files or len(files) + 2 > MAX_FILES:
        raise ValueError(f'files 必须是非空文件白名单，包总文件数不得超过 {MAX_FILES}')
    _check_file_paths([MANIFEST, CHECKSUMS, *files])
    entry = manifest['entry']
    _relative_path(entry)
    if not entry.endswith('.py') or entry not in files:
        raise ValueError('entry 必须是 files 中声明的 Python (.py) 文件')
    _validate_parameters(manifest['parameters'])
    _validate_requirements(manifest['requirements'])
    if 'elements' in manifest:
        elements = manifest['elements']
        _relative_path(elements)
        if not elements.endswith('.json') or elements not in files:
            raise ValueError('elements 必须是 files 中声明的 JSON 相对路径')
    return manifest


def resolve_parameters(manifest, values):
    """Apply defaults and reject unknown, missing required or mistyped inputs."""
    validate_manifest(manifest)
    definitions = manifest['parameters']
    if not isinstance(values, dict) or set(values) - set(definitions):
        raise ValueError('运行参数必须是对象，且不能包含未声明的参数')
    resolved = {}
    for name, definition in definitions.items():
        if name in values:
            value = values[name]
        elif 'default' in definition:
            value = definition['default']
        elif definition.get('required', False):
            raise ValueError(f'缺少必填参数：{name}')
        else:
            continue
        _validate_value(name, definition, value)
        resolved[name] = value
    return resolved


def _assert_no_links(path):
    for candidate in [path, *path.parents]:
        if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
            raise ValueError(f'路径不能包含符号链接或目录联接：{candidate}')


def _read_file(path, limit):
    _assert_no_links(path)
    if not path.is_file():
        raise ValueError(f'缺少普通文件：{path}')
    with path.open('rb') as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError(f'文件大小超过允许上限：{path.name}')
    return content


def _strip_transient_fields(value):
    if isinstance(value, dict):
        return {key: _strip_transient_fields(item) for key, item in value.items()
                if key not in TRANSIENT_ELEMENT_FIELDS}
    if isinstance(value, list):
        return [_strip_transient_fields(item) for item in value]
    return value


def _portable_elements(content):
    exported = _load_json(content, '元素库')
    _check_fields(exported, {'format', 'version', 'items'}, {'format', 'version', 'items'}, '元素库')
    if exported['format'] != 'wbot-elements' or type(exported['version']) is not int or exported['version'] != 1:
        raise ValueError('elements 需要 wbot-elements version=1 格式')
    if not isinstance(exported['items'], list) or len(exported['items']) > 10000:
        raise ValueError('元素库 items 必须是最多 10000 项的列表')
    identities, record_ids = set(), set()
    for record in exported['items']:
        validated = validate_element_record(record)
        identity = (validated['group'], validated['name'])
        if identity in identities or validated['id'] in record_ids:
            raise ValueError('元素库存在重复名称或 ID')
        identities.add(identity)
        record_ids.add(validated['id'])
    return _json_bytes(_strip_transient_fields(exported))


def _check_content_sizes(contents):
    if len(contents) > MAX_FILES or sum(map(len, contents.values())) > MAX_PACKAGE_BYTES:
        raise ValueError('自动化包文件数量或总大小超出上限')
    if any(len(content) > MAX_FILE_BYTES for content in contents.values()):
        raise ValueError('自动化包单个文件大小超出上限')
    if any(len(contents.get(name, b'')) > MAX_METADATA_BYTES for name in (MANIFEST, CHECKSUMS)):
        raise ValueError('自动化包元数据大小超出上限')


def _project_contents(project):
    project = Path(project).absolute()
    manifest = validate_manifest(_load_json(_read_file(project / MANIFEST, MAX_METADATA_BYTES), MANIFEST))
    contents = {MANIFEST: _json_bytes(manifest)}
    total = len(contents[MANIFEST])
    for name in manifest['files']:
        content = _read_file(project / _relative_path(name), min(MAX_FILE_BYTES, MAX_PACKAGE_BYTES - total))
        if name == manifest.get('elements'):
            content = _portable_elements(content)
        contents[name] = content
        total += len(content)
        if total > MAX_PACKAGE_BYTES:
            raise ValueError('自动化包总大小超出上限')
    _check_content_sizes(contents)
    return manifest, contents


def _write_new_directory(destination, contents):
    destination = Path(destination).absolute()
    _assert_no_links(destination)
    if destination.exists():
        raise FileExistsError(f'目标目录已存在：{destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.wbot-package-', dir=destination.parent))
    try:
        for name, content in contents.items():
            target = staging / _relative_path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(content)
        if destination.exists():
            raise FileExistsError(f'目标目录已存在：{destination}')
        staging.rename(destination)
    finally:
        if staging.exists() and staging.resolve().parent == destination.parent.resolve():
            shutil.rmtree(staging)


def create_project(directory, name=None):
    """Create an explicitly declared starter project in a new directory."""
    directory = Path(directory).absolute()
    manifest = {'schemaVersion': 1, 'name': name or directory.name, 'version': '0.1.0',
                'entry': 'main.py', 'files': ['main.py'], 'requirements': {},
                'parameters': {'name': {'type': 'string', 'default': 'WBot', 'description': '问候对象'}}}
    validate_manifest(manifest)
    script = ('from wbot import runtime\n\n'
              'parameters = runtime.parameters()\n'
              'message = f"你好，{parameters[\'name\']}"\n'
              'print(message)\n'
              'runtime.set_result({"message": message})\n')
    _write_new_directory(directory, {MANIFEST: _json_bytes(manifest), 'main.py': script.encode('utf-8')})
    return manifest


def build_package(project, output=None):
    """Build a deterministic archive without replacing an existing release."""
    manifest, contents = _project_contents(project)
    contents[CHECKSUMS] = _json_bytes({name: hashlib.sha256(content).hexdigest()
                                      for name, content in contents.items()})
    _check_content_sizes(contents)
    output = Path(output) if output is not None else Path(project) / 'dist' / f'{manifest["name"]}-{manifest["version"]}.wbot.zip'
    output = output.absolute()
    _assert_no_links(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        try:
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for name, content in sorted(contents.items()):
                    member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    member.create_system = 3
                    member.external_attr = (stat.S_IFREG | 0o644) << 16
                    archive.writestr(member, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        except BaseException:
            stream.close()
            output.unlink()
            raise
    return output


def _archive_contents(archive_path):
    archive_path = Path(archive_path).absolute()
    _assert_no_links(archive_path)
    if archive_path.stat().st_size > MAX_PACKAGE_BYTES + 4 * 1024 * 1024:
        raise ValueError('归档文件大小超出上限')
    contents = {}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES or sum(member.file_size for member in members) > MAX_PACKAGE_BYTES:
                raise ValueError('自动化包文件数量或总大小超出上限')
            _check_file_paths([member.filename for member in members])
            for member in members:
                mode = member.external_attr >> 16
                if member.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG) or member.flag_bits & 1:
                    raise ValueError(f'包中不支持目录、链接、特殊文件或加密内容：{member.filename}')
                limit = min(MAX_FILE_BYTES, MAX_METADATA_BYTES) if member.filename in (MANIFEST, CHECKSUMS) else MAX_FILE_BYTES
                if member.file_size > limit:
                    raise ValueError(f'包文件大小超出上限：{member.filename}')
                with archive.open(member) as stream:
                    content = stream.read(limit + 1)
                if len(content) != member.file_size:
                    raise ValueError(f'包文件实际大小与声明不符：{member.filename}')
                contents[member.filename] = content
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError) as error:
        raise ValueError(f'不是有效的自动化 ZIP 包：{error}') from error
    _check_content_sizes(contents)
    return contents


def _verified_package(archive):
    contents = _archive_contents(archive)
    if MANIFEST not in contents or CHECKSUMS not in contents:
        raise ValueError('自动化包缺少 wbot.json 或 SHA256 完整性索引')
    manifest = validate_manifest(_load_json(contents[MANIFEST], MANIFEST))
    declared = {MANIFEST, *manifest['files']}
    if set(contents) != declared | {CHECKSUMS}:
        raise ValueError('包包含未声明文件或缺少声明的文件')
    hashes = _load_json(contents[CHECKSUMS], CHECKSUMS)
    if not isinstance(hashes, dict) or set(hashes) != declared:
        raise ValueError('SHA256 完整性索引未覆盖所有声明的文件')
    for name, digest in hashes.items():
        if (not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
                or hashlib.sha256(contents[name]).hexdigest() != digest):
            raise ValueError(f'SHA256 完整性校验失败：{name}')
    if 'elements' in manifest:
        elements = contents[manifest['elements']]
        if _load_json(elements, '元素库') != _load_json(_portable_elements(elements), '元素库'):
            raise ValueError('发布包元素库不能包含临时浏览器身份，请重新构建包')
    return manifest, contents


def inspect_package(archive):
    """Verify archive boundaries, manifest and every checksum without extracting."""
    manifest, _contents = _verified_package(archive)
    return manifest


def extract_package(archive, destination):
    """Verify completely, then install the verified bytes into a new directory."""
    manifest, contents = _verified_package(archive)
    _write_new_directory(destination, contents)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description='WBot automation project packages')
    commands = parser.add_subparsers(dest='command', required=True)
    initialize = commands.add_parser('init')
    initialize.add_argument('path')
    initialize.add_argument('--name')
    build = commands.add_parser('build')
    build.add_argument('path')
    build.add_argument('--output')
    inspect = commands.add_parser('inspect')
    inspect.add_argument('archive')
    arguments = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    try:
        if arguments.command == 'init':
            result = create_project(arguments.path, arguments.name)
        elif arguments.command == 'build':
            archive = build_package(arguments.path, arguments.output)
            result = {'path': str(archive), 'manifest': inspect_package(archive)}
        else:
            result = inspect_package(arguments.archive)
    except (OSError, ValueError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
