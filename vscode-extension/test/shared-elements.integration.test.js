'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');
const {requestAssistant} = require('../src/assistant-client');
const {createSharedElementCommands} = require('../src/shared-elements');
const {startSharedFixture} = require('./shared-fixture');

test('真实 VSCode 客户端经 Assistant 完成分支提交、管理端合并和拉取', {timeout:30000}, async t => {
  const active = await startSharedFixture();
  t.after(active.close);
  const catalog = await requestAssistant(active.assistant_dir, 'repositories');
  assert.equal(catalog.items[0].id, active.repository_id);
  const documents = new Map();
  const vscode = {
    window:{
      showInputBox:async options => ({'创建个人元素分支':'fix-search', '提交共享元素版本':'修复搜索框 XPath',
        '元素合并申请标题':'共享搜索框修复', '合并说明':'真实客户端联调'})[options.title],
      showQuickPick:async items => items[0],
      showInformationMessage:async (_message, ...actions) => actions.at(-1),
      withProgress:async (_options, callback) => callback(),
      showTextDocument:async document => document
    },
    workspace:{
      registerTextDocumentContentProvider:(_scheme, provider) => { documents.set('provider', provider); return {dispose(){}}; },
      onDidCloseTextDocument:() => ({dispose(){}}), openTextDocument:async uri => ({uri})
    },
    Uri:{parse:value => ({toString:() => value})},
    commands:{executeCommand:async (...args) => { documents.set('command', args); }},
    ProgressLocation:{Notification:15}
  };
  const commands = createSharedElementCommands({vscode, context:{subscriptions:[]},
    settings:() => ({libraryPath:active.library_path, assistantStateDir:active.assistant_dir}), refresh:async () => {}});
  const connected = await commands.connectSharedElements();
  assert.equal(connected.dirty, false);
  assert.equal((await active.command('items'))[0].xpath, '//input');
  await active.command('edit', {xpath:'//input[@id="search"]'});
  const difference = await commands.sharedElementChanges();
  assert.equal(difference.changes.length, 1);
  const [, before, after] = documents.get('command');
  const provider = documents.get('provider');
  assert.equal(JSON.parse(provider.provideTextDocumentContent(before))[0].xpath, '//input');
  assert.equal(JSON.parse(provider.provideTextDocumentContent(after))[0].xpath, '//input[@id="search"]');
  const committed = await commands.commitSharedElements();
  assert.equal(committed.dirty, false);
  const proposed = await commands.requestElementMerge();
  assert.equal(proposed.request.state, 'open');
  await assert.rejects(commands.pullSharedElements(), /尚未合并/);
  const session = await (await fetch(active.admin_url + '/api/oc/session')).json();
  const endpoint = active.admin_url + '/api/oc/elements/repositories/' + active.repository_id + '/requests/' + proposed.request.id;
  const reviewResponse = await fetch(endpoint, {headers:{'X-WBot-Token':session.token}});
  assert.equal(reviewResponse.status, 200);
  const review = await reviewResponse.json();
  assert.equal(review.conflicts.length, 0);
  const merged = await fetch(endpoint + '/merge', {method:'POST',
    headers:{'X-WBot-Token':session.token, 'Content-Type':'application/json'},
    body:JSON.stringify({expected_main:review.main_head, expected_source:review.source_head,
      resolutions:[], request_id:randomUUID()})});
  assert.equal(merged.status, 200, await merged.text());
  const pulled = await commands.pullSharedElements();
  assert.equal(pulled.branch_status, 'merged');
  assert.equal(pulled.dirty, false);
  assert.equal((await active.command('items'))[0].xpath, '//input[@id="search"]');
  const observed = await commands.sharedElementStatus();
  assert.equal(observed.request.state, 'merged');
});
