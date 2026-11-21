import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import test, { beforeEach } from 'node:test';
import { build } from 'esbuild';

const require = createRequire(import.meta.url);
const axios = require('axios');
// Exercise the real Axios interceptor chain. Only UI dependencies and the HTTP
// adapter are isolated; no provider request or refresh endpoint is contacted.
const bundle = await build({
  entryPoints: [fileURLToPath(new URL('../src/api/client.ts', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false, external: ['axios'],
  define: { 'import.meta.env.DEV': 'false', 'import.meta.env.VITE_API_BASE_URL': '"http://test.invalid"' },
  plugins: [{ name: 'ui-boundary', setup(builder) {
    builder.onResolve({ filter: /^\.\.\/(stores\/toast|mocks|utils\/routing)$/ }, ({ path }) => ({ path, namespace: 'isolated-ui' }));
    builder.onLoad({ filter: /.*/, namespace: 'isolated-ui' }, ({ path }) => ({ contents:
      path.includes('toast') ? 'export const toastStore = { dismiss() {}, loading() {}, error() {} };' :
      path.includes('mocks') ? 'export const shouldUseMock = () => false;' :
      'export const appPath = (path) => path;' }));
  } }],
});
const productModule = { exports: {} };
new Function('require', 'module', 'exports', bundle.outputFiles[0].text)(require, productModule, productModule.exports);
const { default: client, loopbackClient } = productModule.exports;

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
const ok = (config, data = { success: true }) => ({ config, data, status: 200, statusText: 'OK', headers: {} });
const unauthorized = (config) => new axios.AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, {},
  { config, data: {}, status: 401, statusText: 'Unauthorized', headers: {} });
function account(team, user) {
  localStorage.setItem('auth_user', JSON.stringify({ team_id: team, id: user }));
  localStorage.setItem('auth_token', `access-${team}`);
  localStorage.setItem('auth_refresh_token', `refresh-${team}`);
}
beforeEach(() => {
  globalThis.localStorage = new MemoryStorage();
  globalThis.window = { location: { hostname: 'localhost', pathname: '/', href: '/' }, setTimeout, clearTimeout };
  account(7, 1);
  client.defaults.adapter = async () => assert.fail('unexpected product HTTP request');
  loopbackClient.defaults.adapter = async () => assert.fail('unexpected loopback HTTP request');
  axios.defaults.adapter = async () => assert.fail('unexpected token refresh');
});

test('late configuration 401 cannot replay its body or clear the next account', async () => {
  const started = deferred(), pending = deferred();
  let original, calls = 0;
  client.defaults.adapter = (config) => { calls += 1; original = config; started.resolve(); return pending.promise; };
  const saving = client.put('/api/kellai/channels/chatwoot/config', { api_access_token: 'account-a-key' }, { skipLoading: true });
  const rejected = assert.rejects(saving, /Unauthorized/);
  await started.promise;
  assert.equal(original.expectedAccount, '7:1');
  account(8, 2);
  pending.reject(unauthorized(original));
  await rejected;
  assert.equal(calls, 1);
  assert.equal(localStorage.getItem('auth_token'), 'access-8');
  assert.equal(localStorage.getItem('auth_refresh_token'), 'refresh-8');
});

test('late successful settings and loopback responses cannot populate a new account', async () => {
  for (const transport of [client, loopbackClient]) {
    account(7, 1);
    const started = deferred(), pending = deferred();
    let original;
    transport.defaults.adapter = (config) => { original = config; started.resolve(); return pending.promise; };
    const loading = transport.get('/api/kellai/channels');
    const rejected = assert.rejects(loading, /账号已切换/);
    await started.promise;
    account(8, 2);
    pending.resolve(ok(original, { data: ['old private configuration'] }));
    await rejected;
  }
});

test('same-account refresh retains the captured account and retries once', async () => {
  let calls = 0, refreshes = 0;
  client.defaults.adapter = async (config) => {
    calls += 1;
    assert.equal(config.expectedAccount, '7:1');
    if (!config.__retried) throw unauthorized(config);
    assert.equal(config.headers.Authorization, 'Bearer renewed-7');
    return ok(config);
  };
  axios.defaults.adapter = async (config) => {
    refreshes += 1;
    assert.equal(JSON.parse(config.data).refresh_token, 'refresh-7');
    return ok(config, { success: true, access_token: 'renewed-7', refresh_token: 'renewed-refresh-7' });
  };
  await client.put('/api/kellai/ai/llm-config', { model: 'authorized-model' }, { skipLoading: true });
  assert.equal(calls, 2);
  assert.equal(refreshes, 1);
});

test('in-flight refresh is isolated from the next account refresh', async () => {
  const firstStarted = deferred(), firstResponse = deferred();
  let firstConfig, refreshes = 0;
  client.defaults.adapter = async (config) => {
    if (!config.__retried) throw unauthorized(config);
    assert.equal(config.headers.Authorization, 'Bearer renewed-8');
    return ok(config);
  };
  axios.defaults.adapter = async (config) => {
    refreshes += 1;
    if (JSON.parse(config.data).refresh_token === 'refresh-7') {
      firstConfig = config;
      firstStarted.resolve();
      return firstResponse.promise;
    }
    return ok(config, { success: true, access_token: 'renewed-8', refresh_token: 'renewed-refresh-8' });
  };
  const first = client.get('/api/kellai/channels');
  const rejected = assert.rejects(first, /Unauthorized/);
  await firstStarted.promise;
  account(8, 2);
  await client.get('/api/kellai/channels');
  firstResponse.resolve(ok(firstConfig, { success: true, access_token: 'renewed-7', refresh_token: 'renewed-refresh-7' }));
  await rejected;
  assert.equal(refreshes, 2);
  assert.equal(localStorage.getItem('auth_token'), 'renewed-8');
  assert.equal(localStorage.getItem('auth_refresh_token'), 'renewed-refresh-8');
});
