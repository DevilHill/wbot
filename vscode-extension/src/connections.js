"use strict";
const os = require('node:os');
const {assistantStateDir,readSession} = require('./assistant-client');
const {discoverAssistants} = require('./assistant-discovery');
const {send} = require('./publish-client');

function bindingOrigin(value) {
  let url;try{url=new URL(value);}catch{throw new Error('请输入 OC 地址，例如 https://rpa.marswei.fun');}
  if(!['http:','https:'].includes(url.protocol) || url.username || url.password || url.pathname!=='/' || url.search || url.hash)throw new Error('OC 地址不能包含账号、路径或查询参数');
  return url.origin;
}
async function assistantSettings(directory,body) {
  const {url,token}=await readSession(directory);
  const response=await send(url,body===undefined?'/api/settings':body===null?'/api/settings/disconnect':'/api/settings/connect',{
    method:body===undefined?'GET':'POST',headers:{'X-WBot-Token':token,'Content-Type':'application/json'},body:body===null?{}:body,timeout:8000});
  if(!response.payload?.settings || typeof response.payload.settings.binding_state!=='string')throw new Error('请升级 Assistant 后再管理 OC 绑定');
  return response.payload.settings;
}
const bindingLabels={unconfigured:'未绑定 · 点击绑定 OC',connecting:'正在申请绑定',pending:'待 OC 管理员批准',approved:'已绑定',rejected:'申请被拒绝 · 重新绑定',revoked:'授权已撤销 · 重新绑定',disconnected:'已断开 · 点击重新连接'};

