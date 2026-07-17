/**
 * Mock 模式开关
 *
 * 仅开发构建可开启，正式桌面包始终连接真实后端。
 *
 * 开发构建有三种开启方式（任一即可）：
 * 1. .env 里写 VITE_USE_MOCK=true
 * 2. localStorage.setItem("kellai:useMock", "1")
 * 3. 设置页"使用 Mock 数据"开关
 */

const LS_KEY = 'kellai:useMock';
const ENV_KEY = 'VITE_USE_MOCK';

export function shouldUseMock(): boolean {
  // 打包交付物必须使用真实 API，避免遗留 localStorage 让渠道消息、
  // 员工心跳和负责人分配悄悄落到演示数据。
  if (import.meta.env.PROD) return false;

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
    if (import.meta.env.PROD) {
      localStorage.removeItem(LS_KEY);
      return;
    }
    if (v) localStorage.setItem(LS_KEY, '1');
    else localStorage.removeItem(LS_KEY);
  } catch {
    // ignore
  }
}

export function isMockOn(): boolean {
  return shouldUseMock();
}
