'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {nextActions, createSharedView} = require('../src/shared-view');
const {editElementDraft} = require('../src/element-input');
test('共享操作随工作副本状态变化，异常与待确认不引导写入', () => {
  assert.deepEqual(nextActions({}), ['connectSharedElements']);
  assert.deepEqual(nextActions({binding:{}, dirty:true}), ['sharedElementChanges','commitSharedElements']);
  assert.deepEqual(nextActions({binding:{}, dirty:false, request:{state:'open'}}), []);
  assert.deepEqual(nextActions({binding:{}, dirty:false}), ['requestElementMerge']);
  assert.deepEqual(nextActions({binding:{}, branch_status:'merged', dirty:true}), ['connectSharedElements']);
  assert.deepEqual(nextActions({binding:{}, branch_status:'merged'}), ['pullSharedElements','connectSharedElements']);
  assert.deepEqual(nextActions({binding:{}, remote_error:'离线'}), []);
  assert.deepEqual(nextActions({binding:{}, pending_action:'commit'}), []);
});

test('元素表单转义输入，校验字段且只保存当前面板的消息', async () => {
  const {editorHTML, validateDraft} = require('../src/element-input');
  assert.ok(!editorHTML('nonce',{name:'<script>bad</script>'}).includes('value="<script>'));
  assert.throws(()=>validateDraft({name:'',group:'g',xpath:'//x',url:'',description:''}),/不能为空/);
  let receive, dispose, html, writes=0;
  const panel={webview:{set html(value){html=value;},onDidReceiveMessage(fn){receive=fn;return {dispose(){}};},postMessage:async()=>{}},onDidDispose(fn){dispose=fn;return {dispose(){}};},dispose(){dispose();}};
  const vscode={ViewColumn:{Active:1},window:{createWebviewPanel:()=>panel}};
  const pending=editElementDraft(vscode,{id:'trusted'},async record=>{writes++;return record;});
  const nonce=html.match(/script-src 'nonce-([a-f0-9]+)'/)[1];
  const fields={name:'name',group:'g',xpath:'//input',url:'',description:''};
  await receive({action:'save',session:'stale',fields});assert.equal(writes,0);
  await receive({action:'save',session:nonce,fields:{...fields,id:'forged'}});assert.equal(writes,0);
  await receive({action:'save',session:nonce,fields});assert.equal(writes,1);
  assert.equal((await pending).id,'trusted');
});

test('切换连接后丢弃旧响应，销毁侧栏后不再更新界面', async () => {
  let resolveStatus;
  const context = {subscriptions:[]};
  const view = {visible:false, onDidChangeVisibility:()=>({dispose(){}}), dispose(){}};
  const vscode = {EventEmitter:class {constructor(){this.event=()=>{};} fire(){} dispose(){}},
    window:{createTreeView:()=>view}};
  const shared = createSharedView(vscode, context, ()=>new Promise(resolve=>{resolveStatus=resolve;}));
  try {
    const pending = shared.refresh();
    shared.invalidate();
    resolveStatus({binding:{repository_name:'旧服务器'}, changes:[]});
    await pending;
    assert.deepEqual(shared.provider.getChildren(), []);
    const second = shared.refresh();
    context.subscriptions.forEach(item=>item.dispose());
    const message = view.message;
    resolveStatus({binding:{repository_name:'已关闭'}, changes:[]});
    await second;
    assert.equal(view.message, message);
  } finally { context.subscriptions.forEach(item=>item.dispose()); }
});
