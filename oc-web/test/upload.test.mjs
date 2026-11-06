import test from 'node:test';
import assert from 'node:assert/strict';
import { snapshotUploadFile, MAX_UPLOAD_BYTES } from '../src/upload.ts';

test('选择时复制文件字节，提交副本不再依赖原文件读取', async () => {
  const bytes = Uint8Array.from([80, 75, 3, 4, 0, 255, 128, 10]);
  const selected = new File([bytes], '示例.wbot.zip', { type: 'application/zip', lastModified: 123456 });
  const snapshot = await snapshotUploadFile(selected);
  Object.defineProperty(selected, 'arrayBuffer', { value: () => { throw new Error('临时文件已失效'); } });
  assert.notEqual(snapshot, selected);
  assert.deepEqual(new Uint8Array(await snapshot.arrayBuffer()), bytes);
  assert.equal(snapshot.name, selected.name);
  assert.equal(snapshot.type, selected.type);
  assert.equal(snapshot.lastModified, selected.lastModified);
});

test('本地读取失败明确提示重新选择', async () => {
  const selected = new File(['unavailable'], 'demo.zip');
  Object.defineProperty(selected, 'arrayBuffer', { value: async () => { throw new Error('backing file disappeared'); } });
  await assert.rejects(snapshotUploadFile(selected), { message: '无法读取所选文件，请重新选择' });
});

test('超限文件在读取前拒绝', async () => {
  const selected = new File([], 'too-large.zip');
  let read = false;
  Object.defineProperty(selected, 'size', { value: MAX_UPLOAD_BYTES + 1 });
  Object.defineProperty(selected, 'arrayBuffer', { value: async () => { read = true; return new ArrayBuffer(0); } });
  await assert.rejects(snapshotUploadFile(selected), /不能超过 68 MiB/);
  assert.equal(read, false);
});
