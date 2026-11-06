import test from 'node:test';
import assert from 'node:assert/strict';
import { initialParameterValues, parseParameterValues } from '../src/parameters.ts';

test('运行参数优先使用流程默认值，保留 false、零和空字符串', () => {
  const definitions = { name: { type: 'string', default: '原值' }, count: { type: 'integer', default: 3 }, ready: { type: 'boolean', default: true } };
  assert.deepEqual(initialParameterValues(definitions, { name: '', count: 0, ready: false }), { name: '', count: '0', ready: 'false' });
});
test('区分省略布尔参数和明确 false，空数值不自动变零', () => {
  const definitions = { ready: { type: 'boolean' }, count: { type: 'integer' }, label: { type: 'string' } };
  assert.deepEqual(parseParameterValues(definitions, { ready: '', count: '', label: '' }), { label: '' });
  assert.deepEqual(parseParameterValues(definitions, { ready: 'false', count: '0', label: '' }), { ready: false, count: 0, label: '' });
});
test('必填、整数和有限数值校验', () => {
  assert.throws(() => parseParameterValues({ value: { type: 'integer', required: true } }, { value: '' }), /value/);
  assert.throws(() => parseParameterValues({ value: { type: 'integer' } }, { value: '1.5' }), /整数/);
  assert.throws(() => parseParameterValues({ value: { type: 'number' } }, { value: 'Infinity' }), /有限/);
});