function createConnections({vscode,context,enabled=true,legacyDirectory=()=>'',onAssistantChanged=()=>{},discover=discoverAssistants,settingsRequest=assistantSettings}) {
  const changes=new vscode.EventEmitter();
  let assistant=null,instances=[],assistantMessage='正在查找运行中的 Assistant';
  let binding=null,bindingError='',disposed=false,pending=null,wizard=false,revision=0;
  const provider={
    onDidChangeTreeData:changes.event,
    getChildren:()=>['assistant','oc'],
    getTreeItem(kind) {
      const item=new vscode.TreeItem(kind==='assistant'?'本机 Assistant':'OC 平台',vscode.TreeItemCollapsibleState.None);
      const connected=kind==='assistant'?Boolean(assistant):Boolean(assistant && binding?.binding_state==='approved' && !bindingError && !binding.error);
      item.id=kind;item.contextValue='wbot.connection.'+kind;
      item.description=kind==='assistant'?(assistant?`已连接 · ${assistant.version || '运行中'}`:assistantMessage):!assistant?'离线 · 请启动 Assistant':bindingError?'无法读取绑定 · 点击重试':binding?.error?'连接异常 · 点击检查':bindingLabels[binding?.binding_state] || '正在读取 Assistant 绑定';
      item.iconPath=new vscode.ThemeIcon(connected?'pass-filled':kind==='assistant'?'desktop-download':'cloud');
      item.tooltip=kind==='assistant'?(assistant?`自动发现 · PID ${assistant.pid}\n${assistant.directory}`:assistantMessage):!assistant?'OC 连接跟随本机 Assistant，请先启动 Assistant。':bindingError || [binding?.server_url || '通过 Assistant 提交 OC 地址和接入 Key',binding?.device_name,binding?.verification_code?'核验码：'+binding.verification_code:'',binding?.error].filter(Boolean).join('\n');
      item.command={command:kind==='assistant'?'wbot.connectAssistant':'wbot.manageOC',title:'管理连接'};
      return item;
    }
  };
  const view=vscode.window.createTreeView('wbot.connections',{treeDataProvider:provider});
  const status=vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left,12);
  status.command='wbot.connections.focus';status.show();
  function render() {
    if(disposed)return;
    status.text=`$(plug) WBot · Assistant ${assistant?'✓':'—'} · OC ${assistant && binding?.binding_state==='approved' && !bindingError && !binding.error?'✓':'—'}`;
    status.tooltip='OC 连接跟随本机 Assistant 的设备绑定';changes.fire();
  }
  async function refreshAssistant() {
    if(!enabled || disposed || wizard)return;
    const current=revision;
    const preferred=context.globalState.get('wbot.assistantSelection','') || legacyDirectory() || context.globalState.get('wbot.assistantDirectory','');
    const found=await discover({directories:[preferred,assistantStateDir()].filter(Boolean)});
    if(disposed || current!==revision)return;
    instances=found;
    const previous=assistant?.directory, previousPid=assistant?.pid;
    assistant=preferred?found.find(item=>item.directory===preferred):found.find(item=>item.directory===assistantStateDir()) || (found.length===1?found[0]:null);
    assistantMessage=found.length>1?'发现多个实例 · 点击选择':preferred && found.length?'原实例未运行 · 点击选择':'未运行 · 请打开 Assistant';
    if(assistant && !preferred)await context.globalState.update('wbot.assistantDirectory',assistant.directory);
    if(previous!==assistant?.directory || previousPid!==assistant?.pid){binding=null;bindingError='';onAssistantChanged();}
    if(assistant){
      try {const value=await settingsRequest(assistant.directory);if(disposed || current!==revision)return;binding=value;bindingError='';}
      catch(error){if(disposed || current!==revision)return;bindingError=error.message;}
    } else {binding=null;bindingError='';}
    render();
  }
  function refresh() {
    if(!pending)pending=refreshAssistant().finally(()=>{pending=null;});
    return pending;
  }
  async function reload() {
    revision++;
    if(pending)await pending;
    return refresh();
  }
  async function connectAssistant() {
    await refresh();
    if(!instances.length){await vscode.window.showInformationMessage('未发现正在运行的 Assistant。请先打开 Assistant；插件会自动连接并读取它的 OC 绑定。');return;}
    let selected=assistant;
    if(instances.length>1 || !selected)selected=(await vscode.window.showQuickPick(instances.map(item=>({label:`Assistant · PID ${item.pid}`,description:item.version,detail:item.directory,instance:item})),{title:'选择正在运行的 Assistant'}))?.instance;
    if(!selected)return;
    revision++;await context.globalState.update('wbot.assistantSelection',selected.directory);
    await context.globalState.update('wbot.assistantDirectory',selected.directory);
    assistant=selected;binding=null;onAssistantChanged();await refreshAssistant();return selected;
  }
  async function requireAssistant() {
    await refresh();
    if(!assistant && instances.length)await connectAssistant();
    if(!assistant)throw new Error('Assistant 离线。请先启动本机 Assistant，插件会自动连接并读取 OC 绑定');
    return assistant.directory;
  }
  async function connectOC() {
    if(wizard)return;
    const directory=await requireAssistant();
    wizard=true;revision++;
    try {
      const address=await vscode.window.showInputBox({title:'绑定 OC · 1/3 服务地址',value:binding?.server_url || '',placeHolder:'https://rpa.marswei.fun',ignoreFocusOut:true,validateInput:value=>{try{bindingOrigin(value.trim());}catch(error){return error.message;}}});
      if(address===undefined)return;
      const server_url=bindingOrigin(address.trim());
      const name=await vscode.window.showInputBox({title:'绑定 OC · 2/3 设备名称',value:binding?.device_name || os.hostname(),ignoreFocusOut:true,validateInput:value=>!value.trim() || value.trim().length>120?'请输入 1–120 字符的设备名称':undefined});
      if(name===undefined)return;
      const reuse=binding?.server_url===server_url && binding?.device_name===name.trim() && binding.has_binding_credentials && !['rejected','revoked'].includes(binding.binding_state);
      const key=await vscode.window.showInputBox({title:'绑定 OC · 3/3 接入 Key',password:true,ignoreFocusOut:true,prompt:reuse?'已有设备凭据，留空可重新连接；无需重新申请 Key。':'在 OC 的 Robot 连接页生成 Key；提交后等待管理员审批。',validateInput:value=>reuse && !value.trim()?undefined:/^wbot_[A-Za-z0-9_-]{43}$/.test(value.trim())?undefined:'请粘贴 OC 生成的完整接入 Key'});
      if(key===undefined)return;
      const body={server_url,device_name:name.trim()};if(key.trim())body.binding_key=key.trim();
      const result=await vscode.window.withProgress({location:vscode.ProgressLocation.Notification,title:'通过 Assistant 提交 OC 绑定'},()=>settingsRequest(directory,body));
      if(disposed)return;
      binding=result;bindingError='';onAssistantChanged();
      await vscode.window.showInformationMessage(result.binding_state==='approved'?'已通过 Assistant 恢复 OC 连接。':'已交给 Assistant 处理，绑定状态会自动更新；待审批时请管理员在 OC 核对并批准。');
      return result;
    } finally {wizard=false;render();}
  }
  async function disconnectOC() {
    if(wizard)return;
    const directory=await requireAssistant();
    if(await vscode.window.showWarningMessage('断开会暂停本机 Assistant 与 OC 的连接，也会影响其他使用同一 Assistant 的工具。',{modal:true},'断开连接')!=='断开连接')return;
    wizard=true;revision++;
    try{binding=await settingsRequest(directory,null);bindingError='';onAssistantChanged();}finally{wizard=false;render();}
  }
  async function requireOC() {
    await requireAssistant();
    if(bindingError)throw new Error(bindingError);
    if(!binding || binding.binding_state!=='approved')throw new Error('请先完成 Assistant 的 OC 绑定，并等待管理员批准；可在“连接 → OC 平台”查看进度');
    if(binding.error)throw new Error(binding.error);
    return {origin:bindingOrigin(binding.server_url)};
  }
  async function manageOC() {
    await requireAssistant();
    if(!binding?.server_url || binding.binding_state==='unconfigured')return connectOC();
    const action=await vscode.window.showQuickPick([{label:'查看绑定状态',value:'status'},{label:'绑定 / 重新连接 OC',value:'connect'},{label:'打开 OC 平台',value:'open'},{label:'断开 Assistant 的 OC 连接',value:'disconnect'}],{title:binding.server_url});
    if(action?.value==='status')return vscode.window.showInformationMessage([bindingError || bindingLabels[binding.binding_state],binding.verification_code?'核验码 '+binding.verification_code:'',binding.error].filter(Boolean).join(' · '));
    if(action?.value==='open')return vscode.env.openExternal(vscode.Uri.parse(bindingOrigin(binding.server_url)));
    if(action?.value==='connect')return connectOC();
    if(action?.value==='disconnect')return disconnectOC();
  }
  if(!enabled)assistantMessage='请在本机受信任工作区使用';
  const ready=refresh().catch(error=>{assistantMessage=error.message;render();});
  const timer=setInterval(()=>{void refresh().catch(()=>{});},10000);
  context.subscriptions.push(view,status,changes,{dispose(){disposed=true;revision++;clearInterval(timer);}});
  return {provider,ready,refresh,reload,connectAssistant,connectOC,disconnectOC,manageOC,requireAssistant,requireOC,
    settled:()=>pending || ready,
    connectedDirectory:()=>assistant?.directory,
    directory:()=>assistant?.directory || legacyDirectory() || context.globalState.get('wbot.assistantDirectory','') || assistantStateDir()};
}
module.exports={createConnections,bindingOrigin,assistantSettings};
