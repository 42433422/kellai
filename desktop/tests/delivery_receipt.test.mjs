import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

const bundle = await build({
  entryPoints: [fileURLToPath(new URL('../src/types.ts', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false,
});
const module = { exports: {} };
new Function('module', 'exports', bundle.outputFiles[0].text)(module, module.exports);
const { receiptState, receiptLabel } = module.exports;
const receipt = (status, provider_state) => ({ request_id: 'original', connection_id: 'account-a', status, provider_state });

test('accepted requests display later delivery and read evidence', () => {
  assert.equal(receiptLabel(receiptState(receipt('accepted', 'delivered'))), '已送达');
  assert.equal(receiptLabel(receiptState(receipt('accepted', 'read'))), '已读');
});

test('platform acceptance alone never becomes confirmed delivery', () => {
  assert.equal(receiptLabel(receiptState(receipt('accepted', 'accepted'))), '平台已受理');
  assert.equal(receiptLabel(receiptState(receipt('accepted', undefined))), '平台已受理');
});

test('uncertain or failed attempts cannot be promoted by stale platform fields', () => {
  assert.equal(receiptLabel(receiptState(receipt('unknown', 'read'))), '结果待核验，请查询原请求');
  assert.equal(receiptLabel(receiptState(receipt('failed', 'delivered'))), '发送失败');
});
