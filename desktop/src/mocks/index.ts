/**
 * Mock 模式开关
 *
 * 三种开启方式（任一即可）：
 * 1. .env 里写 VITE_USE_MOCK=true
 * 2. localStorage.setItem("kellai:useMock", "1")
 * 3. 设置页"使用 Mock 数据"开关
 */

const LS_KEY = 'kellai:useMock';
const ENV_KEY = 'VITE_USE_MOCK';

export function shouldUseMock(): boolean {
  // 1) 环境变量
  const env = (import.meta.env[ENV_KEY] || '').toString().toLowerCase();
  if (env === '1' || env === 'true' || env === 'yes') return true;
  // 2) localStorage
  try {
    const v = localStorage.getItem(LS_KEY);
    if (v === '1' || v === 'true') return true;
  } catch {
    // ignore
  }
  return false;
}

export function setUseMock(v: boolean) {
  try {
    if (v) localStorage.setItem(LS_KEY, '1');
    else localStorage.removeItem(LS_KEY);
  } catch {
    // ignore
  }
}

export function isMockOn(): boolean {
  return shouldUseMock();
}
