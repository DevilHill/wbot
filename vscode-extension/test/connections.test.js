"use strict";
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createConnections,assistantSettings}=require('../src/connections');
const {assistantStateDir}=require('../src/assistant-client');
function fixture(t) {
 const saved=new Map(),inputs=[],prompts=[],messages=[],requests=[];
 const context={subscriptions:[],globalState:{get:(key,fallback)=>saved.has(key)?saved.get(key):fallback,update:async(key,value)=>saved.set(key,value)}};
 class Emitter {event=()=>({dispose(){}});fire(){}dispose(){}}
 const vscode={EventEmitter:Emitter,TreeItem:class{constructor(label){this.label=label;}},TreeItemCollapsibleState:{None:0},ThemeIcon:class{},StatusBarAlignment:{Left:1},ProgressLocation:{Notification:1},window:{createTreeView:()=>({dispose(){}}),createStatusBarItem:()=>({show(){},dispose(){}}),showInputBox:async prompt=>{prompts.push(prompt);return inputs.shift();},showQuickPick:async items=>items[0],showInformationMessage:async message=>messages.push(message),showWarningMessage:async()=> '断开连接',withProgress:async(_options,action)=>action()},env:{openExternal:async()=>{}},Uri:{parse:value=>value}};
 let running=[],binding={binding_state:'unconfigured'},fail=false;
 const manager=createConnections({vscode,context,discover:async()=>running,settingsRequest:async(directory,body)=>{requests.push({directory,body});if(fail)throw new Error('Assistant 暂不可用');if(body===null)binding={...binding,binding_state:'disconnected'};else if(body)binding={server_url:body.server_url,device_name:body.device_name,binding_state:'connecting',has_binding_credentials:true};return binding;}});
 t.after(()=>context.subscriptions.forEach(item=>item.dispose()));
 return {manager,saved,inputs,prompts,messages,requests,setRunning:value=>{running=value;},setBinding:value=>{binding=value;},setFailure:()=>{fail=true;}};
}
const instance={directory:assistantStateDir(),pid:123,version:'0.8.0'};
test('侧栏只有两个连接，Assistant 离线时 OC 也离线，不能绕过它建立另一条连接',async t=>{
 const f=fixture(t);await f.manager.ready;
 assert.deepEqual(f.manager.provider.getChildren(),['assistant','oc']);
 assert.match(f.manager.provider.getTreeItem('oc').description,/离线/);
 await assert.rejects(f.manager.connectOC(),/Assistant 离线/);assert.equal(f.prompts.length,0);
 f.setRunning([instance]);await f.manager.refresh();assert.match(f.manager.provider.getTreeItem('assistant').description,/已连接/);assert.match(f.manager.provider.getTreeItem('oc').description,/未绑定/);
 f.setRunning([]);await f.manager.refresh();assert.match(f.manager.provider.getTreeItem('oc').description,/离线/);
});
test('OC 向导通过当前 Assistant 提交 URL + Key，插件不保存 Key，审批状态自动跟随',async t=>{
 const f=fixture(t);await f.manager.ready;f.setRunning([instance]);await f.manager.refresh();
 const key='wbot_'+'a'.repeat(43);
 f.inputs.push('https://oc.example','我的电脑',key);await f.manager.connectOC();
 assert.equal(f.prompts.length,3);assert.equal(f.prompts[2].password,true);
 assert.deepEqual(f.requests.find(item=>item.body)?.body,{server_url:'https://oc.example',device_name:'我的电脑',binding_key:key});
 assert.equal(JSON.stringify([...f.saved]).includes(key),false);
 f.setBinding({server_url:'https://oc.example',binding_state:'pending',verification_code:'123456'});await f.manager.refresh();assert.match(f.manager.provider.getTreeItem('oc').description,/待.*批准/);await assert.rejects(f.manager.requireOC(),/批准/);
 f.setBinding({server_url:'https://oc.example',binding_state:'approved'});await f.manager.refresh();assert.equal((await f.manager.requireOC()).origin,'https://oc.example');assert.match(f.manager.provider.getTreeItem('oc').description,/已绑定/);
});
test('取消绑定向导不改动 Assistant，原绑定重连可留空 Key，断开需明确操作',async t=>{
 const f=fixture(t);await f.manager.ready;f.setRunning([instance]);f.setBinding({server_url:'https://oc.example',device_name:'我的电脑',binding_state:'disconnected',has_binding_credentials:true});await f.manager.refresh();
 f.inputs.push('https://other.example',undefined);await f.manager.connectOC();assert.equal(f.requests.filter(item=>item.body).length,0);
 f.inputs.push('https://oc.example','我的电脑','');await f.manager.connectOC();assert.equal(f.prompts.at(-1).validateInput(''),undefined);assert.equal('binding_key' in f.requests.find(item=>item.body).body,false);
 await f.manager.disconnectOC();assert.equal(f.requests.at(-1).body,null);assert.match(f.manager.provider.getTreeItem('oc').description,/已断开/);
});
test('读取绑定失败时不能把上次已绑定状态当作可用连接',async t=>{
 const f=fixture(t);await f.manager.ready;f.setRunning([instance]);f.setBinding({server_url:'https://oc.example',binding_state:'approved'});await f.manager.refresh();
 f.setFailure();await assert.rejects(f.manager.requireOC(),/暂不可用/);assert.match(f.manager.provider.getTreeItem('oc').description,/无法读取/);
});
test('真实 Assistant 接口接收绑定 Key，插件读取只得到公开状态',async t=>{
 const {startSharedFixture}=require('./shared-fixture');
 const f=await startSharedFixture();t.after(()=>f.close());
 assert.equal((await assistantSettings(f.assistant_dir)).binding_state,'approved');
 const key='wbot_'+'a'.repeat(43);
 const result=await assistantSettings(f.assistant_dir,{server_url:'https://oc.example',device_name:'向导测试',binding_key:key});
 assert.equal(result.binding_state,'connecting');assert.equal(result.server_url,'https://oc.example');assert.equal(JSON.stringify(result).includes(key),false);
 assert.equal((await assistantSettings(f.assistant_dir,null)).binding_state,'disconnected');
});
