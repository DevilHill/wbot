'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const {execFile} = require('node:child_process');
const {promisify} = require('node:util');
const {initializeProject} = require('./project-environment');

const executeFile = promisify(execFile);

async function selectProjectFolder(vscode) {
  const folders = vscode.workspace.workspaceFolders || [];
  if (!folders.length) throw new Error('请先打开自动化项目文件夹');
  const resource = vscode.window.activeTextEditor?.document.uri;
  let selected = resource?.scheme === 'file' && vscode.workspace.getWorkspaceFolder(resource);
  if (!selected) {
    selected = folders.length === 1 ? folders[0] :
      await vscode.window.showWorkspaceFolderPick({placeHolder:'选择要构建的自动化项目'});
  }
  if (selected && selected.uri.scheme !== 'file') throw new Error('仅支持本机自动化项目');
  return selected;
}

function commandError(error) {
  if (error.code === 'ENOENT') return new Error('找不到所选 Python，请先选择可用的 Python 解释器');
  if (error.killed) return new Error('项目命令执行超时，请查看项目大小和磁盘状态');
  const stderr = String(error.stderr || '').trim();
  try {
    const result = JSON.parse(stderr);
    if (result.error) return new Error(String(result.error));
  } catch { /* Python 启动或导入错误可能没有 JSON 输出。 */ }
  return new Error(stderr || error.message);
}

async function runProjectCommand(options) {
  const script = path.join(options.runtime, 'app', 'automation_package.py');
  const args = ['-X', 'utf8', script, options.action, options.project];
  if (options.name) args.push('--name', options.name);
  let stdout;
  try {
    ({stdout} = await executeFile(options.python, args, {
      cwd:options.runtime, windowsHide:true, encoding:'utf8',
      timeout:120000, maxBuffer:2 * 1024 * 1024,
      env:{...process.env, PYTHONIOENCODING:'utf-8'}
    }));
  } catch (error) {
    throw commandError(error);
  }
  try {
    return JSON.parse(stdout);
  } catch {
    throw new Error('项目工具返回的不是 JSON，请更新扩展运行资源');
  }
}

function createProjectCommands({vscode, runtime, output, pythonExecutable}) {
  async function execute(action, project, resource, name) {
    const python = await pythonExecutable(resource);
    const title = action === 'init' ? 'WBot：初始化自动化项目' : 'WBot：构建自动化发布包';
    output.appendLine(`${title} · ${project}`);
    return vscode.window.withProgress({location:vscode.ProgressLocation.Notification, title},
      () => runProjectCommand({python, runtime, action, project, name}));
  }

  async function initProject() {
    const parents = await vscode.window.showOpenDialog({
      title:'选择新项目的父目录', openLabel:'选择父目录',
      canSelectFolders:true, canSelectFiles:false, canSelectMany:false
    });
    const parent = parents?.[0];
    if (!parent) return;
    if (parent.scheme !== 'file') throw new Error('仅支持本机项目目录');
    const name = await vscode.window.showInputBox({
      title:'新建自动化项目', value:'my-automation',
      prompt:'在所选父目录下创建新目录；项目名称使用英文字母、数字、连字符或下划线',
      validateInput:value => /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(value) ? undefined :
        '以英文字母或数字开头，最多 80 位，仅使用英文字母、数字、连字符或下划线'
    });
    if (name === undefined) return;
    const directory = path.join(parent.fsPath, name);
    const currentPython = await pythonExecutable(parent);
    const selected = await vscode.window.showQuickPick([
      {label:'使用当前 Python 创建独立环境', description:currentPython, python:currentPython},
      {label:'选择其他 Python 解释器'}
    ], {title:'选择项目的基础 Python（3.10+）', placeHolder:'只用于创建本项目的 .venv，不向基础 Python 安装依赖'});
    if (!selected) return;
    let python = selected.python;
    if (!python) {
      const interpreters = await vscode.window.showOpenDialog({title:'选择 Python 解释器',
        canSelectFiles:true, canSelectFolders:false, canSelectMany:false});
      if (!interpreters?.[0]) return;
      if (interpreters[0].scheme !== 'file') throw new Error('仅支持本机 Python 解释器');
      python = interpreters[0].fsPath;
    }
    output.appendLine(`新建自动化项目 · ${directory} · ${python}`);
    const manifest = await vscode.window.withProgress({location:vscode.ProgressLocation.Notification,
      title:'WBot：新建项目并搭建虚拟环境'}, progress => initializeProject({
      python, runtime, project:directory, name, log:line => output.appendLine(line),
      report:message => { progress.report({message}); output.appendLine(message); }
    }));
    const choice = await vscode.window.showInformationMessage(`项目与独立虚拟环境已就绪：${directory}`, '在新窗口打开');
    if (choice === '在新窗口打开') await vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(directory), true);
    return manifest;
  }

  async function buildPackage({notify = true} = {}) {
    const folder = await selectProjectFolder(vscode);
    if (!folder || !await vscode.workspace.saveAll()) return;
    try {
      await fs.access(path.join(folder.uri.fsPath, 'wbot.json'));
    } catch (error) {
      if (error.code === 'ENOENT') throw new Error('所选项目缺少 wbot.json，请先初始化自动化项目');
      throw error;
    }
    const built = await execute('build', folder.uri.fsPath, folder.uri);
    if (typeof built.path !== 'string') throw new Error('构建结果缺少发布包路径，请更新扩展运行资源');
    output.appendLine(`已构建自动化发布包：${built.path}`);
    if (notify) Promise.resolve(vscode.window.showInformationMessage(`发布包已生成：${built.path}`, '在文件管理器中显示'))
      .then(choice => choice === '在文件管理器中显示' &&
        vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(built.path)))
      .catch(error => output.appendLine(`无法显示发布包：${error.message}`));
    return built;
  }

  return {initProject, buildPackage};
}

module.exports = {selectProjectFolder, runProjectCommand, createProjectCommands};
