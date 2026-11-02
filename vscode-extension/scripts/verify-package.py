"""核对 VSIX 中的可执行资源与源码逐字节一致。"""
from io import BytesIO
from pathlib import Path
import json
import zipfile

extension = Path(__file__).resolve().parents[1]
root = extension.parent
source_manifest = json.loads((extension / 'package.json').read_text(encoding='utf-8'))
package = root / f"dist/wbot-studio-{source_manifest['version']}.vsix"
checked = 0
with zipfile.ZipFile(package) as archive:
    names = set(archive.namelist())
    assert not any('/node_modules/' in name or '/test/' in name or name.endswith('.sqlite3') for name in names)
    manifest = json.loads(archive.read('extension/package.json'))
    assert manifest['capabilities']['untrustedWorkspaces']['supported'] is False
    commands = {item['command'] for item in manifest['contributes']['commands']}
    assert len(commands) == 22
    assert {'wbot.newScript', 'wbot.runFile', 'wbot.debugFile', 'wbot.pick',
            'wbot.insertElement', 'wbot.startBridge', 'wbot.installRuntime'} <= commands
    assert not {'wbot.newFlow', 'wbot.openWorkbench'} & commands
    assert not manifest['contributes'].get('customEditors')
    assert not any(event.startswith('onCustomEditor:') for event in manifest['activationEvents'])
    forbidden = ('extension/media/flow-', 'extension/src/flow-editor.js',
                 'extension/runtime/flow_runner.py', 'extension/runtime/app/web/')
    assert not any(name.startswith(forbidden) or name.endswith('.wbot.json') for name in names)
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
            elif inside == 'bridge_server.py':
                source = extension / 'scripts' / inside
        assert source.is_file(), source
        assert archive.read(name) == source.read_bytes(), name
        checked += 1
    wheel = zipfile.ZipFile(BytesIO(archive.read('extension/runtime/wheels/wbot-0.1.0-py3-none-any.whl')))
    wheel_count = 0
    for name in wheel.namelist():
        if name.startswith('wbot/') and name.endswith('.py'):
            assert wheel.read(name) == (root / name).read_bytes(), name
            wheel_count += 1
print(f'VSIX 资源逐字节一致：{checked} 个文件；内置 wheel：{wheel_count} 个 Python 文件。')
