import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

let server, Devices, ProcessDialog, RunDialog, IdentityContext;
before(async () => {
  server = await createServer({ root: resolve(import.meta.dirname, '..'), configFile: false, server: { middlewareMode: true }, esbuild: { jsx: 'automatic' }, logLevel: 'silent' });
  ({ Devices } = await server.ssrLoadModule('/src/device-page.tsx'));
  ({ ProcessDialog, RunDialog } = await server.ssrLoadModule('/src/forms.tsx'));
  ({ IdentityContext } = await server.ssrLoadModule('/src/permissions.tsx'));
});
after(async () => { await server?.close(); });

const device = (id, binding_state) => ({ id, name: id, transport: 'agent', binding_state, status: 'online', maintenance: false, active_jobs: 0, last_seen: 1, created_at: 1, error: '', verification_code: '123456' });
const packageItem = { id: 'report@1.0', manifest: { name: 'report', version: '1.0', parameters: {} } };
const snapshot = () => ({ packages: [packageItem], processes: [], jobs: [], devices: [device('pending-device', 'pending'), device('approved-device', 'approved'), device('revoked-device', 'revoked'), { ...device('legacy-local', undefined), transport: undefined }] });
const actions = { pendingAction: null, addDevice() {}, toggleMaintenance() {}, async deviceBindingChanged() {} };

test('设备页展示审批核验与绑定状态，不渲染设备凭据', () => {
  const state = snapshot();
  state.devices[0].device_secret = 'secret-must-never-be-rendered';
  state.devices[1].maintenance = true;
  state.devices[1].status = 'offline';
  const markup = renderToStaticMarkup(createElement(IdentityContext.Provider, { value: { mode: 'account', permissions: ['read', 'robots.manage'] } }, createElement(Devices, { snapshot: state, actions, session: { agent_gateway: { host: '0.0.0.0', port: 8793, url: 'http://0.0.0.0:8793', public_host_required: true } } })));
  assert.match(markup, /123456/);
  assert.match(markup, /批准 pending-device 绑定/);
  assert.match(markup, /拒绝 pending-device 绑定/);
  assert.match(markup, /撤销绑定/);
  assert.match(markup, /已撤销/);
  assert.match(markup, /本机目录接入 · local/);
  assert.match(markup, /最近心跳/);
  assert.match(markup, /status-offline/);
  assert.match(markup, /维护模式/);
  assert.match(markup, /已开启/);
  assert.match(markup, /这台 OC 电脑可访问的 IP 或域名/);
  assert.doesNotMatch(markup, /secret-must-never-be-rendered/);
  assert.doesNotMatch(markup, /href="http:\/\/0\.0\.0\.0/);
});

test('只读角色可查看设备状态，但不显示审批和维护操作', () => {
  const markup = renderToStaticMarkup(createElement(IdentityContext.Provider, { value: { mode: 'account', permissions: ['read'] } }, createElement(Devices, { snapshot: snapshot(), actions })));
  assert.match(markup, /pending-device/);
  assert.doesNotMatch(markup, /批准 pending-device 绑定|拒绝 pending-device 绑定|设为维护|撤销绑定<\/button>/);
});

test('部署表单只提供已批准远程设备与旧本机设备', () => {
  const markup = renderToStaticMarkup(createElement(ProcessDialog, { snapshot: snapshot(), onClose() {}, onSaved() {} }));
  assert.match(markup, /option value="approved-device"/);
  assert.match(markup, /option value="legacy-local"/);
  assert.doesNotMatch(markup, /option value="pending-device"/);
  assert.doesNotMatch(markup, /option value="revoked-device"/);
});

test('已有流程的设备被撤销后，部署和运行表单禁用提交', () => {
  const process = { id: 'process-one', name: '每日任务', device_id: 'revoked-device', package_id: packageItem.id, defaults: {}, enabled: true };
  for (const Component of [ProcessDialog, RunDialog]) {
    const markup = renderToStaticMarkup(createElement(Component, { process, snapshot: snapshot(), onClose() {}, onSaved() {}, onStarted() {} }));
    assert.match(markup, /type="submit" disabled=""/);
  }
});
