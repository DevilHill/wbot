'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const vscode = require('vscode');

async function run() {
  const folder = vscode.workspace.workspaceFolders[0];
  const project = folder.uri.fsPath;
  const report = {checks:[], passed:false};
  try {
    const manifest = require('../package.json');
    await vscode.extensions.getExtension(manifest.publisher + '.' + manifest.name).activate();
    const entry = vscode.Uri.file(path.join(project, 'main.py'));
    assert.ok(vscode.workspace.getConfiguration('wbot', entry).get('pythonPath').includes('${workspaceFolder}'));
    await vscode.workspace.getConfiguration('wbot').update('pythonPath', 'C:/missing-global/python.exe',
      vscode.ConfigurationTarget.Global);
    await fs.appendFile(entry.fsPath, '\nimport json,sys,wbot\nfrom pathlib import Path\n' +
      'Path("run-environment.json").write_text(json.dumps({"prefix":sys.prefix,"sdk":wbot.__file__}))\n');
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(entry));
    let listener, timer;
    const finished = new Promise((resolve, reject) => {
      timer = setTimeout(() => reject(new Error('新项目运行超时')), 30000);
      listener = vscode.tasks.onDidEndTaskProcess(event => {
        if (event.execution.task.source === 'WBot') resolve(event.exitCode);
      });
    });
    try {
      await vscode.commands.executeCommand('wbot.runFile');
      assert.equal(await finished, 0);
    } finally { clearTimeout(timer); listener.dispose(); }
    const actual = JSON.parse(await fs.readFile(path.join(project, 'run-environment.json'), 'utf8'));
    assert.equal(path.resolve(actual.prefix).toLowerCase(), path.join(project, '.venv').toLowerCase());
    assert.ok(actual.sdk.toLowerCase().startsWith(path.join(project, '.venv').toLowerCase() + path.sep));
    report.checks.push('新窗口读取生成的项目配置，全局解释器无效时仍使用项目 .venv 运行并导入独立 SDK');
    report.passed = true;
  } catch (error) { report.error = error.stack; throw error; }
  finally {
    await fs.writeFile(path.join(project, 'integration-report.json'), JSON.stringify(report, null, 2));
  }
}

module.exports = {run};
