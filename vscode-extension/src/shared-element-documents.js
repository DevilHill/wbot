'use strict';
const {randomUUID} = require('node:crypto');

function createSharedElementDocuments(vscode, context) {
  const contents = new Map();
  context.subscriptions.push(vscode.workspace.registerTextDocumentContentProvider('wbot-shared-elements', {
    provideTextDocumentContent:uri => contents.get(uri.toString()) || ''
  }), vscode.workspace.onDidCloseTextDocument(document => contents.delete(document.uri.toString())),
  {dispose:() => contents.clear()});

  function document(name, value) {
    const uri = vscode.Uri.parse(`wbot-shared-elements:/${randomUUID()}/${name}.json`);
    contents.set(uri.toString(), JSON.stringify(value, null, 2) + '\n');
    return uri;
  }

  function sorted(items) {
    return [...items].sort((a, b) => `${a.group}\0${a.name}\0${a.id}`.localeCompare(`${b.group}\0${b.name}\0${b.id}`));
  }

  return {
    async diff(before, after, title) {
      const left = document('提交版本', sorted(before)), right = document('本地修改', sorted(after));
      try { await vscode.commands.executeCommand('vscode.diff', left, right, title, {preview:true}); }
      catch (error) { contents.delete(left.toString()); contents.delete(right.toString()); throw error; }
    },
    async status(value, title = '共享元素状态') {
      const uri = document(title, value);
      try { await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(uri), {preview:true}); }
      catch (error) { contents.delete(uri.toString()); throw error; }
    }
  };
}

module.exports = {createSharedElementDocuments};
