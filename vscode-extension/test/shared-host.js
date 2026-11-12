'use strict';
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');
const {requestAssistant} = require('../src/assistant-client');
const {configureLegacy}=require('./host-settings');
const {startSharedFixture} = require('./shared-fixture');

async function verifySharedElementsHost(vscode, check) {
  const fixture = await startSharedFixture();
  const configuration = vscode.workspace.getConfiguration('wbot');
  const previousLibrary = configuration.get('libraryPath');
  const previousAssistant = configuration.get('assistantStateDir');
  try {
    await configureLegacy(vscode,{libraryPath:fixture.library_path,assistantStateDir:fixture.assistant_dir});
    const initial = await requestAssistant(fixture.assistant_dir, 'status', {library_path:fixture.library_path});
    await requestAssistant(fixture.assistant_dir, 'connect', {library_path:fixture.library_path,
      repository_id:fixture.repository_id, branch_name:'host-diff', expected_fingerprint:initial.fingerprint,
      expected_branch:null, expected_head:null, request_id:randomUUID()});
    await fixture.command('edit', {xpath:'//input[@id="host-search"]'});
    const difference = await vscode.commands.executeCommand('wbot.sharedElementChanges', 'search');
    assert.equal(difference.changes.length, 1);
    const documents = vscode.workspace.textDocuments.filter(document => document.uri.scheme === 'wbot-shared-elements');
    const snapshots = documents.map(document => JSON.parse(document.getText()));
    assert.ok(snapshots.some(items => Array.isArray(items) && items[0]?.xpath === '//input'));
    assert.ok(snapshots.some(items => Array.isArray(items) && items[0]?.xpath === '//input[@id="host-search"]'));
    assert.ok(vscode.window.tabGroups.all.some(group => group.tabs.some(tab =>
      tab.input?.original?.scheme === 'wbot-shared-elements' && tab.input?.modified?.scheme === 'wbot-shared-elements')));
    const status = await vscode.commands.executeCommand('wbot.sharedElementStatus');
    assert.equal(status.dirty, true);
    assert.equal(status.binding.repository_id, fixture.repository_id);
    const extension = vscode.extensions.getExtension(require('../package.json').publisher+'.'+require('../package.json').name);
    await extension.exports.sharedView.refresh();
    const rows = extension.exports.sharedView.provider.getChildren();
    assert.ok(rows.some(row => row.changeId === 'search'));
    const item = extension.exports.sharedView.provider.getTreeItem(rows.find(row => row.changeId === 'search'));
    assert.equal(item.command.command, 'wbot.sharedElementChanges');
    check('原生共享侧栏呈现真实变更，元素行连接原生差异命令');
    check('共享元素真实 Assistant 通信、命令注册、原生只读差异与状态文档');
  } finally {
    await configureLegacy(vscode,{libraryPath:previousLibrary,assistantStateDir:previousAssistant});
    await fixture.close();
  }
}

module.exports = {verifySharedElementsHost};
