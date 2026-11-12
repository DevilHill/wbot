'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {startSharedFixture}=require('./shared-fixture');
const {requestBrowser}=require('../src/assistant-browser');
const vscode = require('vscode');
const core = require('../src/core');
const {configureLegacy}=require('./host-settings');
const {verifySharedElementsHost} = require('./shared-host');

async function until(predicate, timeout=30000) {
  const end = Date.now()+timeout;
  while (Date.now()<end) { if (predicate()) return; await new Promise(resolve=>setTimeout(resolve,30)); }
  throw new Error('等待扩展操作完成超时');
}

async function executeTask(command) {
  let listener;
  const completed = new Promise((resolve,reject) => {
    const timer = setTimeout(() => { listener.dispose(); reject(new Error(command+' 任务未完成')); },30000);
    listener = vscode.tasks.onDidEndTaskProcess(event => { if (event.execution.task.source === 'WBot') { clearTimeout(timer); listener.dispose(); resolve(event.exitCode); } });
  });
  await vscode.commands.executeCommand(command);
  assert.equal(await completed,0,command);
}

async function verifyPythonDebugger(workspace, check) {
  assert.ok(vscode.extensions.getExtension('ms-python.debugpy'), '请为宿主测试提供 --debugger-extension');
  const script = path.join(workspace,'debug_test.py');
  const output = path.join(workspace,'debug-result.txt');
  const example = await fs.readFile(path.join(__dirname,'../examples/code-demo.py'),'utf8');
  // 保留示例函数与断点位置，只把最终结果写到隔离工作区供断言。
  const code = 'from pathlib import Path\n'+example.replace(/    main\(\)\s*$/,`    Path(${core.pyString(output)}).write_text(main(), encoding="utf-8")\n`);
  assert.ok(code.includes('write_text(main()'));
  const breakpointLine = code.split('\n').findIndex(line=>line.includes('message = strings.replace('));
  assert.ok(breakpointLine>=0);
  await fs.writeFile(script,code);
  await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(script));
  const breakpoint = new vscode.SourceBreakpoint(new vscode.Location(vscode.Uri.file(script),new vscode.Position(breakpointLine,0)));
  const sessions = [];
  const tracker = vscode.debug.registerDebugAdapterTrackerFactory('debugpy',{
    createDebugAdapterTracker(session) {
      if (typeof session.configuration.program!=='string' || path.resolve(session.configuration.program).toLowerCase()!==script.toLowerCase()) return;
      const state = {session,stops:[],ended:false}; sessions.push(state);
      return {onDidSendMessage(message) {
        if (message.type==='event' && message.event==='stopped') state.stops.push(message.body);
      }};
    }
  });
  const terminated = vscode.debug.onDidTerminateDebugSession(session=>{
    const state=sessions.find(item=>item.session.id===session.id); if(state) state.ended=true;
  });
  async function localValue(state,stop) {
    const stack = await state.session.customRequest('stackTrace',{threadId:stop.threadId,startFrame:0,levels:1});
    assert.equal(path.resolve(stack.stackFrames[0].source.path).toLowerCase(),script.toLowerCase());
    const frameId = stack.stackFrames[0].id;
    const scopes = await state.session.customRequest('scopes',{frameId});
    for (const scope of scopes.scopes.filter(scope=>!scope.expensive)) {
      const values = await state.session.customRequest('variables',{variablesReference:scope.variablesReference});
      const value = values.variables.find(item=>item.name==='message');
      if (value) return value.value;
    }
    throw new Error('暂停时未找到局部变量 message');
  }
  try {
    vscode.debug.addBreakpoints([breakpoint]);
    assert.equal(await vscode.commands.executeCommand('wbot.debugFile'),true);
    await until(()=>sessions[0]?.stops.length);
    const first=sessions[0], initial=first.stops[0];
    assert.equal(initial.reason,'breakpoint');
    assert.match(await localValue(first,initial),/你好，WBot/);
    await assert.rejects(fs.access(output));
    check('Python debugpy 真实命中源码断点，读取局部变量，未执行断点行');
    await first.session.customRequest('next',{threadId:initial.threadId,granularity:'statement'});
    await until(()=>first.stops.length===2);
    assert.equal(first.stops[1].reason,'step');
    assert.match(await localValue(first,first.stops[1]),/您好，WBot/);
    await assert.rejects(fs.access(output));
    check('Python 单步越过替换语句，变量从你好更新为您好');
    await first.session.customRequest('continue',{threadId:first.stops[1].threadId});
    await until(()=>first.ended);
    assert.equal(await fs.readFile(output,'utf8'),'您好，WBot');
    check('Python 继续执行至结束并得到实际脚本结果');
    await fs.unlink(output);
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(script));
    assert.equal(await vscode.commands.executeCommand('wbot.debugFile'),true);
    await until(()=>sessions[1]?.stops.length);
    const second=sessions[1];
    assert.equal(second.stops[0].reason,'breakpoint');
    await vscode.debug.stopDebugging(second.session);
    await until(()=>second.ended);
    await assert.rejects(fs.access(output));
    check('Python 断点暂停时停止调试，后续语句未执行');
  } finally {
    for(const state of sessions) if(!state.ended) await vscode.debug.stopDebugging(state.session);
    vscode.debug.removeBreakpoints([breakpoint]);
    tracker.dispose(); terminated.dispose();
  }
}

