import type { APIKey, Plugin, ISVPartner, WebhookConfig, EventSubscription, AppTemplate, ReviewStatus, PlatformStats, ApiEndpointDoc } from '../types';

const apiKeys: APIKey[] = [
  { id: 'key1', name: '生产环境', key_prefix: 'kl_live_8f2a****', scopes: ['customers:read', 'messages:write'], created_at: '2026-01-15T00:00:00Z', last_used_at: '2026-06-13T08:00:00Z' },
  { id: 'key2', name: '测试环境', key_prefix: 'kl_test_3c9d****', scopes: ['customers:read'], created_at: '2026-03-20T00:00:00Z', last_used_at: '2026-06-10T14:00:00Z' },
];

const plugins: Plugin[] = [
  { id: 'p1', name: '企业微信增强', description: '企业微信消息同步与自动回复增强，支持会话存档与素材库', author: 'Kellai Labs', category: 'channel', rating: 4.8, installs: 1250, price: 0, installed: true, icon: '💬', version: '2.3.1', tags: ['企微', '自动回复'], featured: true, updated_at: '2026-06-01T00:00:00Z', publisher_verified: true },
  { id: 'p2', name: '智能报价助手', description: '基于行业模板自动生成报价单，支持折扣审批与电子签', author: 'DevPartner', category: 'sales', rating: 4.5, installs: 890, price: 99, installed: false, icon: '💰', version: '1.8.0', tags: ['报价', 'CPQ'], featured: true, updated_at: '2026-05-22T00:00:00Z', publisher_verified: true },
  { id: 'p3', name: '数据导出 Pro', description: '高级报表导出与定时推送，支持 Excel/PDF/飞书多维表', author: 'DataFlow', category: 'analytics', rating: 4.2, installs: 456, price: 49, installed: false, icon: '📊', version: '3.1.2', tags: ['报表', '导出'], updated_at: '2026-05-10T00:00:00Z', publisher_verified: false },
  { id: 'p4', name: '抖音线索同步', description: '自动同步抖音评论与私信线索到 CRM，含意向评分', author: 'GrowthHub', category: 'channel', rating: 4.6, installs: 1580, price: 0, installed: false, icon: '🎵', version: '1.4.0', tags: ['抖音', '获客'], featured: true, updated_at: '2026-06-05T00:00:00Z', publisher_verified: true },
  { id: 'p5', name: 'AI 外呼机器人', description: '智能语音外呼，自动筛客与意向判定，对接坐席', author: 'VoiceAI', category: 'sales', rating: 4.3, installs: 620, price: 199, installed: false, icon: '📞', version: '2.0.5', tags: ['外呼', 'AI语音'], updated_at: '2026-04-28T00:00:00Z', publisher_verified: true },
  { id: 'p6', name: '工单系统集成', description: '将客户问题一键转工单，支持 SLA 与升级流程', author: 'ServiceX', category: 'service', rating: 4.0, installs: 312, price: 79, installed: false, icon: '🎫', version: '1.2.0', tags: ['工单', '售后'], updated_at: '2026-03-15T00:00:00Z', publisher_verified: false },
  { id: 'p7', name: '财务对账插件', description: '自动对账与发票管理，对接金蝶/用友', author: 'FinBridge', category: 'analytics', rating: 4.4, installs: 540, price: 129, installed: false, icon: '🧾', version: '1.6.3', tags: ['财务', '对账'], updated_at: '2026-05-30T00:00:00Z', publisher_verified: true },
  { id: 'p8', name: '邮件营销大师', description: 'EDM 批量发送、打开追踪与 A/B 测试', author: 'MailPro', category: 'channel', rating: 3.9, installs: 280, price: 0, installed: false, icon: '✉️', version: '0.9.8', tags: ['邮件', 'EDM'], updated_at: '2026-02-18T00:00:00Z', publisher_verified: false },
];

const webhooks: WebhookConfig[] = [
  { id: 'owh_demo', url: 'https://hooks.example.com/kellai', events: ['customer.created', 'deal.closed'], secret: 'whsec_demo8f2a3c9d', active: true },
];
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

export function revokeAPIKey(id: string): boolean {
  const idx = apiKeys.findIndex((k) => k.id === id);
  if (idx >= 0) { apiKeys.splice(idx, 1); return true; }
  return false;
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
    icon: data.icon ?? '🧩',
    version: '1.0.0',
  };
  plugins.push(plugin);
  return plugin;
}

export function getISVPartners(): ISVPartner[] {
  return [
    { id: 'isv1', name: 'CloudTech 解决方案', tier: 'gold', solutions: 12, certified: true },
    { id: 'isv2', name: 'SmartSales 科技', tier: 'silver', solutions: 5, certified: true },
    { id: 'isv3', name: 'DataBridge', tier: 'bronze', solutions: 2, certified: false },
    { id: 'isv4', name: '智联云服', tier: 'gold', solutions: 9, certified: true },
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
    { id: 'ev5', event_type: 'lead.converted', description: '线索转化', subscribed: true },
    { id: 'ev6', event_type: 'contract.signed', description: '合同签署', subscribed: false },
  ];
}

