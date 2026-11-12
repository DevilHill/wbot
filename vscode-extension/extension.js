'use strict';
const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');
const core = require('./src/core');
const {requestBrowser} = require('./src/assistant-browser');
const {createConnections} = require('./src/connections');
const {createProjectCommands} = require('./src/project');
const {createPublishCommands} = require('./src/publish');
const {registerCompletions} = require('./src/completions');
const {createSharedElementCommands} = require('./src/shared-elements');

const {createSharedView} = require('./src/shared-view');
const {editElementDraft} = require('./src/element-input');
const {assistantStateDir, requestAssistant} = require('./src/assistant-client');
const {createSharedElementDocuments} = require('./src/shared-element-documents');

function activate(context) {
  const output = vscode.window.createOutputChannel('WBot');
  const runtime = path.join(context.extensionPath, 'runtime');
  const changes = new vscode.EventEmitter();
  const elementDocuments = createSharedElementDocuments(vscode, context);
  const validations = new Map();
  let connections, browserInfo, browserDirectory;
  let connectionReload=Promise.resolve();
  const sharedView = createSharedView(vscode, context, async () => {
    trusted();
    await browserSession();
    const cfg = settings();
    return requestAssistant(assistantStateDir(cfg.assistantStateDir), 'status', {library_path:cfg.libraryPath});
  });
  let records = [], query = '', generation = 0, picking = false;
  registerCompletions(vscode, context, () => records);
  const settings = resource => {
    const cfg = vscode.workspace.getConfiguration('wbot', resource);
    return {baseUrl:browserInfo?.bridge_url || 'http://127.0.0.1:8790', libraryPath:browserInfo?.library_path || core.libraryPath(),
      pythonPath:cfg.get('pythonPath'), scriptArgs:cfg.get('scriptArgs', []), assistantStateDir:connections?.directory() || cfg.get('assistantStateDir')};
  };
  function trusted() {
    if (!vscode.workspace.isTrusted) throw new Error('请先将工作区设为受信任，再使用 WBot');
    if (vscode.env.remoteName) throw new Error('此版本仅支持本机 VS Code 窗口，请在本机打开项目');
  }
  connections = createConnections({vscode, context, enabled:vscode.workspace.isTrusted && !vscode.env.remoteName,
    legacyDirectory:() => vscode.workspace.getConfiguration('wbot').get('assistantStateDir',''),
    onAssistantChanged:() => { browserInfo=undefined; browserDirectory=undefined; generation++; records=[]; validations.clear(); changes.fire(); sharedView.invalidate(); void refresh(true); }});
  async function browserSession() {
    trusted();
    await connectionReload;
    await connections.settled();
    const directory=connections.connectedDirectory() || await connections.requireAssistant();
    if(!browserInfo || browserDirectory!==directory){
      const info=await requestBrowser(directory);
      if(connections.directory()!==directory)throw new Error('Assistant 已切换，请重试');
      browserInfo=info;browserDirectory=directory;
    }
    return directory;
  }
  const api = async (endpoint, body) => requestBrowser(await browserSession(),endpoint,body);
  const provider = {
    onDidChangeTreeData:changes.event,
    getChildren(node) {
      const items = records.filter(r => [r.name,r.group,r.xpath,r.description].some(v => String(v || '').toLowerCase().includes(query.toLowerCase())));
      if (node) return node.kind === 'group' ? items.filter(r => r.group === node.name).map(record => ({kind:'element',record})) : [];
      return [...new Set(items.map(r => r.group))].sort().map(name => ({kind:'group',name,count:items.filter(r => r.group === name).length}));
    },
    getTreeItem(node) {
      if (node.kind === 'group') {
        const item = new vscode.TreeItem(node.name, vscode.TreeItemCollapsibleState.Expanded);
        item.description = String(node.count); item.iconPath = new vscode.ThemeIcon('folder'); return item;
      }
      const r = node.record, item = new vscode.TreeItem(r.name, vscode.TreeItemCollapsibleState.None);
      item.id = r.id; item.contextValue = 'wbot.element'; item.iconPath = new vscode.ThemeIcon('symbol-field');
      item.description = r.xpath; item.tooltip = `${r.group} / ${r.name}\n${r.xpath}\n${r.url || ''}\n${r.description || ''}`;
      item.command = {command:'wbot.elementDetails', title:'查看元素详情', arguments:[node]}; return item;
    }
  };
  const view = vscode.window.createTreeView('wbot.elements', {treeDataProvider:provider, showCollapseAll:true});
  async function refresh(silent = false) {
    const current = ++generation;
    try {
      const data = await api('/api/elements');
      if (!Array.isArray(data.items)) throw new Error('元素库响应无效，请更新浏览器服务');
      if (current !== generation) return;
      records = data.items; view.message = query ? `搜索：${query}` : `${records.length} 个元素`;
      vscode.commands.executeCommand('setContext', 'wbot.bridgeConnected', true);
      view.description = 'Assistant'; changes.fire();
      return records;
    } catch (error) {
      if (current !== generation) return;
      vscode.commands.executeCommand('setContext', 'wbot.bridgeConnected', false);
      records = []; view.message = error.message; view.description = 'Assistant 未就绪';
      changes.fire();
      if (!silent) throw error;
    }
  }
  async function pythonExecutable(resource) {
    const configured = settings(resource).pythonPath;
    if (configured) return configured;
    const extension = vscode.extensions.getExtension('ms-python.python');
    if (extension) {
      try {
        const py = extension.isActive ? extension.exports : await extension.activate();
        const env = py.environments?.getActiveEnvironmentPath(resource);
        if (env) { const resolved = await py.environments.resolveEnvironment(env); if (resolved?.executable?.uri) return resolved.executable.uri.fsPath; }
      } catch (error) { output.appendLine('读取 Python 扩展解释器：' + error.message); }
    }
    const folder = resource && vscode.workspace.getWorkspaceFolder(resource) || vscode.workspace.workspaceFolders?.[0];
    if (folder) {
      const candidate = path.join(folder.uri.fsPath, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
      try { await fs.access(candidate); return candidate; } catch {}
    }
    return 'python';
  }
  async function chooseElement(node) {
    // 菜单参数仅作为ID引用，始终从当前加载数据选择，不接受任意调用对象。
    const found = records.find(r => r.id === node?.record?.id);
    if (found) return found;
    if (!records.length) await refresh();
    return (await vscode.window.showQuickPick(records.map(record => ({label:record.name,description:record.group,detail:record.xpath,record})),
      {placeHolder:'选择元素',matchOnDescription:true,matchOnDetail:true}))?.record;
  }
  async function editRecord(original = {}) {
    await browserSession();
    const source = settings();
    return editElementDraft(vscode, original, async record => {
      const current = settings();
      if (current.assistantStateDir !== source.assistantStateDir || current.baseUrl !== source.baseUrl || current.libraryPath !== source.libraryPath) throw new Error('元素库连接已改变，请关闭表单后重新编辑');
      const result = await api('/api/elements/save', {record});
      await refresh(); return result.item;
    });
  }
  async function insertElement(node) {
    const record = await chooseElement(node); if (!record) return;
    const code = core.elementCode(record, settings());
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'python') {
      await vscode.window.showTextDocument(await vscode.workspace.openTextDocument({language:'python',content:code})); return;
    }
    // 插入普通文本，防止元素名称中的 $ 被解释为代码片段占位符。
    await editor.edit(edit => edit.replace(editor.selection, code));
  }
  async function saveLastPick() { const {payload} = await api('/api/bridge/last'); return editRecord(core.pickedRecord(payload)); }
  async function pick() {
    if (picking) throw new Error('已有抓取进行中，请先完成或取消');
    picking = true;
    try {
      const before = (await api('/api/health')).bridge?.lastPickAt || 0;
      await api('/api/bridge/pick', {});
      const payload = await vscode.window.withProgress({location:vscode.ProgressLocation.Notification,
        title:'WBot：切换到网页，Ctrl＋左键锁定元素，Enter 确认',cancellable:true}, async (_progress, token) => {
        const end = Date.now() + 120000;
        while (Date.now() < end && !token.isCancellationRequested) {
          const health = await api('/api/health');
          if ((health.bridge?.lastPickAt || 0) > before) return (await api('/api/bridge/last')).payload;
          await new Promise(resolve => setTimeout(resolve, 500));
        }
        if (!token.isCancellationRequested) throw new Error('抓取等待超时，请确认扩展已连接并重试');
      });
      if (payload) return editRecord(core.pickedRecord(payload));
    } finally { picking = false; await api('/api/bridge/stop', {}).catch(() => {}); }
  }
  async function validateElement(node) {
    const record = await chooseElement(node); if (!record) return;
    const {payload} = await api('/api/bridge/last');
    if (!payload?.frame?.documentId || !payload.browserId) throw new Error('请先在对应网页重新抓取元素');
    if (!core.scopeMatches(record, payload)) throw new Error('该元素来自其他页面或框架，请先在对应页面重新抓取');
    const result = await api('/api/bridge/validate', {action:'validate',xpath:record.xpath,target:{...payload.frame,browserId:payload.browserId}});
    validations.set(record.id, {xpath:record.xpath, result, checkedAt:new Date().toLocaleString()});
    if (!result.valid) throw new Error(result.error || 'XPath 无效');
    vscode.window.showInformationMessage(`「${record.name}」匹配 ${result.count} 个节点，已高亮 ${result.highlighted || 0} 个元素。`);
    return result;
  }
  async function taskForFile(debug = false) {
    const document = vscode.window.activeTextEditor?.document;
    if (!document || document.languageId !== 'python' || document.uri.scheme !== 'file') throw new Error('请打开并保存一个本机 Python 文件');
    if (!await document.save()) return;
    const folder = vscode.workspace.getWorkspaceFolder(document.uri);
    if (!folder) throw new Error('请先将脚本所在文件夹作为工作区打开');
    const cfg = settings(document.uri), python = await pythonExecutable(document.uri);
    const env = {WBOT_ELEMENT_LIBRARY:cfg.libraryPath, WBOT_BRIDGE_URL:cfg.baseUrl, PYTHONIOENCODING:'utf-8'};
    if (debug) {
      if (!vscode.extensions.getExtension('ms-python.debugpy')) throw new Error('调试需要安装 Microsoft Python Debugger 扩展');
      return vscode.debug.startDebugging(folder, {type:'debugpy',request:'launch',name:'WBot: '+path.basename(document.fileName),
        program:document.fileName,python,cwd:folder.uri.fsPath,console:'integratedTerminal',justMyCode:true,args:cfg.scriptArgs,env});
    }
    const task = new vscode.Task({type:'wbot',file:document.fileName},folder,'运行 '+path.basename(document.fileName),'WBot',
      new vscode.ProcessExecution(python,[document.fileName,...cfg.scriptArgs],{cwd:folder.uri.fsPath,env}));
    task.presentationOptions = {reveal:vscode.TaskRevealKind.Always,panel:vscode.TaskPanelKind.Dedicated,clear:true};
    return vscode.tasks.executeTask(task);
  }
  async function installRuntime() {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) throw new Error('请先打开一个本机项目文件夹');
    const python = await pythonExecutable(vscode.window.activeTextEditor?.document.uri);
    const wheel = path.join(runtime, 'wheels/wbot-0.1.1-py3-none-any.whl');
    const task = new vscode.Task({type:'wbot',action:'install'},folder,'安装 wbot','WBot',
      new vscode.ProcessExecution(python,['-m','pip','install',wheel],{cwd:folder.uri.fsPath}));
    task.presentationOptions = {reveal:vscode.TaskRevealKind.Always};
    return vscode.tasks.executeTask(task);
  }
  async function prepareBrowserExtension() {
    const {directory:dest}=await api('/api/extension/prepare');
    await vscode.env.clipboard.writeText(dest);
    await vscode.commands.executeCommand('revealFileInOS',vscode.Uri.file(path.join(dest,'manifest.json')));
    vscode.window.showInformationMessage('目录已复制。请到 chrome://extensions 或 edge://extensions 开启开发者模式，加载此目录；更新后重新加载扩展并刷新网页。');
    return dest;
  }
  async function newScript() {
    const folder = vscode.workspace.workspaceFolders?.[0];
    const uri = await vscode.window.showSaveDialog({defaultUri:folder && vscode.Uri.joinPath(folder.uri,'wbot_script.py'),filters:{Python:['py']}});
    if (!uri) return;
    if (uri.scheme !== 'file') throw new Error('仅支持本机脚本文件');
    // 保存框之外也防止覆盖已有脚本。
    await fs.writeFile(uri.fsPath,core.scriptTemplate(settings(uri)),{flag:'wx'});
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(uri));
  }
  const projectCommands = createProjectCommands({vscode, runtime, output, pythonExecutable});
  const handlers = {
    ...projectCommands,
    connectAssistant:() => connections.connectAssistant(),
    connectOC:() => connections.connectOC(),
    manageOC:() => connections.manageOC(),
    disconnectOC:() => connections.disconnectOC(),
    refreshConnections:() => connections.refresh(),
    ...createPublishCommands({vscode, context, runtime, pythonExecutable, settings, connections, buildPackage:projectCommands.buildPackage, exportElements:async () => (await api('/api/elements/export')).data}),
    ...createSharedElementCommands({vscode, context, settings, refresh, onStatus:sharedView.update}),
    refreshSharedView:() => sharedView.refresh(),
    elementDetails:async node => {
      const record = await chooseElement(node); if (!record) return;
      const checked = validations.get(record.id);
      return elementDocuments.status({名称:record.name, 分组:record.group, XPath:record.xpath, 页面:record.url, 描述:record.description, 框架:record.frame, 最近验证:checked?.xpath === record.xpath ? checked : '尚未验证；可通过元素右键菜单校验并高亮'}, '元素详情');
    },
    refresh:() => refresh(), pick, saveLastPick, addElement:() => editRecord(),
    editElement:async node => { const record = await chooseElement(node); if (record) return editRecord(record); },
    deleteElement:async node => { const record = await chooseElement(node); if (!record) return;
      if (await vscode.window.showWarningMessage(`删除「${record.group} / ${record.name}」？`,{modal:true},'删除') !== '删除') return;
      await api('/api/elements/delete',{id:record.id}); await refresh(); },
    insertElement, copyXPath:async node => { const record = await chooseElement(node); if (record) await vscode.env.clipboard.writeText(record.xpath); },
    validateElement, search:async () => { const value = await vscode.window.showInputBox({title:'搜索元素（留空显示全部）',value:query});
      if (value !== undefined) { query = value; view.message = query ? `搜索：${query}` : `${records.length} 个元素`; changes.fire(); } },
    importElements:async () => {
      const uris = await vscode.window.showOpenDialog({canSelectMany:false,filters:{JSON:['json']}}); if (!uris?.length) return;
      const bytes = await vscode.workspace.fs.readFile(uris[0]); if (bytes.length > 1900000) throw new Error('导入文件不能超过 1.9 MB');
      const data = JSON.parse(Buffer.from(bytes).toString('utf8').replace(/^\uFEFF/,''));
      const choice = await vscode.window.showQuickPick([{label:'冲突时停止',value:'error'},{label:'跳过同名元素',value:'skip'},{label:'替换同名元素',value:'replace'}]); if (!choice) return;
      const result = await api('/api/elements/import',{data,conflict:choice.value}); await refresh();
      vscode.window.showInformationMessage(`导入完成：新增 ${result.result.inserted}，替换 ${result.result.replaced}，跳过 ${result.result.skipped}`);
    },
    exportElements:async () => { const result = await api('/api/elements/export');
      const uri = await vscode.window.showSaveDialog({saveLabel:'导出',filters:{JSON:['json']}}); if (!uri) return;
      await vscode.workspace.fs.writeFile(uri,Buffer.from(JSON.stringify(result.data,null,2))); },
    newScript, runFile:() => taskForFile(), debugFile:() => taskForFile(true), installRuntime,
    selectPython:async () => { const uris = await vscode.window.showOpenDialog({title:'选择 Python 可执行文件',canSelectMany:false,canSelectFolders:false});
      if (uris?.[0]) await vscode.workspace.getConfiguration('wbot').update('pythonPath',uris[0].fsPath,vscode.ConfigurationTarget.Global); },
    browserExtension:prepareBrowserExtension,
    showOutput:() => output.show(),
    help:async () => {
      let file = path.join(context.extensionPath,'README.md');
      try { await fs.access(file); } catch { file = path.join(context.extensionPath,'readme.md'); }
      return vscode.commands.executeCommand('markdown.showPreview',vscode.Uri.file(file));
    }
  };
  for (const [name, handler] of Object.entries(handlers)) {
    context.subscriptions.push(vscode.commands.registerCommand('wbot.'+name, async (...args) => {
      try { trusted();
        if (['sharedElements','connectSharedElements','sharedElementChanges','commitSharedElements','requestElementMerge','sharedElementStatus','pullSharedElements'].includes(name)) { await connections.requireAssistant(); await browserSession(); }
        const result = await handler(...args);
        if (['connectSharedElements','commitSharedElements','requestElementMerge','pullSharedElements','addElement','editElement','deleteElement','importElements','pick'].includes(name)) sharedView.refresh();
        return result; }
      catch (error) { output.appendLine(error.stack || String(error)); vscode.window.showErrorMessage('WBot: '+error.message); return undefined; }
    }));
  }
  context.subscriptions.push(output,view,changes,
    view.onDidChangeVisibility(event => { if (event.visible && vscode.workspace.isTrusted && !vscode.env.remoteName) void refresh().catch(error => { view.message = error.message; }); }),
    vscode.workspace.onDidChangeConfiguration(event => { if (event.affectsConfiguration('wbot.assistantStateDir')) { validations.clear(); sharedView.invalidate(); connectionReload=connections.reload(); void connectionReload.then(() => { void refresh(true); void sharedView.refresh(); }).catch(error=>output.appendLine(error.message)); } }));
  if (vscode.workspace.isTrusted && !vscode.env.remoteName) { refresh(true); sharedView.refresh(); }
  // 供集成测试与其他扩展只读查看状态；不添加隐藏的执行命令。
  return {refresh, getElements:() => structuredClone(records), provider, sharedView, connectionView:connections.provider, connectionReady:connections.ready, refreshConnections:connections.refresh};
}
function deactivate() {}
module.exports = {activate,deactivate};
