"""核对 VSIX 中的可执行资源与源码逐字节一致。"""
from io import BytesIO
from pathlib import Path
import json
import sys
import zipfile

def verify_wheel_sources(wheel, root):
    source_names = {file.relative_to(root).as_posix() for file in (root / 'wbot').rglob('*.py')}
    wheel_names = {name for name in wheel.namelist() if name.startswith('wbot/') and name.endswith('.py')}
    assert wheel_names == source_names, (
        f'wheel 源码集合不一致：缺少 {sorted(source_names - wheel_names)}；'
        f'多出 {sorted(wheel_names - source_names)}'
    )
    for name in source_names:
        assert wheel.read(name) == (root / name).read_bytes(), name
    return len(source_names)


def main():
    extension = Path(__file__).resolve().parents[1]
    root = extension.parent
    source_manifest = json.loads((extension / 'package.json').read_text(encoding='utf-8'))
    package = root / f"dist/wbot-studio-{source_manifest['version']}.vsix"
    if len(sys.argv) > 1:
        package = Path(sys.argv[1]).resolve()
    checked = 0
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert not any('/node_modules/' in name or '/test/' in name or name.endswith('.sqlite3') for name in names)
        manifest = json.loads(archive.read('extension/package.json'))
        assert manifest['capabilities']['untrustedWorkspaces']['supported'] is False
        commands = {item['command'] for item in manifest['contributes']['commands']}
        assert commands == {item['command'] for item in source_manifest['contributes']['commands']}
        assert {'wbot.newScript', 'wbot.runFile', 'wbot.debugFile', 'wbot.pick',
                'wbot.insertElement', 'wbot.installRuntime',
                'wbot.initProject', 'wbot.buildPackage', 'wbot.sharedElements',
                'wbot.connectSharedElements', 'wbot.requestElementMerge'} <= commands
        assert not {'wbot.newFlow', 'wbot.openWorkbench'} & commands
        assert not manifest['contributes'].get('customEditors')
        assert not any(event.startswith('onCustomEditor:') for event in manifest['activationEvents'])
        forbidden = ('extension/media/flow-', 'extension/src/flow-editor.js',
                     'extension/runtime/flow_runner.py', 'extension/runtime/bridge_server.py',
                     'extension/runtime/extension/', 'extension/src/bridge.js', 'extension/runtime/app/web/',
                     'extension/runtime/app/assistant/web/')
        assert not any(name.startswith(forbidden) or name.endswith('.wbot.json') for name in names)
        assert {'extension/runtime/app/automation_package.py', 'extension/runtime/app/processes.py'} <= names
        assert {'extension/src/assistant-client.js', 'extension/src/shared-elements.js',
                'extension/src/shared-element-documents.js'} <= names
        for name in names:
            if not name.startswith('extension/') or name.endswith('/'):
                continue
            relative = name.removeprefix('extension/')
            source = extension / relative
            if relative == 'LICENSE.txt':
                source = root / 'LICENSE'
            elif relative.lower() == 'readme.md':
                source = extension / 'README.md'
            elif relative.startswith('runtime/'):
                inside = relative.removeprefix('runtime/')
                if inside.startswith(('app/', 'wbot/', 'extension/')):
                    source = root / inside
            assert source.is_file(), source
            assert archive.read(name) == source.read_bytes(), name
            checked += 1
        wheel_bytes = archive.read('extension/runtime/wheels/wbot-0.1.1-py3-none-any.whl')
        with zipfile.ZipFile(BytesIO(wheel_bytes)) as wheel:
            wheel_count = verify_wheel_sources(wheel, root)
    print(f'VSIX 资源逐字节一致：{checked} 个文件；内置 wheel：{wheel_count} 个 Python 文件。')


if __name__ == '__main__':
    main()
