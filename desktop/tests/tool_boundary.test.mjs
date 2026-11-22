import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { readFile } from 'node:fs/promises';
import test, { beforeEach } from 'node:test';
import { build } from 'esbuild';

const require = createRequire(import.meta.url);
const axios = require('axios');
const bundle = await build({
  entryPoints: [fileURLToPath(new URL('../src/api/client.ts', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false, external: ['axios'],
  define: { 'import.meta.env.DEV': 'false', 'import.meta.env.VITE_API_BASE_URL': '"http://127.0.0.1:8793"' },
});
const module = { exports: {} };
new Function('require', 'module', 'exports', bundle.outputFiles[0].text)(require, module, module.exports);
const api = module.exports;

class MemoryStorage {
  values = new Map();
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const session = (team) => ({ access_token: `operator-${team}`, expires_at: Date.now() / 1000 + 3600,
  user: { id: 1, team_id: team, role: 'owner', display_name: '本地操作者' } });
const ok = (config, data = { success: true, data: [] }) => ({ config, data, status: 200, headers: {} });
beforeEach(() => {
  globalThis.sessionStorage = new MemoryStorage();
  globalThis.localStorage = new MemoryStorage();
  api.setToolSession(session(7));
  api.default.defaults.adapter = async () => assert.fail('unexpected network call');
});

test('operator token is session-scoped and old SaaS passwords are discarded', () => {
  localStorage.setItem('kellai_saved_credentials', 'retired-obfuscated-passwords');
  localStorage.setItem('auth_refresh_token', 'retired-refresh-token');
  localStorage.setItem('kellai:delivery:old-request', 'retained-business-receipt');
  api.restoreSession();
  assert.equal(api.getSession().user.team_id, 7);
  assert.equal(localStorage.getItem('kellai_saved_credentials'), null);
  assert.equal(localStorage.getItem('auth_refresh_token'), null);
  assert.equal(localStorage.getItem('kellai:delivery:old-request'), 'retained-business-receipt');
  assert.equal(localStorage.getItem('auth_token'), null);
});

test('expired operator state cannot unlock the tool', () => {
  api.setToolSession({ ...session(7), expires_at: Date.now() / 1000 - 1 });
  api.restoreSession();
  assert.equal(api.getSession(), null);
});

test('late private response cannot populate another workspace', async () => {
  const pending = deferred(), started = deferred();
  let original;
  api.default.defaults.adapter = (config) => { original = config; started.resolve(); return pending.promise; };
  const loading = api.request('get', '/accounts');
  const rejected = assert.rejects(loading, /连接已切换/);
  await started.promise;
  api.setToolSession(session(8));
  pending.resolve(ok(original, { success: true, data: [{ name: 'private-old-account' }] }));
  await rejected;
});

test('late 401 neither replays a credential write nor clears the new operator', async () => {
  const pending = deferred(), started = deferred();
  let original, calls = 0;
  api.default.defaults.adapter = (config) => { original = config; calls++; started.resolve(); return pending.promise; };
  const saving = api.request('patch', '/accounts/connection-a', { config: { api_key: 'secret-a' } });
  const rejected = assert.rejects(saving, /Unauthorized/);
  await started.promise;
  api.setToolSession(session(8));
  pending.reject(new axios.AxiosError('Unauthorized', 'ERR_BAD_REQUEST', original, {}, { status: 401 }));
  await rejected;
  assert.equal(calls, 1);
  assert.equal(api.getSession().access_token, 'operator-8');
});

test('same-session 401 locks the tool and does not retry the mutation', async () => {
  let calls = 0;
  api.default.defaults.adapter = async (config) => {
    calls++;
    throw new axios.AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, {}, { status: 401 });
  };
  await assert.rejects(api.request('post', '/accounts', { name: 'account' }), /Unauthorized/);
  assert.equal(calls, 1);
  assert.equal(api.getSession(), null);
});

test('unlocked operator is required before any account operation', async () => {
  api.setToolSession(null);
  await assert.rejects(api.request('get', '/accounts'), /请先从 XCMAX/);
});

test('application failures are shown even when transport returned HTTP 200', async () => {
  api.default.defaults.adapter = async (config) => ok(config, { success: false, error: '账号已停用' });
  await assert.rejects(api.request('post', '/accounts/a/test', {}), /账号已停用/);
});

test('receipt lookup only reads the original request and cannot resend it', async () => {
  const requests = [];
  api.default.defaults.adapter = async (config) => {
    requests.push([config.method, config.url]);
    return ok(config, { success: true, data: { request_id: 'original', status: 'unknown' } });
  };
  const result = await api.request('get', '/messages/requests/original');
  assert.equal(result.status, 'unknown');
  assert.deepEqual(requests, [['get', '/api/kellai/messages/requests/original']]);
});

test('production frontend rejects an external SaaS API origin', async () => {
  const result = await build({
    entryPoints: [fileURLToPath(new URL('../src/api/client.ts', import.meta.url))],
    bundle: true, platform: 'node', format: 'cjs', write: false, external: ['axios'],
    define: { 'import.meta.env.DEV': 'false', 'import.meta.env.VITE_API_BASE_URL': '"https://remote.invalid"' },
  });
  assert.throws(() => new Function('require', 'module', 'exports', result.outputFiles[0].text)(require, { exports: {} }, {}), /只连接本机/);
});

test('capability-based tool UI has no direct native or HTTP sender', async () => {
  const source = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const native = await readFile(new URL('../src-tauri/src/lib.rs', import.meta.url), 'utf8');
  assert.match(source, /统一聊天/);
  assert.doesNotMatch(source, /messages\/send|douyin_desktop_send|\/auth\/register|\/auth\/login/);
  assert.doesNotMatch(native, /douyin_desktop_send/);
});
