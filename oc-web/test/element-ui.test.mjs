import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

let server, ElementConflicts, ElementRequests, ElementHistory;
before(async () => {
  server = await createServer({ root: resolve(import.meta.dirname, '..'), configFile: false, server: { middlewareMode: true }, esbuild: { jsx: 'automatic' }, logLevel: 'silent' });
  ({ ElementConflicts } = await server.ssrLoadModule('/src/element-merge-dialog.tsx'));
  ({ ElementRequests, ElementHistory } = await server.ssrLoadModule('/src/element-page.tsx'));
});
after(async () => { await server?.close(); });

test('冲突界面默认不替用户选择，整元素 null 明确显示删除', () => {
  const markup = renderToStaticMarkup(createElement(ElementConflicts, {
    conflicts: [{ id: 'removed', field: '__record__', base: { id: 'removed' }, main: null, source: { id: 'removed', xpath: '//button' } }],
    choices: {}, onChoose() {}, disabled: true,
  }));
  assert.match(markup, /保留主分支/);
  assert.match(markup, /采用申请版本/);
  assert.match(markup, /删除这个元素/);
  assert.match(markup, /fieldset disabled=""/);
  assert.doesNotMatch(markup, /checked=""/);
});

test('申请列表默认展示待合并项，已关闭与已合并记录不冒充待处理', () => {
  const request = (id, state) => ({ id, state, title: id, branch_name: 'feature', device_name: '设备 A', updated_at: 1 });
  const markup = renderToStaticMarkup(createElement(ElementRequests, {
    items: [request('pending-item', 'open'), request('closed-item', 'closed'), request('merged-item', 'merged')], onReview() {},
  }));
  assert.match(markup, /pending-item/);
  assert.doesNotMatch(markup, /closed-item|merged-item/);
  assert.match(markup, /审阅变更/);
});

test('历史区区分开发分支快照与受保护主分支提交', () => {
  const markup = renderToStaticMarkup(createElement(ElementHistory, { detail: {
    repository: { head: 'main-head' },
    branches: [{ id: 'branch-one', name: 'selector-fix', device_name: '设备 B', updated_at: 1, status: 'merged', head: 'source-head' }],
    commits: [{ id: 'main-head', message: '合并定位修复', author: { name: '管理端', kind: 'admin' }, created_at: 1 },
      { id: 'source-head', message: '修复 XPath', author: { name: '设备 B', kind: 'device' }, created_at: 1 }],
  }, onCommit() {} }));
  assert.match(markup, /selector-fix/);
  assert.match(markup, /已合并/);
  assert.match(markup, /查看快照/);
  assert.match(markup, /element-head-label">main/);
  assert.match(markup, /开发设备/);
});
