'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {selectProjectFolder, createProjectCommands, runProjectCommand} = require('../src/project');

const python = process.env.WBOT_TEST_PYTHON || 'python';
const runtime = path.resolve(__dirname, '../..');
const uri = file => ({scheme:'file', fsPath:file});
const folder = file => ({name:path.basename(file), uri:uri(file)});

async function temporaryDirectory(t) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'wbot-project-'));
  t.after(() => fs.rm(directory, {recursive:true, force:true}));
  return directory;
}

test('多根工作区优先选择当前文件所属项目；没有所属项目时让用户选择', async () => {
  const folders = [folder('/project-a'), folder('/project-b')];
  let picked = 0;
  const vscode = {
    workspace:{workspaceFolders:folders, getWorkspaceFolder:() => folders[1]},
    window:{activeTextEditor:{document:{uri:uri('/project-b/main.py')}},
      showWorkspaceFolderPick:async () => { picked++; return folders[0]; }}
  };
  assert.equal(await selectProjectFolder(vscode), folders[1]);
  assert.equal(picked, 0);
  vscode.workspace.getWorkspaceFolder = () => undefined;
  assert.equal(await selectProjectFolder(vscode), folders[0]);
  assert.equal(picked, 1);
  vscode.window.showWorkspaceFolderPick = async () => undefined;
  assert.equal(await selectProjectFolder(vscode), undefined);
});

test('没有本机项目时明确报错', async () => {
  await assert.rejects(selectProjectFolder({workspace:{}, window:{}}), /项目文件夹/);
  await assert.rejects(selectProjectFolder({
    workspace:{workspaceFolders:[{uri:{scheme:'vscode-remote',fsPath:'/project'}}]}, window:{}
  }), /本机/);
});

test('取消保存后不启动构建，也不报告构建完成', async () => {
  let saved = 0;
  const vscode = {
    workspace:{workspaceFolders:[folder('/project')], saveAll:async () => { saved++; return false; }},
    window:{showInformationMessage:() => assert.fail('取消保存不能报告成功')}
  };
  const commands = createProjectCommands({vscode, runtime:'unused', output:{},
    pythonExecutable:() => assert.fail('取消保存不能启动 Python')});
  assert.equal(await commands.buildPackage(), undefined);
  assert.equal(saved, 1);
});

test('真实 Python 项目命令保留特殊路径，拒绝覆盖项目与包，反馈清单错误', async t => {
  const directory = await temporaryDirectory(t);
  const project = path.join(directory, "项目 空格 & 'quoted'");
  const options = {python, runtime, project};
  const manifest = await runProjectCommand({...options, action:'init', name:'sample-project'});
  assert.equal(manifest.name, 'sample-project');
  await assert.rejects(runProjectCommand({...options, action:'init', name:'sample-project'}));
  const built = await runProjectCommand({...options, action:'build'});
  assert.equal(built.manifest.name, manifest.name);
  assert.ok(path.isAbsolute(built.path));
  await fs.access(built.path);
  await assert.rejects(runProjectCommand({...options, action:'build'}));
  const manifestPath = path.join(project, 'wbot.json');
  const invalid = {...JSON.parse(await fs.readFile(manifestPath, 'utf8')), entry:'../escape.py'};
  await fs.writeFile(manifestPath, JSON.stringify(invalid));
  await assert.rejects(runProjectCommand({...options, action:'build'}), /entry|路径|入口/);
});

test('构建先保存所有文件，再打包当前项目并返回产物', async t => {
  const directory = await temporaryDirectory(t);
  const project = path.join(directory, 'save-before-build');
  await runProjectCommand({python, runtime, project, action:'init', name:'save-before-build'});
  let saved = false;
  const messages = [];
  const vscode = {
    workspace:{workspaceFolders:[folder(project)], saveAll:async () => {
      await fs.writeFile(path.join(project, 'main.py'), 'print("saved revision")\n');
      saved = true;
      return true;
    }},
    window:{withProgress:async (_options, callback) => callback(),
      showInformationMessage:async message => { messages.push(message); }},
    ProgressLocation:{Notification:15}
  };
  const commands = createProjectCommands({vscode, runtime,
    output:{appendLine:() => {}}, pythonExecutable:async () => {
      assert.equal(saved, true);
      return python;
    }});
  const built = await commands.buildPackage();
  const content = execFileSync(python, ['-I', '-c',
    'import sys,zipfile; print(zipfile.ZipFile(sys.argv[1]).read("main.py").decode())', built.path],
    {encoding:'utf8', windowsHide:true});
  assert.match(content, /saved revision/);
  assert.ok(messages.some(message => message.includes(built.path)));
});

test('VSIX 校验拒绝缺少新增模块、多余旧模块或内容不一致的 wheel', () => {
  execFileSync(python, ['-I', '-X', 'utf8', path.join(__dirname, 'test_package_verification.py')],
    {encoding:'utf8', windowsHide:true, timeout:10000, stdio:'pipe'});
});