export function getAppTemplates(): AppTemplate[] {
  return [
    {
      id: 'at1',
      name: '客户跟进表单',
      description: '自定义客户跟进字段，支持优先级与下一步动作',
      icon: '📋',
      category: '销售',
      fields: [
        { key: 'priority', label: '优先级', type: 'select', options: ['高', '中', '低'], required: true },
        { key: 'next_action', label: '下一步动作', type: 'text', placeholder: '如：本周二电话回访' },
        { key: 'follow_date', label: '跟进日期', type: 'date' },
        { key: 'note', label: '备注', type: 'textarea', placeholder: '补充说明' },
      ],
    },
    {
      id: 'at2',
      name: '报价审批',
      description: '报价单审批流程，支持金额与审批人',
      icon: '✅',
      category: '财务',
      fields: [
        { key: 'amount', label: '报价金额', type: 'number', required: true, placeholder: '0.00' },
        { key: 'discount', label: '折扣', type: 'select', options: ['无', '95 折', '9 折', '85 折'] },
        { key: 'approver', label: '审批人', type: 'text', required: true },
        { key: 'reason', label: '申请理由', type: 'textarea' },
      ],
    },
    {
      id: 'at3',
      name: '满意度调研',
      description: '客户满意度回访表单',
      icon: '⭐',
      category: '售后',
      fields: [
        { key: 'score', label: '满意度评分', type: 'select', options: ['5 分', '4 分', '3 分', '2 分', '1 分'], required: true },
        { key: 'channel', label: '服务渠道', type: 'select', options: ['电话', '在线', '企微'] },
        { key: 'feedback', label: '反馈内容', type: 'textarea' },
      ],
    },
  ];
}

const API_DOCS: ApiEndpointDoc[] = [
  { method: 'GET', path: '/api/kellai/customers', description: '获取客户列表，支持分页、搜索与阶段过滤', category: '客户', auth_required: true, sample: 'curl -H "Authorization: Bearer <token>" \\\n  "{base}/customers?page=1&keyword=科技"' },
  { method: 'POST', path: '/api/kellai/customers', description: '创建新客户', category: '客户', auth_required: true, sample: 'curl -X POST -H "Authorization: Bearer <token>" \\\n  -d \'{"name":"张三","phone":"13800000000"}\' \\\n  "{base}/customers"' },
  { method: 'GET', path: '/api/kellai/messages', description: '获取消息列表', category: '消息', auth_required: true, sample: 'curl -H "Authorization: Bearer <token>" "{base}/messages"' },
  { method: 'POST', path: '/api/kellai/messages/send', description: '发送消息到指定渠道', category: '消息', auth_required: true, sample: 'curl -X POST -H "Authorization: Bearer <token>" \\\n  -d \'{"to":"c_1001","content":"您好"}\' "{base}/messages/send"' },
  { method: 'GET', path: '/api/kellai/pipeline/funnel', description: '获取销售漏斗数据', category: '销售', auth_required: true, sample: 'curl -H "Authorization: Bearer <token>" "{base}/pipeline/funnel"' },
  { method: 'POST', path: '/api/kellai/sales/auto-flow', description: '启动 / 推进自动销售流程', category: '销售', auth_required: true, sample: 'curl -X POST -H "Authorization: Bearer <token>" \\\n  -d \'{"customer_id":1001}\' "{base}/sales/auto-flow"' },
  { method: 'GET', path: '/api/kellai/finance/dashboard', description: '获取财务看板数据', category: '财务', auth_required: true, sample: 'curl -H "Authorization: Bearer <token>" "{base}/finance/dashboard?period=month"' },
  { method: 'POST', path: '/api/kellai/content/publish', description: '内容一键多平台分发', category: '内容', auth_required: true, sample: 'curl -X POST -H "Authorization: Bearer <token>" \\\n  -d \'{"content_id":"c1","platforms":["wechat"]}\' "{base}/content/publish"' },
  { method: 'POST', path: '/api/kellai/scout/scan', description: '扫描评论区识别高意向线索', category: '获客', auth_required: true, sample: 'curl -X POST -H "Authorization: Bearer <token>" \\\n  -d \'{"keyword":"CRM"}\' "{base}/scout/scan"' },
];

export function getAPIDocs(): { endpoints: ApiEndpointDoc[] } {
  return { endpoints: API_DOCS };
}

export function getPlatformStats(): PlatformStats {
  return {
    api_calls_30d: 184320,
    plugins: plugins.length,
    total_installs: plugins.reduce((s, p) => s + p.installs, 0),
    isv_partners: 4,
    active_webhooks: webhooks.filter((w) => w.active).length,
    events_today: 1284,
    uptime: 99.98,
    call_trend: [
      { date: '06-07', count: 5200 },
      { date: '06-08', count: 5800 },
      { date: '06-09', count: 6100 },
      { date: '06-10', count: 5900 },
      { date: '06-11', count: 6800 },
      { date: '06-12', count: 7200 },
      { date: '06-13', count: 6400 },
    ],
    recent_activity: [
      { id: 'a1', type: 'install', text: '「抖音线索同步」被安装', timestamp: '2026-06-13T08:30:00Z' },
      { id: 'a2', type: 'key', text: '创建了新的 API 密钥「测试环境」', timestamp: '2026-06-13T07:10:00Z' },
      { id: 'a3', type: 'webhook', text: 'Webhook deal.closed 触发 12 次', timestamp: '2026-06-13T06:00:00Z' },
      { id: 'a4', type: 'review', text: 'ISV「智联云服」通过金牌认证', timestamp: '2026-06-12T15:20:00Z' },
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
  if (p) { p.installed = true; p.installs += 1; return true; }
  return false;
}
