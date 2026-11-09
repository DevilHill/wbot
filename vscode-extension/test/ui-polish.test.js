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

test('原生元素输入返回上一步保留草稿，取消不产生保存结果', async () => {
  const seen = [], events = [['accept','first'], ['back','财务'], ['accept','改名'], ['accept','财务'], ['accept','//input'], ['accept',''], ['accept','备注']];
  let disposed = 0;
  const vscode = {QuickInputButtons:{Back:{}}, window:{
    createInputBox() {
      const handlers = {};
      const input = {onDidAccept(fn) { handlers.accept=fn; return {dispose(){}}; }, onDidHide(fn) {handlers.hide=fn; return {dispose(){}};},
        onDidTriggerButton(fn) {handlers.back=fn; return {dispose(){}};}, dispose(){disposed++;},
        show() { seen.push({step:this.step,value:this.value}); const [event,value] = events.shift(); this.value=value; queueMicrotask(()=>handlers[event]()); }};
      return input;
    }, showInformationMessage:async ()=>'保存'
  }};
  const draft = await editElementDraft(vscode, {id:'one', xpath:'//old'});
  assert.equal(draft.name, '改名');
  assert.equal(draft.group, '财务');
  assert.deepEqual(seen[2], {step:1,value:'first'});
  assert.deepEqual(seen[3], {step:2,value:'财务'});
  assert.equal(disposed, 7);
  events.push(['hide','']);
  assert.equal(await editElementDraft(vscode, draft), undefined);
  assert.equal(disposed, 8);
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
