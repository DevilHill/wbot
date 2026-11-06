import test from 'node:test';
import assert from 'node:assert/strict';

const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

test('设备批准、拒绝和撤销使用管理会话 POST，不发送设备凭据', async () => {
  const client = await import('../src/api.ts?case=device-actions');
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return url.endsWith('/session') ? json({ token: 'management-session' }) : json({ device: { id: 'agent/one' } });
  };
  try {
    for (const action of ['approve', 'reject', 'revoke']) await client.changeDeviceBinding('agent/one', action);
    const mutations = calls.filter(call => !call.url.endsWith('/session'));
    assert.deepEqual(mutations.map(call => call.url), ['approve', 'reject', 'revoke'].map(action => `/api/oc/devices/agent%2Fone/${action}`));
    for (const { options } of mutations) {
      assert.equal(options.method, 'POST');
      assert.equal(options.headers['X-WBot-Token'], 'management-session');
      assert.equal(options.body, '{}');
    }
  } finally { globalThis.fetch = original; }
});

test('审批失败保留服务错误，不自动重放授权操作', async () => {
  const client = await import('../src/api.ts?case=device-conflict');
  let approvals = 0;
  const original = globalThis.fetch;
  globalThis.fetch = async url => {
    if (url.endsWith('/session')) return json({ token: 'management-session' });
    approvals += 1;
    return json({ error: '设备状态已变化，请刷新后重试' }, 409);
  };
  try {
    await assert.rejects(client.changeDeviceBinding('agent-one', 'approve'), /设备状态已变化/);
    assert.equal(approvals, 1);
  } finally { globalThis.fetch = original; }
});
