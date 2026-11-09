import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

let server, ElementComparison;
before(async () => {
  server = await createServer({ root: resolve(import.meta.dirname, '..'), configFile: false, server: { middlewareMode: true }, esbuild: { jsx: 'automatic' }, logLevel: 'silent' });
  ({ ElementComparison } = await server.ssrLoadModule('/src/element-comparison.tsx'));
});
after(async () => { await server?.close(); });

const record = { id: 'login', group: '登录页', name: '登录按钮', xpath: '//button[@id="login"]', description: '', url: 'https://example.test/login', frame: null };

test('元素差异按字段展示前后值，XPath和描述按文本转义', () => {
  const markup = renderToStaticMarkup(createElement(ElementComparison, { before: record, after: { ...record, xpath: '//button[@data-role="login"]', description: '<script>alert(1)</script>' } }));
  assert.match(markup, /XPath/);
  assert.match(markup, /data-role/);
  assert.match(markup, /&lt;script&gt;/);
  assert.doesNotMatch(markup, /<script>/);
  assert.doesNotMatch(markup, /example.test/);
});

test('新增与删除元素显示完整记录和明确操作标签', () => {
  const added = renderToStaticMarkup(createElement(ElementComparison, { before: null, after: record }));
  const deleted = renderToStaticMarkup(createElement(ElementComparison, { before: record, after: null }));
  assert.match(added, /新增元素/);
  assert.match(deleted, /删除元素/);
  assert.match(added, /登录按钮/);
  assert.match(deleted, /登录按钮/);
});
