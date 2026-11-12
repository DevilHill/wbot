'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const {randomBytes} = require('node:crypto');
const {selectProjectFolder,runProjectCommand} = require('./project');
const {ocOrigin,publishAssistant,publishOC} = require('./publish-client');

function createPublishCommands({vscode,context,runtime,pythonExecutable,settings,buildPackage,exportElements}) {
  let publishing=false;
  async function publishPackage() {
    if(publishing)throw new Error('已有发布正在进行');
    publishing=true;
    try {
      const target=await vscode.window.showQuickPick([{label:'Assistant · 本机托管',value:'assistant',description:'安装到我的自动化，关闭 VS Code 后仍可运行'},{label:'OC · 企业包仓库',value:'oc',description:'上传版本，部署和调度在 OC 单独操作'}],{title:'发布自动化 · 选择目标'});
      if(!target)return;
      const source=await vscode.window.showQuickPick([{label:'构建并发布当前项目',value:'build'},{label:'发布已有版本包',value:'existing',description:'重试或分发已经构建的不可变版本'}],{title:'选择发布内容'});
      if(!source)return;
      let built;
      if(source.value==='build')built=await buildPackage({notify:false});
      else {
        const files=await vscode.window.showOpenDialog({canSelectMany:false,filters:{'WBot 发布包':['zip']}});if(!files?.[0])return;
        built={path:files[0].fsPath,manifest:await runProjectCommand({python:await pythonExecutable(files[0]),runtime,action:'inspect',project:files[0].fsPath})};
      }
      if(!built)return;
      let origin='',credentials;
      if(target.value==='oc'){
        const configured=vscode.workspace.getConfiguration('wbot').get('ocUrl','');
        const value=await vscode.window.showInputBox({title:'OC 管理平台地址',value:configured,placeHolder:'https://rpa.marswei.fun',validateInput:value=>{try{ocOrigin(value);}catch(error){return error.message;}}});if(value===undefined)return;
        origin=ocOrigin(value);
        const username=await vscode.window.showInputBox({title:'OC 开发者账号',ignoreFocusOut:true});if(!username)return;
        const password=await vscode.window.showInputBox({title:'OC 登录密码（仅本次发布使用）',password:true,ignoreFocusOut:true});if(password===undefined)return;
        credentials={username,password};
      }
      const record={id:randomBytes(12).toString('hex'),name:built.manifest.name,version:built.manifest.version,target:target.value,origin,path:built.path,time:new Date().toISOString(),state:'pending'};
      const history=context.globalState.get('wbot.publications',[]);await context.globalState.update('wbot.publications',[record,...history].slice(0,100));
      let installed;
      try {
        installed=await vscode.window.withProgress({location:vscode.ProgressLocation.Notification,title:`发布 ${record.name} ${record.version} → ${target.value==='oc'?'OC':'Assistant'}`},()=>target.value==='oc'?publishOC(origin,credentials,built):publishAssistant(settings().assistantStateDir,built));
        record.state='published';record.packageId=installed.id;
      } catch(error) {record.state='unconfirmed';record.error=error.message;throw error;}
      finally {
        credentials=undefined;
        const current=context.globalState.get('wbot.publications',[]);
        await context.globalState.update('wbot.publications',current.map(item=>item.id===record.id?record:item));
      }
      const choice=await vscode.window.showInformationMessage(`已发布 ${record.name} ${record.version} 到 ${target.value==='oc'?'OC 包仓库':'Assistant 我的自动化'}`,target.value==='oc'?'打开 OC':'查看发布记录');
      if(choice==='打开 OC')await vscode.env.openExternal(vscode.Uri.parse(origin+'/#packages'));
      if(choice==='查看发布记录')await publicationHistory();
      return installed;
    } finally {publishing=false;}
  }
  async function publicationHistory() {
    const history=context.globalState.get('wbot.publications',[]);
    const content=history.length?history.map(item=>`${item.time}  ${item.name}@${item.version} → ${item.target}${item.origin?' · '+item.origin:''}\n状态：${item.state==='published'?'已收到目标端回执':item.state==='pending'?'待核对（上次发布未完成）':'未确认，请核对目标端'}\n包：${item.path}\n${item.packageId?'目标包标识：'+item.packageId+'\n':''}${item.error?'说明：'+item.error+'\n':''}`).join('\n'):'尚无发布记录。使用“WBot: 发布自动化”开始。';
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument({language:'plaintext',content}));
  }
  async function snapshotElements() {
    const folder=await selectProjectFolder(vscode);if(!folder || !await vscode.workspace.saveAll())return;
    const manifestPath=path.join(folder.uri.fsPath,'wbot.json');
    if((await fs.lstat(manifestPath)).isSymbolicLink())throw new Error('项目清单不能是符号链接');
    const before=await fs.readFile(manifestPath,'utf8');const manifest=JSON.parse(before);
    if(!Array.isArray(manifest.files))throw new Error('wbot.json 缺少 files 列表');
    const exported=await exportElements();
    const chosen=await vscode.window.showQuickPick(exported.items.map(record=>({label:record.name,description:record.group,record})),{title:'选择要随项目发布的元素',canPickMany:true,matchOnDescription:true});if(!chosen)return;
    const filename=`elements-${randomBytes(4).toString('hex')}.json`;
    const destination=path.join(folder.uri.fsPath,filename);
    await fs.writeFile(destination,JSON.stringify({...exported,items:chosen.map(item=>item.record)},null,2)+'\n',{flag:'wx'});
    if(await fs.readFile(manifestPath,'utf8')!==before)throw new Error(`清单已被其他程序修改。元素已保存到 ${filename}，请手动加入 files 和 elements。`);
    manifest.files=[...new Set([...manifest.files,filename])];manifest.elements=filename;
    await fs.writeFile(manifestPath,JSON.stringify(manifest,null,2)+'\n');
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(vscode.Uri.file(destination)));
    vscode.window.showInformationMessage(`已将 ${chosen.length} 个元素加入项目快照；构建时会移除临时浏览器标识。`);
  }
  return {publishPackage,publicationHistory,snapshotElements};
}
module.exports={createPublishCommands};
