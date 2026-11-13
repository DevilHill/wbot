'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {selectProjectFolder, createProjectCommands, runProjectCommand} = require('../src/project');
const {initializeProject, projectPythonPath} = require('../src/project-environment');

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

test('新建项目使用自己的虚拟环境，安装 SDK、锁定依赖并支持本地运行',
  {skip:!process.env.WBOT_TEST_WHEELS}, async t => {
    const directory = await temporaryDirectory(t);
    const project = path.join(directory, "新项目 空格 & 'quoted'");
    const result = await initializeProject({python, runtime, project, name:'isolated-project',
      wheel:path.join(runtime, 'dist/wbot/wbot-0.1.1-py3-none-any.whl')});
    assert.equal(result.name, 'isolated-project');
    const interpreter = projectPythonPath(project);
    const environment = JSON.parse(execFileSync(interpreter, ['-I', '-c',
      'import json,sys,wbot,lxml; print(json.dumps({"prefix":sys.prefix,"base":sys.base_prefix,"sdk":wbot.__file__}))'],
      {encoding:'utf8', windowsHide:true}));
    assert.notEqual(environment.prefix, environment.base);
    assert.ok(environment.sdk.startsWith(path.join(project, '.venv')));
    const manifest = JSON.parse(await fs.readFile(path.join(project, 'wbot.json'), 'utf8'));
    assert.equal(manifest.requirements.wbot, '0.1.1');
    assert.ok(manifest.requirements.lxml);
    assert.match(await fs.readFile(path.join(project, 'requirements.txt'), 'utf8'), /wbot==0\.1\.1/);
    const settings = JSON.parse(await fs.readFile(path.join(project, '.vscode/settings.json'), 'utf8'));
    assert.ok(settings['wbot.pythonPath'].startsWith('${workspaceFolder}/.venv/'));
    const output = execFileSync(interpreter, ['-X', 'utf8', path.join(project, 'main.py')],
      {cwd:project, encoding:'utf8', windowsHide:true});
    assert.match(output, /你好，WBot/);
    await assert.rejects(initializeProject({python, runtime, project, name:'replacement'}), /已存在/);
    assert.equal(JSON.parse(await fs.readFile(path.join(project, 'wbot.json'), 'utf8')).name, 'isolated-project');
  });

test('缺少 SDK 时在创建项目之前报错', async t => {
  const directory = await temporaryDirectory(t);
  const project = path.join(directory, 'failed-project');
  await assert.rejects(initializeProject({python, runtime, project, name:'failed-project',
    wheel:path.join(directory, 'missing.whl')}), /wheel|SDK/);
  await assert.rejects(fs.access(project));
});

test('依赖安装失败保留文件并报告阶段，不生成就绪的编辑器配置', async t => {
  const directory = await temporaryDirectory(t);
  const project = path.join(directory, 'broken-sdk');
  const wheel = path.join(directory, 'wbot-0.1.1-py3-none-any.whl');
  await fs.writeFile(wheel, 'invalid wheel');
  await assert.rejects(initializeProject({python, runtime, project, name:'broken-sdk', wheel}),
    /安装 WBot SDK 与依赖失败/);
  await fs.access(path.join(project, 'main.py'));
  await fs.access(projectPythonPath(project));
  await assert.rejects(fs.access(path.join(project, '.vscode/settings.json')));
});

test('取消新建项目时不创建文件也不启动解释器', async () => {
  const commands = createProjectCommands({vscode:{window:{showOpenDialog:async () => undefined}},
    runtime, output:{}, pythonExecutable:() => assert.fail('取消后不选择 Python')});
  assert.equal(await commands.initProject(), undefined);
});
