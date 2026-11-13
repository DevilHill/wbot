"""Dependency-free starter files, shared by the CLI and VS Code bootstrap."""
import json
import re
import sys


def project_template(name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', name):
        raise ValueError('项目名称需要 1–80 位英文字母、数字、连字符或下划线')
    manifest = {'schemaVersion': 1, 'name': name, 'version': '0.1.0',
                'entry': 'main.py', 'files': ['main.py'], 'requirements': {},
                'parameters': {'name': {'type': 'string', 'default': 'WBot', 'description': '问候对象'}}}
    script = ('import os\n'
              'from wbot import runtime\n\n'
              'def main():\n'
              '    hosted = bool(os.environ.get("WBOT_RUN_INPUT"))\n'
              '    parameters = runtime.parameters() if hosted else {"name": "WBot"}\n'
              '    message = f"你好，{parameters[\'name\']}"\n'
              '    print(message)\n'
              '    if hosted:\n'
              '        runtime.set_result({"message": message})\n\n'
              'if __name__ == "__main__":\n'
              '    main()\n')
    return {'wbot.json': json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
            'main.py': script}


if __name__ == '__main__':
    if sys.version_info < (3, 10):
        raise SystemExit('项目需要 Python 3.10 或更新版本')
    print(json.dumps(project_template(sys.argv[1]), ensure_ascii=False))
