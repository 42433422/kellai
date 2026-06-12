import type { APIKey, Plugin, ISVPartner, WebhookConfig, EventSubscription, AppTemplate, ReviewStatus } from '../types';

const apiKeys: APIKey[] = [
  { id: 'key1', name: '生产环境', key_prefix: 'kl_live_****', scopes: ['customers:read', 'messages:write'], created_at: '2026-01-15T00:00:00Z', last_used_at: '2026-06-12T08:00:00Z' },
];

const plugins: Plugin[] = [
  { id: 'p1', name: '企业微信增强', description: '企业微信消息同步与自动回复增强', author: 'Kellai Labs', category: 'channel', rating: 4.8, installs: 1250, price: 0, installed: true },
  { id: 'p2', name: '智能报价助手', description: '基于行业模板自动生成报价', author: 'DevPartner', category: 'sales', rating: 4.5, installs: 890, price: 99, installed: false },
  { id: 'p3', name: '数据导出 Pro', description: '高级报表导出与定时推送', author: 'DataFlow', category: 'analytics', rating: 4.2, installs: 456, price: 49, installed: false },
];

const webhooks: WebhookConfig[] = [];
const reviews: ReviewStatus[] = [];

export function getAPIKeys(): APIKey[] {
  return apiKeys;
}

export function createAPIKey(name: string, scopes: string[]): APIKey {
  const key: APIKey = {
    id: `key_${Date.now()}`,
    name,
    key_prefix: `kl_live_${Math.random().toString(36).slice(2, 6)}****`,
    scopes,
    created_at: new Date().toISOString(),
  };
  apiKeys.push(key);
  return key;
}

export function getPlugins(): Plugin[] {
  return plugins;
}

export function publishPlugin(data: Partial<Plugin>): Plugin {
  const plugin: Plugin = {
    id: `p_${Date.now()}`,
    name: data.name ?? '新插件',
    description: data.description ?? '',
    author: data.author ?? '开发者',
    category: data.category ?? 'other',
    rating: 0,
    installs: 0,
    price: data.price ?? 0,
    installed: false,
  };
  plugins.push(plugin);
  return plugin;
}

export function getISVPartners(): ISVPartner[] {
  return [
    { id: 'isv1', name: 'CloudTech 解决方案', tier: 'gold', solutions: 12, certified: true },
    { id: 'isv2', name: 'SmartSales 科技', tier: 'silver', solutions: 5, certified: true },
    { id: 'isv3', name: 'DataBridge', tier: 'bronze', solutions: 2, certified: false },
  ];
}

export function registerOpenWebhook(url: string, events: string[]): WebhookConfig {
  const wh: WebhookConfig = {
    id: `owh_${Date.now()}`,
    url,
    events,
    secret: `whsec_${Math.random().toString(36).slice(2, 14)}`,
    active: true,
  };
  webhooks.push(wh);
  return wh;
}

export function getEvents(): EventSubscription[] {
  return [
    { id: 'ev1', event_type: 'customer.created', description: '新客户创建', subscribed: true },
    { id: 'ev2', event_type: 'message.received', description: '收到新消息', subscribed: true },
    { id: 'ev3', event_type: 'deal.closed', description: '成交完成', subscribed: false },
    { id: 'ev4', event_type: 'flow.completed', description: '流程执行完成', subscribed: false },
  ];
}

export function getAppTemplates(): AppTemplate[] {
  return [
    { id: 'at1', name: '客户跟进表单', description: '自定义客户跟进字段', fields: [{ key: 'priority', label: '优先级', type: 'select' }, { key: 'next_action', label: '下一步', type: 'text' }] },
    { id: 'at2', name: '报价审批', description: '报价单审批流程', fields: [{ key: 'amount', label: '金额', type: 'number' }, { key: 'approver', label: '审批人', type: 'text' }] },
  ];
}

export function getAPIDocs(): { endpoints: { method: string; path: string; description: string }[] } {
  return {
    endpoints: [
      { method: 'GET', path: '/api/kellai/customers', description: '获取客户列表' },
      { method: 'GET', path: '/api/kellai/messages', description: '获取消息列表' },
      { method: 'POST', path: '/api/kellai/messages/send', description: '发送消息' },
      { method: 'GET', path: '/api/kellai/pipeline/funnel', description: '获取漏斗数据' },
      { method: 'POST', path: '/api/kellai/sales/auto-flow', description: '启动自动销售流程' },
      { method: 'POST', path: '/api/kellai/content/publish', description: '内容一键分发' },
    ],
  };
}

export function submitReview(appName: string): ReviewStatus {
  const review: ReviewStatus = {
    app_id: `app_${Date.now()}`,
    app_name: appName,
    status: 'pending',
    submitted_at: new Date().toISOString(),
  };
  reviews.push(review);
  return review;
}

export function getWebhooks(): WebhookConfig[] {
  return webhooks;
}

export function getReviews(): ReviewStatus[] {
  return reviews;
}

export function installPlugin(pluginId: string): boolean {
  const p = plugins.find((x) => x.id === pluginId);
  if (p) { p.installed = true; return true; }
  return false;
}
