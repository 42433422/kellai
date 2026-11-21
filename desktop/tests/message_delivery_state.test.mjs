import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import test, { beforeEach } from 'node:test';
import { build } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

// Bundle the actual product API with only the network/native transport replaced.
// No browser, provider account, native app or new test dependency is required.
const transportPlugin = { name: 'test-transports', setup(builder) {
    builder.onResolve({ filter: /^(?:\.\/client|\.\.\/api\/client)$/ }, () => ({ path: 'client', namespace: 'transport' }));
    builder.onResolve({ filter: /^@tauri-apps\/api\/core$/ }, () => ({ path: 'native', namespace: 'transport' }));
    builder.onLoad({ filter: /.*/, namespace: 'transport' }, ({ path }) => ({ contents: path === 'client'
      ? `export const currentAccountKey = () => globalThis.__deliveryHarness.account;
         export default {
           post: (...args) => globalThis.__deliveryHarness.post(...args),
           get: (...args) => globalThis.__deliveryHarness.get(...args)
         };`
      : `export const invoke = (...args) => globalThis.__deliveryHarness.invoke(...args);` }));
  } };
const bundled = await build({
  stdin: {
    contents: "export * from './src/api/messages.ts'; export * from './src/api/deliveryState.ts';",
    resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'ts',
  },
  bundle: true, platform: 'node', format: 'esm', write: false,
  plugins: [transportPlugin],
});
const api = await import(`data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`);
const componentBundle = await build({
  entryPoints: [fileURLToPath(new URL('../src/components/MessageDeliveryReceipt.tsx', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false, jsx: 'automatic',
  external: ['react', 'react/jsx-runtime'], plugins: [transportPlugin],
});
const componentModule = { exports: {} };
new Function('require', 'module', 'exports', componentBundle.outputFiles[0].text)(
  createRequire(import.meta.url), componentModule, componentModule.exports,
);
const MessageDeliveryReceipt = componentModule.exports.default;

class MemoryStorage {
  values = new Map();
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}

const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};
const response = (receipt) => ({ data: { data: receipt } });
const accepted = (id) => ({ request_id: id, message_id: `message:${id}`, status: 'accepted', persisted: true });

beforeEach(() => {
  globalThis.localStorage = new MemoryStorage();
  globalThis.window = {};
  if (!globalThis.crypto) Object.defineProperty(globalThis, 'crypto', { value: webcrypto });
  globalThis.__deliveryHarness = {
    account: '7:1',
    post: async () => assert.fail('unexpected HTTP POST'),
    get: async () => assert.fail('unexpected HTTP GET'),
    invoke: async () => assert.fail('unexpected native side effect'),
  };
});

test('late acceptance cannot delete the next request recovery pointer', async () => {
  const firstStarted = deferred();
  const secondStarted = deferred();
  const firstResponse = deferred();
  const secondResponse = deferred();
  let firstId;
  let secondId;
  __deliveryHarness.post = async (_url, body) => {
    if (body.content === 'first message') {
      firstId = body.client_request_id;
      firstStarted.resolve();
      return firstResponse.promise;
    }
    secondId = body.client_request_id;
    secondStarted.resolve();
    return secondResponse.promise;
  };
  __deliveryHarness.get = async () => response(accepted(firstId));
  const first = api.sendMessage(7, 'telegram', 'contact', 'first message');
  await firstStarted.promise;
  const second = api.sendMessage(7, 'telegram', 'contact', 'second message');
  await secondStarted.promise;
  assert.notEqual(firstId, secondId);
  firstResponse.resolve(response(accepted(firstId)));
  await first;
  const storageKey = 'kellai:delivery:7:1:7:telegram:contact';
  assert.equal(JSON.parse(localStorage.getItem(storageKey)).requestId, secondId);
  secondResponse.resolve(response(accepted(secondId)));
  await second;
  assert.equal(localStorage.getItem(storageKey), null);
});

test('an absent recovery pointer allows one authorized request', async () => {
  const key = 'kellai:delivery:7:1:7:telegram:contact';
  assert.equal(localStorage.getItem(key), null);
  let calls = 0;
  __deliveryHarness.post = async (_url, body) => {
    calls += 1;
    const pointer = JSON.parse(localStorage.getItem(key));
    assert.equal(pointer.requestId, body.client_request_id);
    assert.match(pointer.hash, /^[a-f0-9]{64}$/);
    return response(accepted(body.client_request_id));
  };
  assert.equal((await api.sendMessage(7, 'telegram', 'contact', 'hello')).status, 'accepted');
  assert.equal(calls, 1);
  assert.equal(localStorage.getItem(key), null);
});

for (const [name, raw] of [
  ['invalid JSON', '{broken-json'],
  ['empty record', ''],
  ['serialized null', 'null'],
  ['array', '[]'],
  ['missing fields', '{}'],
  ['empty request ID', JSON.stringify({ requestId: ' ', hash: 'a'.repeat(64) })],
  ['non-string request ID', JSON.stringify({ requestId: 123, hash: 'a'.repeat(64) })],
  ['missing hash', JSON.stringify({ requestId: 'original-request' })],
  ['invalid hash', JSON.stringify({ requestId: 'original-request', hash: 'truncated' })],
]) {
  test(`${name} blocks new external delivery and preserves the damaged record`, async () => {
    const key = 'kellai:delivery:7:1:7:telegram:contact';
    localStorage.setItem(key, raw);
    let posts = 0;
    __deliveryHarness.post = async (_url, body) => { posts += 1; return response(accepted(body.client_request_id)); };
    await assert.rejects(api.sendMessage(7, 'telegram', 'contact', 'hello'), /本地发送记录/);
    assert.equal(posts, 0);
    assert.equal(localStorage.getItem(key), raw);
  });
}

test('an unreadable recovery pointer blocks HTTP and native delivery', async () => {
  const key = 'kellai:delivery:7:1:7:douyin:contact';
  const original = JSON.stringify({ requestId: 'original-request', hash: 'a'.repeat(64) });
  localStorage.setItem(key, original);
  localStorage.getItem = () => { throw new Error('storage unavailable'); };
  window.__TAURI_INTERNALS__ = {};
  let posts = 0;
  let invokes = 0;
  __deliveryHarness.post = async (_url, body) => { posts += 1; return response(accepted(body.client_request_id)); };
  __deliveryHarness.invoke = async () => { invokes += 1; return { success: true }; };
  await assert.rejects(api.sendMessage(7, 'douyin', 'contact', 'hello'), /无法读取本地发送记录/);
  assert.equal(posts, 0);
  assert.equal(invokes, 0);
  assert.equal(localStorage.values.get(key), original);
});

test('clearing a pointer requires its original request ID', () => {
  const key = 'recovery-pointer';
  const original = JSON.stringify({ requestId: 'original-request', hash: 'a'.repeat(64) });
  localStorage.setItem(key, original);
  assert.equal(api.clearPendingDelivery(localStorage, key, 'another-request'), false);
  assert.equal(localStorage.getItem(key), original);
  assert.equal(api.clearPendingDelivery(localStorage, key, 'original-request'), true);
  assert.equal(localStorage.getItem(key), null);
});

test('clearing never removes a corrupt or unreadable pointer', () => {
  const key = 'recovery-pointer';
  localStorage.setItem(key, '{broken-json');
  let removals = 0;
  localStorage.removeItem = () => { removals += 1; };
  assert.throws(() => api.clearPendingDelivery(localStorage, key, 'original-request'), /本地发送记录损坏/);
  assert.equal(localStorage.values.get(key), '{broken-json');
  localStorage.getItem = () => { throw new Error('storage unavailable'); };
  assert.throws(() => api.clearPendingDelivery(localStorage, key, 'original-request'), /无法读取本地发送记录/);
  assert.equal(removals, 0);
});

test('a changed pointer during receipt lookup cannot be replaced by a new send', async () => {
  const key = 'kellai:delivery:7:1:7:telegram:contact';
  localStorage.setItem(key, JSON.stringify({ requestId: 'first-request', hash: 'a'.repeat(64) }));
  const replacement = JSON.stringify({ requestId: 'second-request', hash: 'b'.repeat(64) });
  __deliveryHarness.get = async () => {
    localStorage.setItem(key, replacement);
    return response(accepted('first-request'));
  };
  let posts = 0;
  __deliveryHarness.post = async (_url, body) => { posts += 1; return response(accepted(body.client_request_id)); };
  await assert.rejects(api.sendMessage(7, 'telegram', 'contact', 'third message'), /本地发送记录已变化/);
  assert.equal(posts, 0);
  assert.equal(localStorage.getItem(key), replacement);
});

test('labels only promote platform receipts after ledger acceptance', () => {
  for (const [state, label] of [
    [undefined, '渠道已受理，送达待确认'],
    ['accepted', '渠道已受理，送达待确认'],
    ['sent', '渠道回执：已发送，送达待确认'],
    ['delivered', '渠道回执：已送达'],
    ['read', '渠道回执：已读'],
    ['failed', '渠道回执：发送失败'],
  ]) {
    assert.equal(api.deliveryLabel({ ...accepted('request'), provider_state: state }), label);
  }
  for (const status of ['sending', 'unknown']) {
    for (const provider_state of ['sent', 'delivered', 'read', 'failed']) {
      assert.equal(api.deliveryLabel({ ...accepted('request'), status, provider_state }),
        '发送结果待确认，请查询原请求回执');
    }
  }
  for (const provider_state of [undefined, 'sent', 'delivered', 'read', 'failed']) {
    assert.equal(api.deliveryLabel({ ...accepted('request'), status: 'failed', provider_state }),
      '发送失败，请查看失败原因');
  }
});

test('native send is fenced when account changes during prepare', async () => {
  window.__TAURI_INTERNALS__ = {};
  __deliveryHarness.post = async (_url, body, config) => {
    assert.equal(config.expectedAccount, '7:1');
    __deliveryHarness.account = '8:2';
    return response({ request_id: body.client_request_id, dispatch_allowed: true, delivery_token: 'original-token' });
  };
  await assert.rejects(api.sendMessage(7, 'douyin', 'native-contact', 'hello'), /账号已切换/);
});

test('known native result resumes under original account without another native send', async () => {
  window.__TAURI_INTERNALS__ = {};
  let invokes = 0;
  let completed = 0;
  __deliveryHarness.invoke = async () => {
    invokes += 1;
    __deliveryHarness.account = '8:2';
    return { success: true, source: 'douyin_desktop_automation', message_sent: true, contact_id: 'native-contact' };
  };
  __deliveryHarness.post = async (url, body, config) => {
    if (config.expectedAccount !== __deliveryHarness.account) throw new Error('account changed');
    if (url.endsWith('/prepare')) return response({ request_id: body.client_request_id,
      status: 'sending', persisted: false, dispatch_allowed: true, delivery_token: 'original-token' });
    completed += 1;
    assert.equal(body.delivery_token, 'original-token');
    return response(accepted(body.client_request_id));
  };
  await assert.rejects(api.sendMessage(7, 'douyin', 'native-contact', 'hello', '',
    { clientRequestId: 'auto:known-native-result', expectedAccount: '7:1' }), /账号已切换/);
  await api.flushNativeCompletions('8:2');
  assert.equal(completed, 0);
  __deliveryHarness.account = '7:1';
  await api.flushNativeCompletions('7:1');
  await api.flushNativeCompletions('7:1');
  assert.equal(invokes, 1);
  assert.equal(completed, 1);
  assert.equal(localStorage.values.size, 0, 'native token/result must not be persisted to browser storage');
});

test('worker synchronization, claim and result carry their captured account', async () => {
  const requests = [];
  __deliveryHarness.post = async (url, body, config) => { requests.push({ url, body, config }); return {}; };
  await api.syncInboxMessages('douyin', 50, '7:1');
  await api.claimAutoReplyJobs(3, '7:1');
  await api.reportAutoReplyResult({ inbound_message_id: 'inbound', lease_token: 'lease',
    delivery_key: 'auto:inbound', success: false }, '7:1');
  assert.equal(requests.length, 3);
  assert.deepEqual(requests.map((request) => request.config.expectedAccount), ['7:1', '7:1', '7:1']);
});

const projectedMessage = (requestId, state) => ({
  id: `delivery:${requestId}`, direction: 'outbound', contact_id: 'same-contact',
  metadata: { delivery_request_id: requestId, delivery_state: state, provider_message_id: `platform:${requestId}` },
});

test('server projections retain separate receipt IDs and never promote ordinary history', () => {
  const first = api.deliveryReceiptFromMessage(projectedMessage('first-request', 'read'));
  const second = api.deliveryReceiptFromMessage(projectedMessage('second-request', 'accepted'));
  assert.equal(first.request_id, 'first-request');
  assert.equal(first.provider_message_id, 'platform:first-request');
  assert.equal(api.deliveryLabel(first), '渠道回执：已读');
  assert.equal(second.request_id, 'second-request');
  assert.equal(api.deliveryLabel(second), '渠道已受理，送达待确认');
  for (const message of [
    { id: 'legacy-outbound', direction: 'outbound' },
    { id: 'provider-only', direction: 'outbound', metadata: { delivery_state: 'read', provider_message_id: 'old' } },
    { ...projectedMessage('inbound', 'read'), direction: 'inbound' },
    projectedMessage('', 'accepted'), projectedMessage(' request ', 'accepted'),
    projectedMessage('x'.repeat(201), 'accepted'), projectedMessage(123, 'accepted'),
  ]) assert.equal(api.deliveryReceiptFromMessage(message), null);
  assert.equal(api.deliveryReceiptFromMessage(projectedMessage('unknown-state', undefined)).status, 'unknown');
  assert.equal(api.deliveryReceiptFromMessage(projectedMessage('failed-state', 'failed')).status, 'failed');
});

test('actual message receipt component renders two same-contact statuses and read-only controls', () => {
  const messages = [projectedMessage('first-request', 'read'), projectedMessage('second-request', 'accepted')];
  const html = renderToStaticMarkup(React.createElement(React.Fragment, null,
    messages.map((message) => React.createElement(MessageDeliveryReceipt, {
      key: message.id, message, accountKey: '7:1', isCurrentView: () => true,
    })),
  ));
  const rows = html.split('data-delivery-request-id=');
  assert.equal(rows.length, 3);
  assert.match(rows[1], /^"first-request"/);
  assert.match(rows[1], /渠道回执：已读/);
  assert.match(rows[1], /aria-label="查询此消息回执：first-request"/);
  assert.match(rows[2], /^"second-request"/);
  assert.match(rows[2], /渠道已受理，送达待确认/);
  assert.match(rows[2], /aria-label="查询此消息回执：second-request"/);
  assert.equal(localStorage.values.size, 0, 'message history must not create a browser ledger');
});

test('actual component hides ledger-free history and conservatively renders unknown projections', () => {
  const render = (message) => renderToStaticMarkup(React.createElement(MessageDeliveryReceipt, {
    message, accountKey: '7:1', isCurrentView: () => true,
  }));
  assert.equal(render({ id: 'old-message', direction: 'outbound', metadata: { delivery_state: 'read' } }), '');
  assert.equal(render({ ...projectedMessage('incoming', 'read'), direction: 'inbound' }), '');
  const html = render(projectedMessage('unknown-projection', 'unsupported'));
  assert.match(html, /发送结果待确认，请查询原请求回执/);
  assert.doesNotMatch(html, /渠道已受理/);
});

test('receipt queries keep two original request IDs independent and only use GET', async () => {
  const requests = [];
  const firstReply = deferred();
  __deliveryHarness.get = async (url, config) => {
    requests.push({ url, config });
    if (url.endsWith('/first-request')) return firstReply.promise;
    return response({ ...accepted('second-request'), provider_state: 'sent' });
  };
  const first = api.getDeliveryReceiptForView('first-request', '7:1', () => true);
  const second = await api.getDeliveryReceiptForView('second-request', '7:1', () => true);
  firstReply.resolve(response({ ...accepted('first-request'), provider_state: 'read' }));
  assert.equal((await first).request_id, 'first-request');
  assert.equal(second.request_id, 'second-request');
  assert.equal(second.provider_state, 'sent');
  assert.deepEqual(requests.map(({ url }) => url), [
    '/api/kellai/messages/requests/first-request', '/api/kellai/messages/requests/second-request',
  ]);
  assert.deepEqual(requests.map(({ config }) => config.expectedAccount), ['7:1', '7:1']);
  assert.equal(localStorage.values.size, 0);
});

for (const change of ['account', 'contact']) {
  test(`late receipt after ${change} change is discarded`, async () => {
    const pending = deferred();
    let currentView = { contact: 7 };
    const originalView = currentView;
    __deliveryHarness.get = async () => pending.promise;
    const original = api.getDeliveryReceiptForView('first-request', '7:1', () => currentView === originalView);
    if (change === 'account') __deliveryHarness.account = '8:2';
    else currentView = { contact: 8 };
    pending.resolve(response({ ...accepted('first-request'), provider_state: 'read' }));
    assert.equal(await original, null);
  });
}

test('receipt query refuses an already stale view or mismatched request response', async () => {
  assert.equal(await api.getDeliveryReceiptForView('old-request', '7:1', () => false), null);
  assert.equal(await api.getDeliveryReceiptForView('old-account', '8:2', () => true), null);
  __deliveryHarness.get = async () => response(accepted('unrelated-request'));
  await assert.rejects(api.getDeliveryReceiptForView('original-request', '7:1', () => true), /回执与原发送请求不符/);
});
