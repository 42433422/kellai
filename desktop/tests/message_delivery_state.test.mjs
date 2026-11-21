import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import test, { beforeEach } from 'node:test';
import { build } from 'esbuild';

// Bundle the actual product API with only the network/native transport replaced.
// No browser, provider account, native app or new test dependency is required.
const bundled = await build({
  stdin: {
    contents: "export * from './src/api/messages.ts'; export * from './src/api/deliveryState.ts';",
    resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'ts',
  },
  bundle: true, platform: 'node', format: 'esm', write: false,
  plugins: [{ name: 'test-transports', setup(builder) {
    builder.onResolve({ filter: /^\.\/client$/ }, () => ({ path: 'client', namespace: 'transport' }));
    builder.onResolve({ filter: /^@tauri-apps\/api\/core$/ }, () => ({ path: 'native', namespace: 'transport' }));
    builder.onLoad({ filter: /.*/, namespace: 'transport' }, ({ path }) => ({ contents: path === 'client'
      ? `export const currentAccountKey = () => globalThis.__deliveryHarness.account;
         export default {
           post: (...args) => globalThis.__deliveryHarness.post(...args),
           get: (...args) => globalThis.__deliveryHarness.get(...args)
         };`
      : `export const invoke = (...args) => globalThis.__deliveryHarness.invoke(...args);` }));
  } }],
});
const api = await import(`data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`);

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