async function run() {
  const workspace = vscode.workspace.workspaceFolders[0].uri.fsPath;
  const report = {checks:[],skipped:[],passed:false};
  const check = name => report.checks.push(name);
  let api, fixture;
  try {
    assert.equal(vscode.workspace.isTrusted,true);
    fixture=await startSharedFixture();
    await configureLegacy(vscode,{assistantStateDir:fixture.assistant_dir});
    const extension = vscode.extensions.getExtension(require('../package.json').publisher+'.'+require('../package.json').name);
    assert.ok(extension);
    api = await extension.activate();
    check('扩展激活');
    await api.connectionReady;
    await api.refreshConnections();
    assert.deepEqual(api.connectionView.getChildren(),['assistant','oc']);
    for(const key of ['bridgeUrl','assistantStateDir','libraryPath','ocUrl']) assert.equal(extension.packageJSON.contributes.configuration.properties['wbot.'+key],undefined);
    check('连接侧栏仅 Assistant 与 OC，常规设置不再要求地址和数据目录');
    const commands = await vscode.commands.getCommands(true);
    for (const command of extension.packageJSON.contributes.commands) assert.ok(commands.includes(command.command),command.command);
    check('全部 '+extension.packageJSON.contributes.commands.length+' 个命令已注册');
    assert.equal(commands.includes('wbot.newFlow'),false);
    assert.equal(commands.includes('wbot.openWorkbench'),false);
    assert.ok(!extension.packageJSON.contributes.customEditors?.length);
    assert.equal(api.flows,undefined);
    check('编码版不再注册图形流程和定位工作台入口');
    const jsonFile=path.join(workspace,'旧流程.wbot.json');
    const original='{"format":"wbot-flow","steps":[]}\n';
    await fs.writeFile(jsonFile,original);
    await vscode.commands.executeCommand('vscode.open',vscode.Uri.file(jsonFile));
    await until(()=>vscode.window.activeTextEditor?.document.uri.fsPath===jsonFile);
    assert.equal(vscode.window.activeTextEditor.document.getText(),original);
    assert.ok(!vscode.window.tabGroups.all.some(g=>g.tabs.some(t=>t.input?.viewType==='wbot.flowEditor')));
    check('已有 .wbot.json 文件仍可作为普通文本打开，内容保持不变');
    const info=await requestBrowser(fixture.assistant_dir);
    const base=info.bridge_url, database=info.library_path;
    const cfg = vscode.workspace.getConfiguration('wbot');
    await cfg.update('pythonPath',process.env.WBOT_TEST_PYTHON,vscode.ConfigurationTarget.Global);

    await executeTask('wbot.installRuntime');
    check('安装内置 wheel 到测试 Python 环境');
    await cfg.update('pythonPath','C:/missing-python/python.exe',vscode.ConfigurationTarget.Global);
    await api.refresh();
    assert.equal(api.bridge,undefined);
    await cfg.update('pythonPath',process.env.WBOT_TEST_PYTHON,vscode.ConfigurationTarget.Global);
    assert.equal((await core.request(base,'/api/health')).wbot,'0.1.1');
    check('Python 路径无效时仍通过 Assistant 读取元素库，插件不创建服务进程');
    const record = (await requestBrowser(fixture.assistant_dir,'/api/elements/save',{record:{name:'搜索"框 ${1}',group:'中文分组',xpath:'//input[@id="q"]',url:'https://example.com'}})).item;
    await api.refresh();
    assert.equal(api.getElements().length,1);
    const groups = api.provider.getChildren();
    assert.equal(groups[0].name,'中文分组');
    const nodes = api.provider.getChildren(groups[0]);
    assert.equal(api.provider.getTreeItem(nodes[0]).label,record.name);
    check('元素库读取、分组及 TreeItem');
    const completionFile=path.join(workspace,'completion_test.py');
    await fs.writeFile(completionFile,'from wbot import selector\nelements = selector.SelectorStore()\nelements.get("搜');
    const completionDocument=await vscode.workspace.openTextDocument(completionFile);
    await vscode.window.showTextDocument(completionDocument);
    const completion=await vscode.commands.executeCommand('vscode.executeCompletionItemProvider',completionDocument.uri,new vscode.Position(2,'elements.get("搜'.length));
    assert.ok(completion.items.some(item=>item.label===record.name));
    check('真实 Python 编辑器提供项目元素名补全');
    const editing=vscode.commands.executeCommand('wbot.editElement',nodes[0]);
    await until(()=>vscode.window.tabGroups.all.some(group=>group.tabs.some(tab=>tab.input?.viewType?.includes('wbot.elementEditor'))));
    const elementTab=vscode.window.tabGroups.all.flatMap(group=>group.tabs).find(tab=>tab.input?.viewType?.includes('wbot.elementEditor'));
    await vscode.window.tabGroups.close(elementTab);
    await editing;
    assert.equal(api.getElements()[0].xpath,record.xpath);
    check('真实 Webview 元素表单打开与关闭取消，不修改库记录');

    const doc = await vscode.workspace.openTextDocument({language:'python',content:''});
    await vscode.window.showTextDocument(doc);
    await vscode.commands.executeCommand('wbot.insertElement',nodes[0]);
    assert.equal(doc.getText().replace(/\r\n/g,'\n'),core.elementCode(record,{baseUrl:base,libraryPath:database}));
    check('Python 原生编辑器插入正确转义的元素调用代码');
    // 真实运行任务：验证保存、解释器、参数、工作目录和库环境。
    const script = path.join(workspace,'task_test.py');
    const output = path.join(workspace,'task-result.json');
    await fs.writeFile(script,'import json, os, sys\nfrom wbot import ElementLibrary\nfrom pathlib import Path\n' +
      `Path(${core.pyString(output)}).write_text(json.dumps({"args":sys.argv[1:],"cwd":os.getcwd(),"bridge":os.environ.get("WBOT_BRIDGE_URL"),"count":len(ElementLibrary().list())}), encoding="utf-8")\n`);
    const args = ['中文 参数','$(not-shell)','a"b'];
    await cfg.update('scriptArgs',args,vscode.ConfigurationTarget.Global);
    const editor=await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(script));
    await editor.edit(edit=>edit.insert(new vscode.Position(0,0),'# 运行前保存的修改\n'));
    assert.equal(editor.document.isDirty,true);
    await executeTask('wbot.runFile');
    assert.equal(editor.document.isDirty,false);
    assert.ok((await fs.readFile(script,'utf8')).startsWith('# 运行前保存的修改'));
    const result = JSON.parse(await fs.readFile(output,'utf8'));
    assert.deepEqual(result.args,args);
    assert.equal(result.cwd.toLowerCase(),workspace.toLowerCase());
    assert.equal(result.bridge,base);
    assert.equal(result.count,1);
    check('真实 VS Code ProcessExecution 保存并运行 Python，参数、目录、元素库与环境正确');
    const packageEntry = path.join(workspace,'package_entry.py');
    await fs.writeFile(packageEntry,'print("initial")\n');
    await fs.writeFile(path.join(workspace,'wbot.json'),JSON.stringify({
      schemaVersion:1,name:'host-package',version:'0.1.0',entry:'package_entry.py',
      files:['package_entry.py'],parameters:{},requirements:{}
    }));
    const packageEditor=await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(packageEntry));
    await packageEditor.edit(edit=>edit.insert(new vscode.Position(0,0),'# package revision\n'));
    assert.equal(packageEditor.document.isDirty,true);
    const built=await vscode.commands.executeCommand('wbot.buildPackage');
    assert.ok(built?.path,'构建命令应返回真实发布包路径');
    await fs.access(built.path);
    assert.equal(built.manifest.name,'host-package');
    assert.equal(packageEditor.document.isDirty,false);
    assert.ok((await fs.readFile(packageEntry,'utf8')).startsWith('# package revision'));
    check('真实 VS Code 构建命令保存当前项目并生成带版本的自动化发布包');
    if(process.env.WBOT_TEST_DEBUGGER==='1') await verifyPythonDebugger(workspace,check);
    else report.skipped.push('Python debugpy 端到端测试：未传 --debugger-extension');
    assert.equal(commands.includes('wbot.stopBridge'),false);
    require('../extension').deactivate();
    assert.equal((await core.request(base,'/api/health')).ok,true);
    check('插件停用不会关闭 Assistant 的浏览器服务');
    await verifySharedElementsHost(vscode, check);
    report.passed = true;
  } catch (error) { report.error = error.stack; throw error; }
  finally {
    if (fixture) await fixture.close();
    await fs.writeFile(path.join(workspace,'integration-report.json'),JSON.stringify(report,null,2));
  }
}
module.exports = {run};
