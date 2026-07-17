const configuredBasename = String(import.meta.env.VITE_ROUTER_BASENAME || '').trim();
const buildBase = String(import.meta.env.BASE_URL || '/').trim();

function normalizeBasename(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed === '/') return '';
  return `/${trimmed.replace(/^\/+|\/+$/g, '')}`;
}

/** React Router 与原生 location 跳转共用同一个部署前缀。 */
export const ROUTER_BASENAME = normalizeBasename(configuredBasename || buildBase);

export function appPath(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  if (!ROUTER_BASENAME) return normalizedPath;
  if (normalizedPath === '/') return `${ROUTER_BASENAME}/`;
  return `${ROUTER_BASENAME}${normalizedPath}`;
}
