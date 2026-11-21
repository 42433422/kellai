import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const compiled = await build({
  entryPoints: ['src/api/flowDraft.ts'], bundle: true, write: false, format: 'esm', platform: 'node',
});
const { toDraftNodes, fromDraftNodes } = await import(
  'data:text/javascript;base64,' + Buffer.from(compiled.outputFiles[0].text).toString('base64')
);

test('reordering and dragging preserve node types, labels, and nested business configuration', () => {
  const definitions = [
    { id: 'acquire-one', type: 'acquire', label: '客户入站', config: { channel: 'chatwoot', nested: { ids: [1, 2] } }, position: { x: 1, y: 2 } },
    { id: 'webhook-two', type: 'webhook', label: '回调草稿', config: { events: ['message.created'], enabled: false }, position: { x: 100, y: 150 } },
  ];
  const nodes = toDraftNodes(definitions).reverse();
  nodes[0].position = { x: 400, y: 500 };
  const saved = fromDraftNodes(nodes);
  assert.deepEqual(saved[0], { ...definitions[1], position: { x: 400, y: 500 } });
  assert.deepEqual(saved[1], definitions[0]);
});

test('editing a canvas draft does not mutate cached server definitions', () => {
  const original = { id: 'reply', type: 'communicate', label: '回复', config: { policy: { approvals: ['owner'] } }, position: { x: 0, y: 0 } };
  const nodes = toDraftNodes([original]);
  nodes[0].data.draft.config.policy.approvals.push('admin');
  const saved = fromDraftNodes(nodes);
  saved[0].config.policy.approvals.push('sales');
  assert.deepEqual(original.config.policy.approvals, ['owner']);
  assert.deepEqual(nodes[0].data.draft.config.policy.approvals, ['owner', 'admin']);
});
