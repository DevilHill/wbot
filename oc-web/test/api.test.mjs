import test from 'node:test';
import assert from 'node:assert/strict';

const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

test('并发读取共用会话请求，业务请求携带 token', async () => {
  const client = await import('../src/api.ts?case=shared');
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return url.endsWith('/session') ? json({ token: 'local-token' }) : json({ jobs: [] });
  };
  try {
    await Promise.all([client.request('/state'), client.request('/state')]);
    assert.equal(calls.filter(call => call.url.endsWith('/session')).length, 1);
    assert.equal(calls[1].options.headers['X-WBot-Token'], 'local-token');
    assert.equal(calls[2].options.headers['X-WBot-Token'], 'local-token');
  } finally { globalThis.fetch = original; }
});

test('会话失效清除旧 token，但不自动重放运行请求', async () => {
  const client = await import('../src/api.ts?case=expired');
  const calls = [];
  let version = 0;
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith('/session')) return json({ token: `token-${++version}` });
    if (url.endsWith('/run')) return json({ error: '会话已失效' }, 403);
    return json({ jobs: [] });
  };
  try {
    await assert.rejects(client.request('/processes/demo/run', { body: { request_id: 'one' } }), /会话已失效/);
    assert.equal(calls.filter(call => call.url.endsWith('/run')).length, 1);
    await client.request('/state');
    assert.equal(version, 2);
    assert.equal(calls.at(-1).options.headers['X-WBot-Token'], 'token-2');
  } finally { globalThis.fetch = original; }
});
