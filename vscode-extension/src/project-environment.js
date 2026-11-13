'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const {execFile} = require('node:child_process');
const {promisify} = require('node:util');

const executeFile = promisify(execFile);
const sdkWheel = 'wbot-0.1.1-py3-none-any.whl';

function projectPythonPath(project) {
  return path.join(project, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
}

async function runPython(python, args, {cwd, log = () => {}}) {
  const running = executeFile(python, ['-I', '-X', 'utf8', ...args], {
    cwd, windowsHide:true, encoding:'utf8', timeout:600000, maxBuffer:8 * 1024 * 1024
  });
  running.child.stdout?.on('data', chunk => log(String(chunk).trimEnd()));
  running.child.stderr?.on('data', chunk => log(String(chunk).trimEnd()));
  try {
    return (await running).stdout;
  } catch (error) {
    if (error.code === 'ENOENT') throw new Error('找不到所选 Python 解释器');
    if (error.killed) throw new Error('环境搭建超时，请检查网络或软件源');
    throw new Error(String(error.stderr || error.stdout || error.message).trim());
  }
}

async function writeJson(file, value) {
  await fs.writeFile(file, JSON.stringify(value, null, 2) + '\n', {flag:'wx'});
}

function requirementsText(dependencies) {
  const lines = Object.entries(dependencies).sort(([a], [b]) => a.localeCompare(b))
    .filter(([name]) => name !== 'wbot').map(([name, version]) => `${name}==${version}`);
  return [`# wbot==${dependencies.wbot}，使用项目附带的 SDK wheel`,
    `./.wbot/wheels/${sdkWheel}`, ...lines, ''].join('\n');
}

async function configureEditor(project) {
  const interpreter = '${workspaceFolder}/.venv/' +
    (process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  await fs.mkdir(path.join(project, '.vscode'));
  await writeJson(path.join(project, '.vscode/settings.json'), {
    'wbot.pythonPath':interpreter,
    'python.defaultInterpreterPath':interpreter
  });
  await writeJson(path.join(project, '.vscode/launch.json'), {
    version:'0.2.0', configurations:[{name:'WBot：调试流程', type:'debugpy', request:'launch',
      program:'${workspaceFolder}/main.py', python:interpreter, cwd:'${workspaceFolder}',
      console:'integratedTerminal', justMyCode:true}]
  });
}

async function initializeProject({python, runtime, project, name, wheel, report = () => {}, log = () => {}}) {
  try {
    await fs.lstat(project);
    throw new Error(`目标目录已存在：${project}`);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  const sourceWheel = wheel || path.join(runtime, 'wheels', sdkWheel);
  try { await fs.access(sourceWheel); }
  catch { throw new Error('扩展缺少内置 SDK wheel，请重新安装完整的 WBot 扩展'); }
  report('检查 Python 与项目模板');
  const files = JSON.parse(await runPython(python,
    [path.join(runtime, 'app/project_template.py'), name], {cwd:runtime}));
  await fs.mkdir(project);
  let stage = '创建初始目录';
  try {
    report(stage);
    for (const [file, content] of Object.entries(files)) {
      await fs.writeFile(path.join(project, file), content, {flag:'wx'});
    }
    for (const directory of ['data', 'output', '.wbot/wheels']) {
      await fs.mkdir(path.join(project, directory), {recursive:true});
    }
    await fs.writeFile(path.join(project, 'data/.gitkeep'), '', {flag:'wx'});
    await fs.copyFile(sourceWheel, path.join(project, '.wbot/wheels', sdkWheel), fs.constants.COPYFILE_EXCL);
    await fs.writeFile(path.join(project, 'requirements.txt'), `./.wbot/wheels/${sdkWheel}\n`, {flag:'wx'});
    await fs.writeFile(path.join(project, '.gitignore'), '.venv/\n__pycache__/\n*.py[cod]\noutput/\ndist/\n.env\n', {flag:'wx'});
    await fs.writeFile(path.join(project, 'README.md'), `# ${name}\n\n` +
      '代码入口为 main.py；data/ 存放输入资料，output/ 存放运行输出。\n\n' +
      '项目使用独立 .venv。请在 VS Code 中打开本目录，运行 main.py；断点调试需要 Microsoft Python Debugger。\n\n' +
      '重建环境：使用 Python 3.10+ 执行 python -m venv .venv，再用该环境的 Python 执行 -m pip install -r requirements.txt。所有命令在项目根目录执行。\n\n' +
      '新增依赖后更新 requirements.txt 和 wbot.json 的 requirements；新增发布文件需加入清单 files。\n\n' +
      '虚拟环境不提交到 Git，也不能直接复制到其他电脑。当前发布包仍只包含清单声明的文件，不包含 .venv；Assistant 的独立环境托管需由后续发布协议支持。\n', {flag:'wx'});
    stage = '创建项目虚拟环境'; report(stage);
    await runPython(python, ['-m', 'venv', path.join(project, '.venv')], {cwd:project, log});
    const interpreter = projectPythonPath(project);
    stage = '安装 WBot SDK 与依赖'; report(stage);
    await runPython(interpreter, ['-m', 'pip', '--disable-pip-version-check', '--no-input',
      'install', '-r', 'requirements.txt'], {cwd:project, log});
    stage = '校验并记录依赖版本'; report(stage);
    await runPython(interpreter, ['-m', 'pip', 'check'], {cwd:project, log});
    const dependencies = JSON.parse(await runPython(interpreter, ['-c',
      'import importlib.metadata as m,json,wbot,lxml; print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions() if d.metadata["Name"].lower() not in ("pip", "setuptools", "wheel")}))'], {cwd:project}));
    const manifest = JSON.parse(files['wbot.json']);
    manifest.requirements = dependencies;
    await fs.writeFile(path.join(project, 'requirements.txt'), requirementsText(dependencies));
    await fs.writeFile(path.join(project, 'wbot.json'), JSON.stringify(manifest, null, 2) + '\n');
    await configureEditor(project);
    return manifest;
  } catch (error) {
    throw new Error(`${stage}失败：${error.message}\n未完成的项目保留在 ${project}。` +
      '请查看 WBot 输出；修复后可按项目 README 重建环境，或选择新的项目目录重新创建。');
  }
}

module.exports = {initializeProject, projectPythonPath};
