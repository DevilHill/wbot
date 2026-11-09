import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { createServer } from 'vite';

let server, reviewHelpers, client;
before(async () => {
  server = await createServer({ root: resolve(import.meta.dirname, '..'), configFile: false, server: { middlewareMode: true }, esbuild: { jsx: 'automatic' }, logLevel: 'silent' });
  reviewHelpers = await server.ssrLoadModule('/src/element-review.ts');
  client = await server.ssrLoadModule('/src/element-api.ts');
});
after(async () => { await server?.close(); });

test('没有逐项选择冲突结果时不允许合并，删除选择保留 null', () => {
  const { canMergeElements, reviewedResolutions, conflictKey } = reviewHelpers;
  const review = { request: { state: 'open' }, conflicts: [
    { id: 'login', field: 'xpath', main: '//button', source: '//a' },
    { id: 'deleted', field: '__record__', main: null, source: { id: 'deleted' } },
  ] };
  const choices = { [conflictKey('login', 'xpath')]: 'source' };
  assert.equal(canMergeElements(review, choices), false);
  assert.throws(() => reviewedResolutions(review, choices), /全部冲突/);
  choices[conflictKey('deleted', '__record__')] = 'main';
  assert.equal(canMergeElements(review, choices), true);
  assert.deepEqual(reviewedResolutions(review, choices), [
    { id: 'login', field: 'xpath', value: '//a' }, { id: 'deleted', field: '__record__', value: null },
  ]);
  assert.equal(canMergeElements({ ...review, request: { state: 'merged' } }, choices), false);
});

test('相同审阅内容重试复用请求号，版本或冲突选择变化生成新意图', () => {
  const { intentFor } = reviewHelpers;
  const original = { expected_main: 'm1', expected_source: 's1', resolutions: [] };
  const first = intentFor(null, original);
  assert.equal(intentFor(first, { ...original }).id, first.id);
  assert.notEqual(intentFor(first, { ...original, expected_main: 'm2' }).id, first.id);
  assert.notEqual(intentFor(first, { ...original, resolutions: [{ id: 'one', field: 'xpath', value: '//a' }] }).id, first.id);
});

test('管理端合并、关闭和恢复发送审阅时的版本及幂等标识', async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify(url.endsWith('/session') ? { token: 'management' } : {}), { headers: { 'Content-Type': 'application/json' } });
  };
  try {
    const merge = { expected_main: 'main-reviewed', expected_source: 'source-reviewed', resolutions: [], request_id: 'merge-once' };
    const close = { expected_source: 'source-reviewed', reason: '需要重新验证 XPath', request_id: 'close-once' };
    const restore = { expected_head: 'current-main', commit_id: 'old-revision', message: '恢复登录页定位', request_id: 'restore-once' };
    await client.mergeElements('repo/one', 'request/one', merge);
    await client.closeElementRequest('repo/one', 'request/one', close);
    await client.restoreElements('repo/one', restore);
    const mutations = calls.filter(call => !call.url.endsWith('/session'));
    assert.deepEqual(mutations.map(call => call.url), [
      '/api/oc/elements/repositories/repo%2Fone/requests/request%2Fone/merge',
      '/api/oc/elements/repositories/repo%2Fone/requests/request%2Fone/close',
      '/api/oc/elements/repositories/repo%2Fone/restore',
    ]);
    assert.deepEqual(mutations.map(call => JSON.parse(call.options.body)), [merge, close, restore]);
    for (const call of mutations) {
      assert.equal(call.options.method, 'POST');
      assert.equal(call.options.headers['X-WBot-Token'], 'management');
    }
  } finally { globalThis.fetch = original; }
});
