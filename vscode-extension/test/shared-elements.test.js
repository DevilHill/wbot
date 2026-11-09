'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {createSharedElementCommands} = require('../src/shared-elements');

const binding = {server_url:'http://oc.test:8793', device_id:'device1', repository_id:'repo1',
  repository_name:'采购门户', branch_id:'branch1', branch_name:'fix-search', head:'commit1', base_commit:'base1'};
const status = (extra = {}) => ({binding, dirty:false, changes:[], fingerprint:'digest1', branch_status:'open', request:null, remote_error:'', ...extra});

function setup(handler, choices = {}) {
  const calls = [], messages = [], documents = new Map(), disposables = [];
  const vscode = {
    window:{
      showInputBox:async options => choices.input === undefined ? options.title.includes('分支') ? 'fix-search' : '修复搜索框 XPath' : choices.input,
      showQuickPick:async items => choices.pick === null ? undefined : items[choices.pick || 0],
      showInformationMessage:async (message, ...actions) => { messages.push(message); return choices.confirm === false ? undefined : actions.at(-1); },
      withProgress:async (_options, callback) => callback(),
      showTextDocument:async document => document
    },
    workspace:{
      registerTextDocumentContentProvider:(_scheme, provider) => { documents.set('provider', provider); return {dispose(){}}; },
      onDidCloseTextDocument:() => ({dispose(){}}),
      openTextDocument:async uri => ({uri})
    },
    Uri:{parse:value => ({toString:() => value})},
    commands:{executeCommand:async (...args) => { documents.set('command', args); }},
    ProgressLocation:{Notification:15}
  };
  const commands = createSharedElementCommands({vscode, context:{subscriptions:disposables},
    settings:() => ({libraryPath:path.resolve('elements.sqlite3'), assistantStateDir:path.resolve('assistant-state')}),
    refresh:async () => { calls.push({action:'refresh'}); },
    request:async (directory, action, body) => { calls.push({directory, action, body}); return handler(action, body); }});
  return {commands, calls, messages, documents};
}

test('取消选择仓库不会创建分支或改写元素', async () => {
  const {commands, calls} = setup(action => action === 'repositories' ? {items:[{id:'repo1', name:'采购门户'}]} : status(), {pick:null});
  await commands.connectSharedElements();
  assert.equal(calls.some(call => call.action === 'connect' || call.action === 'refresh'), false);
});

test('已合并分支可将本地修改带到同仓库新分支，其他切换仍受保护', async () => {
  const current = status({dirty:true, branch_status:'merged', changes:[{type:'modified'}]});
  const allowed = setup(action => action === 'repositories' ? {items:[{id:'repo1', name:'采购门户'}]} : current);
  await allowed.commands.connectSharedElements();
  const sent = allowed.calls.find(call => call.action === 'connect').body;
  assert.equal(sent.repository_id, 'repo1');
  assert.equal(sent.expected_fingerprint, 'digest1');
  for (const [repositoryId, state] of [['repo2', current], ['repo1', status({dirty:true})],
                                     ['repo1', {...current, remote_error:'连接中断'}]]) {
    const denied = setup(action => action === 'repositories' ? {items:[{id:repositoryId, name:'仓库'}]} : state);
    await assert.rejects(denied.commands.connectSharedElements(), /未提交/);
    assert.equal(denied.calls.some(call => call.action === 'connect'), false);
  }
});

test('提交携带审阅时的本地指纹与分支头，取消输入不提交', async () => {
  const current = status({dirty:true, changes:[{id:'search', type:'modified'}]});
  const accepted = setup(action => action === 'status' ? current : {commit:{id:'new-commit'}});
  await accepted.commands.commitSharedElements();
  const sent = accepted.calls.find(call => call.action === 'commit').body;
  assert.equal(sent.expected_fingerprint, 'digest1');
  assert.equal(sent.expected_branch, 'branch1');
  assert.equal(sent.expected_head, 'commit1');
  assert.equal(sent.message, '修复搜索框 XPath');
  assert.match(sent.request_id, /^[0-9a-f-]{36}$/);
  const cancelled = setup(() => current, {input:null});
  await cancelled.commands.commitSharedElements();
  assert.equal(cancelled.calls.some(call => call.action === 'commit'), false);
});

test('响应丢失后原提交复用request_id，不自动重复发送', async () => {
  let attempts = 0;
  const {commands, calls} = setup(action => {
    if (action === 'status') return status({dirty:true, changes:[{type:'modified'}]});
    if (action === 'commit' && ++attempts === 1) throw new Error('响应丢失');
    return {commit:{id:'accepted'}};
  });
  await assert.rejects(commands.commitSharedElements(), /响应丢失/);
  assert.equal(attempts, 1);
  await commands.commitSharedElements();
  const writes = calls.filter(call => call.action === 'commit');
  assert.equal(writes[0].body.request_id, writes[1].body.request_id);
  assert.equal(attempts, 2);
});

test('有本地修改或未合并分支时不发送拉取操作', async () => {
  for (const current of [status({dirty:true, branch_status:'merged'}), status()]) {
    const {commands, calls} = setup(() => current);
    await assert.rejects(commands.pullSharedElements(), /未提交|合并/);
    assert.equal(calls.some(call => call.action === 'pull'), false);
  }
});

test('已合并分支的拉取经确认且携带同一版本约束', async () => {
  const {commands, calls, messages} = setup(action => action === 'status' ? status({branch_status:'merged'}) : status({branch_status:'merged'}));
  await commands.pullSharedElements();
  const sent = calls.find(call => call.action === 'pull').body;
  assert.equal(sent.expected_fingerprint, 'digest1');
  assert.equal(sent.expected_head, 'commit1');
  assert.equal(calls.at(-1).action, 'refresh');
  assert.ok(messages.some(message => message.includes('新的个人分支')));
});

test('本地有改动时不能发起MR，已有打开的MR提示继续提交更新', async () => {
  const dirty = setup(() => status({dirty:true}));
  await assert.rejects(dirty.commands.requestElementMerge(), /先提交/);
  assert.equal(dirty.calls.some(call => call.action === 'request'), false);
  const open = setup(() => status({request:{id:'mr1', title:'修复搜索框', state:'open'}}));
  await open.commands.requestElementMerge();
  assert.equal(open.calls.some(call => call.action === 'request'), false);
  assert.ok(open.messages.some(message => message.includes('后续提交')));
});

test('差异在原生只读编辑器呈现，不写入本地元素文件', async () => {
  const before = [{id:'search', name:'搜索', group:'首页', xpath:'//input'}];
  const after = [{...before[0], xpath:'//input[@id="search"]'}];
  const {commands, documents} = setup(action => action === 'status' ? status({dirty:true}) : {before, after, changes:[{type:'modified'}]});
  await commands.sharedElementChanges();
  const [command, left, right] = documents.get('command');
  assert.equal(command, 'vscode.diff');
  const provider = documents.get('provider');
  assert.equal(JSON.parse(provider.provideTextDocumentContent(left))[0].xpath, before[0].xpath);
  assert.equal(JSON.parse(provider.provideTextDocumentContent(right))[0].xpath, after[0].xpath);
});
