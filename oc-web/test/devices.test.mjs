import test from 'node:test';
import assert from 'node:assert/strict';
import { isDeviceAuthorized, isDeviceReady } from '../src/devices.ts';

test('流程保留旧本机设备并允许已批准的远程设备', () => {
  assert.equal(isDeviceAuthorized({ id: 'legacy' }), true);
  assert.equal(isDeviceAuthorized({ transport: 'local', binding_state: 'approved' }), true);
  assert.equal(isDeviceAuthorized({ transport: 'agent', binding_state: 'approved' }), true);
});

test('远程设备缺失审批或被拒绝、撤销时不可用于流程', () => {
  for (const binding_state of [undefined, 'pending', 'rejected', 'revoked', 'unknown']) {
    assert.equal(isDeviceAuthorized({ transport: 'agent', binding_state }), false, String(binding_state));
  }
  assert.equal(isDeviceAuthorized({ transport: 'unknown', binding_state: 'approved' }), false);
  assert.equal(isDeviceAuthorized({ transport: 'local', binding_state: 'revoked' }), false);
});

test('绑定批准不等于可运行，设备还必须在线空闲且未维护', () => {
  const approved = { transport: 'agent', binding_state: 'approved', status: 'online', maintenance: false };
  assert.equal(isDeviceReady(approved), true);
  assert.equal(isDeviceReady({ ...approved, status: 'offline' }), false);
  assert.equal(isDeviceReady({ ...approved, status: 'busy' }), false);
  assert.equal(isDeviceReady({ ...approved, maintenance: true }), false);
  assert.equal(isDeviceReady({ ...approved, binding_state: 'pending' }), false);
  assert.equal(isDeviceReady(undefined), false);
});
