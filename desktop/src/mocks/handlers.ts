/**
 * Mock 拦截器：在 mock 模式下把 axios 请求"截下来"，用本地数据返回。
 *
 * 用法（在 client.ts 里）：
 *   const adapter = shouldUseMock() ? createMockAdapter() : undefined;
 *   const client = axios.create({ ..., adapter });
 *
 * 覆盖的端点（与真后端对齐，路径都是 /api/kellai/...）：
 *   GET    /api/kellai/pipeline/funnel
 *   GET    /api/kellai/pipeline/query
 *   GET    /api/kellai/pipeline?customer_id=X
 *   POST   /api/kellai/pipeline/stage              （漏斗里拖卡片用）
 *   PUT    /api/kellai/pipeline/customer/:id/stage （教程里拖卡片用）
 *
 *   GET    /api/kellai/messages
 *   POST   /api/kellai/messages/send
 *   POST   /api/kellai/messages/mark-read
 *   GET    /api/kellai/messages/unread-count
 *
 *   POST   /api/kellai/ai/intent
 *   POST   /api/kellai/ai/suggest-reply
 *   POST   /api/kellai/ai/auto-reply
 *   GET    /api/kellai/ai/profile/:id
 *   GET    /api/kellai/ai/operating-insight/:id
 *   GET    /api/kellai/ai/reminders
 *
 *   GET    /api/kellai/channels
 *   GET    /api/kellai/crm?customer_id=X
 */

import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { handleExtendedRoutes } from './mockRouter';
import {
  MOCK_CUSTOMERS,
  getMockFunnelStages,
  getMockAiProfile,
  getMockMessages,
  getMockReminders,
  addMockCustomer,
  updateMockCustomer,
  deleteMockCustomer,
  setMockCustomerStage,
  stageLabelOf,
  mockStageDefinitions,
} from './customers';

/* -------- 内部可变状态：mock 阶段变更会写回这里 -------- */
const stageMap = new Map<number, string>();
MOCK_CUSTOMERS.forEach((c) => stageMap.set(c.customer_id, c.stage));

const messageStore: Record<number, ReturnType<typeof getMockMessages>> = {};
MOCK_CUSTOMERS.forEach((c) => {
  messageStore[c.customer_id] = getMockMessages(c.customer_id);
});
const mockServiceTickets: Record<number, any[]> = {};
const mockServiceLearning: Record<number, any> = {};
const mockSelfServiceSessions: Record<number, any[]> = {};
const mockOutboundCalls: Record<number, any[]> = {};

/** mock 短信验证码存储：phone → code（找回密码 / 验证码登录用） */
const mockSmsCodes: Record<string, string> = {};
const mockQrLoginSessions: Record<string, {
  secret: string;
  status: 'waiting' | 'scanned' | 'authorized' | 'expired' | 'canceled' | 'failed';
  expiresAt: number;
  user?: ReturnType<typeof buildMockUser>;
  login?: {
    success: boolean;
    access_token: string;
    refresh_token: string;
    access_expires_at: string;
    refresh_expires_at: string;
    user: ReturnType<typeof buildMockUser>;
  };
  error?: string;
}> = {};
const MOCK_QR_LOGIN_TTL_MS = 180 * 1000;
const mockLlmConfig = {
  provider: 'deepseek',
  model: 'deepseek-chat',
  base_url: 'https://api.deepseek.com/v1',
  key_prefix: 'mock-key',
  ready: true,
  connected: true,
  verified: true,
  lastProbe: {
    success: true,
    connected: true,
    checked_at: '2026-06-13T00:00:00Z',
    provider: 'deepseek',
    model: 'deepseek-chat',
    latency_ms: 120,
    error: '',
  },
  autoReplyEnabled: true,
  autoReplyStages: ['已建联', '需求采集', '已报价', '谈判中'],
  confirmScenarios: ['价格优惠', '合同条款'],
  message: 'Mock LLM 已就绪',
};

const mockKnowledgeArticles: Array<{
  id: string;
  title: string;
  content: string;
  tags: string[];
  source: string;
  updated_at: string;
}> = [
  {
    id: 'mock_kb_wework_offer',
    title: '企微接入与首月优惠',
    content: '企业微信接入需要客服链接或 open_kfid。首月优惠需在客户确认合同后申请，付款后安排交付清单、渠道配置和团队培训。',
    tags: ['企业微信', '优惠', '交付'],
    source: 'mock',
    updated_at: '2026-06-13T00:00:00Z',
  },
];

/* ============================================================
 *  渠道 mock 状态（按 channelGroups 分组，跨请求持久化）
 * ============================================================ */
const channelMockState: Record<string, {
  id: string;
  name: string;
  type: string;
  channel_type: string;
  adapter_class: string;
  enabled: boolean;
  connected: boolean;
  config: Record<string, string>;
  message: string;
  createdAt: string;
}> = {
  // 即时通讯
  wechat:     { id: 'ch_wechat',     name: '微信开放平台', type: 'wechat',     channel_type: 'wechat',     adapter_class: 'WeChatAdapter',      enabled: true,  connected: true,  config: { app_id: 'wx_mock_app', app_secret: '***', oauth_authorized: 'true', oauth_openid: 'mock_openid' }, message: '已连接', createdAt: '2026-01-01T00:00:00Z' },
  wework:     { id: 'ch_wework',     name: '企业微信',     type: 'wework',     channel_type: 'wework',     adapter_class: 'WecomAdapter',      enabled: true,  connected: true,  config: { corp_id: 'ww123456', secret: '***', agent_id: '1000002', kf_url: 'https://work.weixin.qq.com/kfid/kfcfd8a26b4a56f24ee', open_kfid: 'kfcfd8a26b4a56f24ee' }, message: '已连接', createdAt: '2026-01-01T00:00:00Z' },
  douyin:     { id: 'ch_douyin',     name: '抖音',         type: 'douyin',     channel_type: 'douyin',     adapter_class: 'DouyinAdapter',     enabled: false, connected: false, config: {}, message: '未连接', createdAt: '2026-01-01T00:00:00Z' },
  miniprogram:{ id: 'ch_miniprogram',name: '公众号/小程序', type: 'miniprogram',channel_type: 'miniprogram',adapter_class: 'MiniappAdapter',    enabled: false, connected: false, config: {}, message: '未连接', createdAt: '2026-01-01T00:00:00Z' },
  // 电商平台
  pdd:        { id: 'ch_pdd',        name: '拼多多',       type: 'pdd',        channel_type: 'pdd',        adapter_class: 'PddAdapter',        enabled: false, connected: false, config: {}, message: '未连接', createdAt: '2026-01-01T00:00:00Z' },
  taobao:     { id: 'ch_taobao',     name: '淘宝',         type: 'taobao',     channel_type: 'taobao',     adapter_class: 'TaobaoAdapter',     enabled: false, connected: false, config: {}, message: '未连接', createdAt: '2026-01-01T00:00:00Z' },
  jd:         { id: 'ch_jd',         name: '京东',         type: 'jd',         channel_type: 'jd',         adapter_class: 'JdAdapter',         enabled: false, connected: false, config: {}, message: '未连接', createdAt: '2026-01-01T00:00:00Z' },
  alibaba:    { id: 'ch_alibaba',    name: '1688',         type: 'alibaba',    channel_type: 'alibaba',    adapter_class: 'AlibabaAdapter',    enabled: false, connected: false, config: {}, message: '未连接', createdAt: '2026-01-01T00:00:00Z' },
  // 海外
  whatsapp:   { id: 'ch_whatsapp',   name: 'WhatsApp',     type: 'whatsapp',   channel_type: 'whatsapp',   adapter_class: 'WhatsappAdapter',   enabled: false, connected: false, config: {}, message: '未连接', createdAt: '2026-01-01T00:00:00Z' },
  telegram:   { id: 'ch_telegram',   name: 'Telegram',     type: 'telegram',   channel_type: 'telegram',   adapter_class: 'TelegramAdapter',   enabled: false, connected: false, config: {}, message: '未连接', createdAt: '2026-01-01T00:00:00Z' },
  line:       { id: 'ch_line',       name: 'LINE',         type: 'line',       channel_type: 'line',       adapter_class: 'LineAdapter',       enabled: false, connected: false, config: {}, message: '未连接', createdAt: '2026-01-01T00:00:00Z' },
  // 其他
  phone:      { id: 'ch_phone',      name: '电话',         type: 'phone',      channel_type: 'phone',      adapter_class: 'PhoneAdapter',      enabled: false, connected: false, config: {}, message: '未连接', createdAt: '2026-01-01T00:00:00Z' },
  email:      { id: 'ch_email',      name: '邮件',         type: 'email',      channel_type: 'email',      adapter_class: 'EmailAdapter',      enabled: true,  connected: true,  config: {}, message: '已连接', createdAt: '2026-01-01T00:00:00Z' },
  sms:        { id: 'ch_sms',        name: '短信',         type: 'sms',        channel_type: 'sms',        adapter_class: 'SmsAdapter',        enabled: false, connected: false, config: {}, message: '未连接', createdAt: '2026-01-01T00:00:00Z' },
  web:        { id: 'ch_web',        name: '网页',         type: 'web',        channel_type: 'web',        adapter_class: 'WebAdapter',        enabled: false, connected: false, config: {}, message: '未连接', createdAt: '2026-01-01T00:00:00Z' },
};

/* 每个渠道类型的必填配置字段（测试连接时校验） */
const channelRequiredFields: Record<string, string[]> = {
  wechat: ['app_id', 'app_secret'],
  wework: ['corp_id', 'secret', 'agent_id'],
  douyin: ['app_id', 'app_secret'],
  miniprogram: ['app_id', 'app_secret'],
  pdd: ['client_id', 'client_secret'],
  taobao: ['app_key', 'app_secret'],
  jd: ['app_key', 'app_secret'],
  alibaba: ['app_key', 'app_secret'],
  whatsapp: ['phone_number_id', 'access_token'],
  telegram: ['bot_token'],
  line: ['channel_access_token'],
  phone: ['line'],
};

/* -------- 帮助函数：构造一个 axios 兼容的响应 -------- */
function ok<T>(config: InternalAxiosRequestConfig, data: T): AxiosResponse<T> {
  return {
    data,
    status: 200,
    statusText: 'OK',
    headers: {},
    config,
    request: {},
  } as AxiosResponse<T>;
}

function notFound(config: InternalAxiosRequestConfig, msg = 'not found'): AxiosResponse<unknown> {
  return {
    data: { success: false, message: msg },
    status: 404,
    statusText: 'Not Found',
    headers: {},
    config,
    request: {},
  } as AxiosResponse<unknown>;
}

function badRequest(config: InternalAxiosRequestConfig, msg = '参数错误'): AxiosResponse<unknown> {
  return {
    data: { success: false, message: msg },
    status: 400,
    statusText: 'Bad Request',
    headers: {},
    config,
    request: {},
  } as AxiosResponse<unknown>;
}

/** 简单本地 intent 识别（关键词命中） */
function detectIntent(text: string) {
  const t = text || '';
  const rules: Array<{ regex: RegExp; intent: string; keywords: string[] }> = [
    { regex: /价格|多少(钱|费用)|报价|便宜|贵|预算/i, intent: '价格咨询', keywords: ['价格', '报价'] },
    { regex: /功能|能做|支持|怎么用|怎么操作/i, intent: '功能了解', keywords: ['功能'] },
    { regex: /试用|体验|试试|演示|demo/i, intent: '试用申请', keywords: ['试用'] },
    { regex: /老板|决策|领导|采购|选型|对比/i, intent: '采购决策', keywords: ['采购', '决策'] },
    { regex: /不(太|想)?要|不需要|算了|没兴趣/i, intent: '拒绝/暂缓', keywords: ['拒绝'] },
    { regex: /好|可以|行|同意|签|可以/i, intent: '积极回应', keywords: ['积极'] },
  ];
  for (const r of rules) {
    if (r.regex.test(t)) {
      return {
        intent: r.intent,
        confidence: 0.82,
        keywords: r.keywords,
        sentiment: r.intent === '拒绝/暂缓' ? 'negative' : r.intent === '积极回应' ? 'positive' : 'neutral',
        suggestion:
          r.intent === '价格咨询'
            ? '建议先确认客户预算区间，再发对应档位报价单。'
            : r.intent === '采购决策'
              ? '可推进到「报价」阶段，约 15 分钟产品演示。'
              : r.intent === '拒绝/暂缓'
                ? '礼貌回应，3 个月后再次激活。'
                : '保持节奏，主动给一两个相关案例。',
      };
    }
  }
  return {
    intent: '一般咨询',
    confidence: 0.55,
    keywords: [],
    sentiment: 'neutral',
    suggestion: '建议主动询问客户核心业务场景。',
  };
}

/** 推荐话术 */
function suggestReplies(text: string) {
  const t = text || '';
  if (/价格|便宜|预算|贵/i.test(t)) {
    return {
      replies: [
        '理解您的考虑。我们有按坐席阶梯定价的方案，方便的话我先发您看看？',
        '我们最近正好有老客户续费折扣活动，您这边方便聊 5 分钟吗？',
        '可以先按月试用，跑通流程后再决定长期方案。',
      ],
    };
  }
  if (/试用|体验|demo|演示/i.test(t)) {
    return {
      replies: [
        '没问题，我帮您申请 14 天免费试用，您看从哪天开始比较方便？',
        '我先发您一个 demo 链接，您可以先体验一下核心功能。',
      ],
    };
  }
  if (/老板|采购|选型|对比|决策/i.test(t)) {
    return {
      replies: [
        '完全理解。如果方便，我们可以一起和您老板开个 30 分钟的会，把 ROI 算清楚。',
        '我们整理了一份和同类产品的对比表，方便发给您内部参考。',
      ],
    };
  }
  return {
    replies: [
      '好的，那我就您关心的部分整理一下，稍后发您。',
      '方便问一下，目前这块是您自己主导，还是需要和团队一起评估？',
      '明白了，我先把相关资料整理好发您，您有空的时候看看。',
    ],
  };
}

/* =========================================================
 *  主拦截器
 * ========================================================= */
export const mockAdapter: AxiosAdapter = async (config) => {
  const method = (config.method || 'get').toLowerCase();
  const url = (config.url || '').replace(/^https?:\/\/[^/]+/, ''); // 去掉 baseURL
  const params = config.params;
  const data = config.data ? safeJson(config.data) : undefined;
  const sendDelay = (): Promise<void> => new Promise((r) => setTimeout(r, 200 + Math.random() * 250));

  /* ----- 鉴权（mock 模式下任意密码都通过） ----- */
  if (url === '/api/kellai/auth/login' && method === 'post') {
    await sendDelay();
    const email = (data?.email || data?.phone || '').toString().trim();
    if (!email) {
      return ok(config, { success: false, message: '请输入邮箱或手机号' });
    }
    const user = buildMockUser(email);
    return ok(config, {
      success: true,
      access_token: 'mock-token-' + Date.now(),
      refresh_token: 'mock-refresh-' + Date.now(),
      access_expires_at: new Date(Date.now() + 3600 * 1000).toISOString(),
      refresh_expires_at: new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString(),
      user,
    });
  }

  if (url === '/api/kellai/auth/me' && method === 'get') {
    await sendDelay();
    const userStr = typeof window !== 'undefined' ? localStorage.getItem('auth_user') : null;
    if (userStr) {
      try {
        return ok(config, { success: true, data: JSON.parse(userStr) });
      } catch {
        // ignore
      }
    }
    return ok(config, { success: true, data: buildMockUser('test@kellai.com') });
  }

  if (url === '/api/kellai/auth/qr/start' && method === 'post') {
    await sendDelay();
    const sessionId = `mock_qr_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    const secret = Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
    const expiresAt = Date.now() + MOCK_QR_LOGIN_TTL_MS;
    mockQrLoginSessions[sessionId] = {
      secret,
      status: 'waiting',
      expiresAt,
    };
    const origin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:5173';
    const query = new URLSearchParams({ qr_session: sessionId, qr_secret: secret });
    return ok(config, {
      success: true,
      data: {
        session_id: sessionId,
        secret,
        login_url: `${origin}/login?${query.toString()}`,
        expires_in: Math.floor(MOCK_QR_LOGIN_TTL_MS / 1000),
        expires_at: Math.floor(expiresAt / 1000),
      },
    });
  }

  if (url === '/api/kellai/auth/qr/status' && method === 'get') {
    await sendDelay();
    const sessionId = String(params?.session_id || '');
    const session = mockQrLoginSessions[sessionId];
    if (!session || session.expiresAt <= Date.now()) {
      if (session) delete mockQrLoginSessions[sessionId];
      return ok(config, { success: true, data: { status: 'expired', expired: true } });
    }
    return ok(config, {
      success: true,
      data: {
        status: session.status,
        scanned: session.status === 'scanned' || session.status === 'authorized',
        authorized: session.status === 'authorized',
        expired: false,
        expires_in: Math.max(0, Math.floor((session.expiresAt - Date.now()) / 1000)),
        user: session.user,
        login: session.login,
        error: session.error,
      },
    });
  }

  if (url === '/api/kellai/auth/qr/scan' && method === 'post') {
    await sendDelay();
    const sessionId = String(data?.session_id || '');
    const secret = String(data?.secret || '');
    const session = mockQrLoginSessions[sessionId];
    if (!session || session.expiresAt <= Date.now()) {
      return ok(config, { success: false, error: '二维码已过期' });
    }
    if (session.secret !== secret) {
      return ok(config, { success: false, error: '二维码无效' });
    }
    if (session.status === 'waiting') session.status = 'scanned';
    return ok(config, { success: true, data: { status: session.status } });
  }

  if (url === '/api/kellai/auth/qr/confirm' && method === 'post') {
    await sendDelay();
    const sessionId = String(data?.session_id || '');
    const secret = String(data?.secret || '');
    const session = mockQrLoginSessions[sessionId];
    if (!session || session.expiresAt <= Date.now()) {
      return ok(config, { success: false, error: '二维码已过期' });
    }
    if (session.secret !== secret) {
      return ok(config, { success: false, error: '二维码无效' });
    }
    const userStr = typeof window !== 'undefined' ? localStorage.getItem('auth_user') : null;
    let user = buildMockUser('test@kellai.com');
    if (userStr) {
      try {
        user = JSON.parse(userStr);
      } catch {
        // keep default user
      }
    }
    session.user = user;
    session.login = {
      success: true,
      access_token: 'mock-qr-token-' + Date.now(),
      refresh_token: 'mock-qr-refresh-' + Date.now(),
      access_expires_at: new Date(Date.now() + 3600 * 1000).toISOString(),
      refresh_expires_at: new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString(),
      user,
    };
    session.status = 'authorized';
    return ok(config, { success: true, data: { status: 'authorized', user } });
  }

  if (url === '/api/kellai/auth/qr/cancel' && method === 'post') {
    await sendDelay();
    const sessionId = String(data?.session_id || '');
    const secret = String(data?.secret || '');
    const session = mockQrLoginSessions[sessionId];
    if (!session) return ok(config, { success: true, data: { status: 'expired' } });
    if (session.secret !== secret) {
      return ok(config, { success: false, error: '二维码无效' });
    }
    session.status = 'canceled';
    session.error = '用户已取消';
    return ok(config, { success: true, data: { status: 'canceled' } });
  }

  /* 发送短信验证码（mock：固定 123456，并在响应里回带便于联调） */
  if (url === '/api/kellai/auth/sms/send' && method === 'post') {
    await sendDelay();
    const phone = String(data?.phone || '').trim();
    if (!/^1[3-9]\d{9}$/.test(phone)) {
      return ok(config, { success: false, error: '手机号格式不正确' });
    }
    mockSmsCodes[phone] = '123456';
    return ok(config, { success: true, message: '验证码已发送（mock：123456）', code: '123456' });
  }

  /* 找回密码（mock：校验验证码后即成功） */
  if (url === '/api/kellai/auth/forgot-password' && method === 'post') {
    await sendDelay();
    const phone = String(data?.phone || '').trim();
    const code = String(data?.code || '').trim();
    const pwd = String(data?.new_password || '');
    if (!/^1[3-9]\d{9}$/.test(phone)) return badRequest(config, '手机号格式不正确');
    if (pwd.length < 6 || !/[A-Za-z]/.test(pwd) || !/\d/.test(pwd)) {
      return badRequest(config, '密码至少 6 位且需包含字母和数字');
    }
    const expected = mockSmsCodes[phone];
    if (!expected || expected !== code) return badRequest(config, '验证码无效或已过期');
    delete mockSmsCodes[phone];
    return ok(config, { success: true, message: '密码已重置，请使用新密码登录' });
  }

  if (url === '/api/kellai/auth/register' && method === 'post') {
    await sendDelay();
    const email = (data?.email || '').toString().trim();
    if (!email) {
      return ok(config, { success: false, message: '请输入邮箱' });
    }
    const user = buildMockUser(email, data?.name);
    return ok(config, {
      success: true,
      access_token: 'mock-token-' + Date.now(),
      refresh_token: 'mock-refresh-' + Date.now(),
      access_expires_at: new Date(Date.now() + 3600 * 1000).toISOString(),
      refresh_expires_at: new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString(),
      user,
    });
  }

  /* ----- 漏斗 ----- */
  if (url === '/api/kellai/pipeline/funnel' && method === 'get') {
    await sendDelay();
    return ok(config, { success: true, data: { stages: getMockFunnelStages(), stage_definitions: [] } });
  }

  if (url === '/api/kellai/pipeline/query' && method === 'get') {
    await sendDelay();
    const stage = params?.stage;
    const stages = getMockFunnelStages();
    const filtered = stage
      ? stages.flatMap((s) => (s.id === stage ? s.clients : []))
      : stages.flatMap((s) => s.clients);
    return ok(config, { success: true, data: { pipelines: filtered, total: filtered.length } });
  }

  if (url === '/api/kellai/pipeline' && method === 'get') {
    await sendDelay();
    const cid = Number(params?.customer_id);
    const c = MOCK_CUSTOMERS.find((x) => x.customer_id === cid);
    if (!c) return notFound(config, '客户不存在');
    const pipelineDoc = {
        customer_id: c.customer_id,
        username: c.username,
        display_name: c.display_name,
        stage: stageMap.get(cid) || c.stage,
        stage_label: c.stage_label,
        ai_score: c.ai_score,
        ai_tags: c.ai_tags,
        channel_sources: c.channel_sources,
        intake_sent: c.intake_sent,
        last_message_preview: c.last_message_preview,
        created_at: '2026-05-01T00:00:00Z',
        updated_at: c.updated_at,
      };
    return ok(config, {
      success: true,
      data: {
        pipeline: pipelineDoc,
        stages: [],
        advanced: false,
        crm: {},
      },
    });
  }

  /* POST /api/kellai/pipeline/stage —— 漏斗拖卡片 */
  if (url === '/api/kellai/pipeline/stage' && method === 'post') {
    await sendDelay();
    const cid = Number(data?.customer_id);
    const stage = String(data?.stage || '');
    if (cid && stage) {
      stageMap.set(cid, stage);
      const c = setMockCustomerStage(cid, stage);
      return ok(config, { success: true, data: { pipeline: { customer_id: cid, stage, stage_label: c?.stage_label || stage } } });
    }
    return badRequest(config, '参数错误');
  }

  /* PUT /api/kellai/pipeline/customer/:id/stage —— 教程用 */
  const m = url.match(/^\/api\/kellai\/pipeline\/customer\/(\d+)\/stage$/);
  if (m && method === 'put') {
    await sendDelay();
    const cid = Number(m[1]);
    const stage = String(data?.stage_id || '');
    if (cid && stage) {
      stageMap.set(cid, stage);
      const c = setMockCustomerStage(cid, stage);
      return ok(config, { success: true, data: { pipeline: { customer_id: cid, stage, stage_label: c?.stage_label || stage } } });
    }
    return badRequest(config, '参数错误');
  }

  /* ----- 消息 ----- */
  if (url === '/api/kellai/messages' && method === 'get') {
    await sendDelay();
    const cid = params?.customer_id ? Number(params.customer_id) : undefined;
    if (cid) {
      return ok(config, { success: true, data: messageStore[cid] || [] });
    }
    // 团队级：合并所有客户
    const all = Object.values(messageStore).flat();
    return ok(config, { success: true, data: all });
  }

  if (url === '/api/kellai/messages/send' && method === 'post') {
    await sendDelay();
    const cid = Number(data?.customer_id);
    if (cid) {
      const newMsg = {
        id: `${cid}-user-${Date.now()}`,
        customer_id: cid,
        channel_type: String(data?.channel_type || 'wework'),
        contact_id: String(data?.contact_id || ''),
        direction: 'outbound' as const,
        content: String(data?.content || ''),
        created_at: new Date().toISOString(),
      };
      messageStore[cid] = [...(messageStore[cid] || []), newMsg];
      return ok(config, { success: true, data: { message_id: newMsg.id, channel_result: { success: true } } });
    }
    return notFound(config);
  }

  if (url === '/api/kellai/messages/mark-read' && method === 'post') {
    await sendDelay();
    // 真正把已读状态写回 messageStore，避免轮询拿到旧数据导致红点又冒出来
    let updated = 0;
    if (data?.all) {
      for (const cid of Object.keys(messageStore)) {
        const list = messageStore[Number(cid)] || [];
        for (const m of list) {
          if (m.direction === 'inbound' && !(m as { read?: boolean }).read) {
            (m as { read?: boolean }).read = true;
            updated += 1;
          }
        }
      }
    } else if (data?.customer_id !== undefined) {
      const cid = Number(data.customer_id);
      const list = messageStore[cid] || [];
      for (const m of list) {
        if (m.direction === 'inbound' && !(m as { read?: boolean }).read) {
          (m as { read?: boolean }).read = true;
          updated += 1;
        }
      }
    } else if (Array.isArray(data?.message_ids) && data.message_ids.length > 0) {
      const ids = new Set<string>(data.message_ids as string[]);
      for (const cid of Object.keys(messageStore)) {
        const list = messageStore[Number(cid)] || [];
        for (const m of list) {
          if (ids.has(m.id) && !(m as { read?: boolean }).read) {
            (m as { read?: boolean }).read = true;
            updated += 1;
          }
        }
      }
    }
    return ok(config, { success: true, data: { updated } });
  }

  if (url === '/api/kellai/messages/unread-count' && method === 'get') {
    await sendDelay();
    // 按当前 messageStore 真实状态计算未读，mark-read 后这里也会同步归零
    const byCustomer: Record<string, number> = {};
    let total = 0;
    for (const cid of Object.keys(messageStore)) {
      const list = messageStore[Number(cid)] || [];
      const n = list.filter(
        (m) => m.direction === 'inbound' && !(m as { read?: boolean }).read
      ).length;
      if (n > 0) byCustomer[cid] = n;
      total += n;
    }
    return ok(config, {
      success: true,
      data: { total, by_customer: byCustomer },
    });
  }

  /* ----- AI ----- */
  if (url === '/api/kellai/ai/intent' && method === 'post') {
    await sendDelay();
    return ok(config, { success: true, data: detectIntent(String(data?.message || '')) });
  }

  if (url === '/api/kellai/ai/suggest-reply' && method === 'post') {
    await sendDelay();
    const r = suggestReplies(String(data?.message || ''));
    return ok(config, { success: true, data: { suggestions: r.replies } });
  }

  if (url === '/api/kellai/ai/auto-reply' && method === 'post') {
    await sendDelay();
    const r = suggestReplies(String(data?.message || ''));
    return ok(config, { success: true, data: { draft: r.replies[0] } });
  }

  const aiProfileMatch = url.match(/^\/api\/kellai\/ai\/profile\/(\d+)$/);
  if (aiProfileMatch && method === 'get') {
    await sendDelay();
    const cid = Number(aiProfileMatch[1]);
    const p = getMockAiProfile(cid);
    if (!p) return notFound(config, '客户不存在');
    return ok(config, { success: true, data: p });
  }

  const insightMatch = url.match(/^\/api\/kellai\/ai\/operating-insight\/(\d+)$/);
  if (insightMatch && method === 'get') {
    await sendDelay();
    const cid = Number(insightMatch[1]);
    const customer = MOCK_CUSTOMERS.find((item) => item.customer_id === cid);
    if (!customer) return notFound(config, '客户不存在');
    const messages = messageStore[cid] ?? getMockMessages(cid);
    return ok(config, {
      success: true,
      data: {
        customer_id: cid,
        memory_summary: `${customer.display_name} 当前处于 ${stageLabelOf(customer.stage)} 阶段；已打通渠道：${(customer.channel_sources || []).join(' / ') || '暂无'}；最近消息：${messages[messages.length - 1]?.content || '暂无'}`,
        channel_sources: customer.channel_sources || [],
        channel_contacts: { [customer.channel_sources?.[0] || 'wework']: customer.contact_id || `mock_${cid}` },
        last_inbound_preview: messages.filter((msg) => msg.direction === 'inbound').slice(-1)[0]?.content || '',
        risk_signals: [
          { key: 'price_objection', label: '价格异议', matched: '预算、报价' },
        ],
        management_insights: [
          { key: 'omnichannel_one_id', label: '跨渠道 One ID 已形成', value: (customer.channel_sources || []).join(' / ') },
          { key: 'pricing_signal', label: '价格敏感客户', value: '准备阶梯套餐' },
          { key: 'active_customer', label: '客户多轮主动咨询', value: `${messages.filter((msg) => msg.direction === 'inbound').length} 轮入站消息` },
        ],
        active_task: '跟进报价反馈，处理异议',
        pending_follow_up: true,
        ai_score: customer.ai_score,
        message_count: messages.length,
      },
    });
  }

  const qualityMatch = url.match(/^\/api\/kellai\/ai\/quality-inspection\/(\d+)$/);
  if (qualityMatch && method === 'get') {
    await sendDelay();
    const cid = Number(qualityMatch[1]);
    const customer = MOCK_CUSTOMERS.find((item) => item.customer_id === cid);
    if (!customer) return notFound(config, '客户不存在');
    const messages = messageStore[cid] ?? getMockMessages(cid);
    const inbound = messages.filter((msg) => msg.direction === 'inbound');
    const outbound = messages.filter((msg) => msg.direction === 'outbound');
    const risky = inbound.some((msg) => /投诉|差评|退款|不满意|太慢/.test(msg.content));
    return ok(config, {
      success: true,
      data: {
        customer_id: cid,
        customer_name: customer.display_name,
        score: risky ? 62 : 86,
        grade: risky ? 'C' : 'B',
        review_required: risky,
        risk_level: risky ? 'high' : 'low',
        message_count: messages.length,
        inbound_count: inbound.length,
        outbound_count: outbound.length,
        response_coverage: inbound.length ? Math.min(1, outbound.length / inbound.length) : 1,
        unanswered_inbound: inbound.length > outbound.length,
        failed_rules: risky
          ? [
              { key: 'negative_sentiment', label: '客户负面情绪', severity: 'high', matched: '投诉、退款' },
              { key: 'handoff_required', label: '需要人工/主管介入', severity: 'medium', matched: '主管' },
            ]
          : [],
        recommendations: risky
          ? ['优先安抚客户，承认问题并给出明确处理时限。', '生成主管待办，并把客户诉求、最近消息和风险原因带过去。']
          : ['当前会话无明显质检风险，保持标准回复节奏并继续沉淀知识库。'],
        manager_report: {
          summary: `${customer.display_name} 质检得分 ${risky ? 62 : 86}，共检查 ${messages.length} 条消息。`,
          suggested_action: risky ? '主管介入复盘话术并安排补救跟进' : '继续自动跟进并抽样复查',
          risk_level: risky ? 'high' : 'low',
        },
      },
    });
  }

  const serviceTicketListMatch = url.match(/^\/api\/kellai\/ai\/service-tickets\/(\d+)$/);
  if (serviceTicketListMatch && method === 'get') {
    await sendDelay();
    const cid = Number(serviceTicketListMatch[1]);
    const tickets = mockServiceTickets[cid] ?? [];
    const sorted = [...tickets].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
    const open = sorted.filter((item) => item.status !== 'resolved');
    return ok(config, {
      success: true,
      data: {
        customer_id: cid,
        total: sorted.length,
        open: open.length,
        resolved: sorted.length - open.length,
        latest: sorted[0] ?? null,
        tickets: sorted,
      },
    });
  }

  if (url === '/api/kellai/ai/service-tickets' && method === 'post') {
    await sendDelay();
    const cid = Number(data?.customer_id || 0);
    if (!cid) return notFound(config, '客户不存在');
    const now = new Date().toISOString();
    const ticket = {
      id: `mock_ticket_${Date.now()}`,
      customer_id: cid,
      title: String(data?.title || '主管介入：客服质检高风险'),
      status: 'open',
      priority: String(data?.priority || 'urgent'),
      risk_level: 'high',
      assignee: String(data?.assignee || ''),
      reason: 'Mock 质检命中高风险，需要主管复核。',
      recommendations: ['优先安抚客户，承认问题并给出明确处理时限。', '删除绝对化承诺，改为明确交付条件和时间边界。'],
      due_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
      ai_rehost_action: '',
      created_at: now,
      updated_at: now,
      events: [{ action: 'created', actor: 'mock', at: now }],
    };
    mockServiceTickets[cid] = [ticket, ...(mockServiceTickets[cid] ?? [])];
    return ok(config, { success: true, data: ticket });
  }

  const ticketAssignMatch = url.match(/^\/api\/kellai\/ai\/service-tickets\/([^/]+)\/assign$/);
  if (ticketAssignMatch && method === 'post') {
    await sendDelay();
    const ticketId = ticketAssignMatch[1];
    for (const tickets of Object.values(mockServiceTickets)) {
      const ticket = tickets.find((item) => item.id === ticketId);
      if (!ticket) continue;
      ticket.status = 'assigned';
      ticket.assignee = String(data?.assignee || '质检主管');
      ticket.updated_at = new Date().toISOString();
      ticket.events.push({ action: 'assigned', actor: 'mock', at: ticket.updated_at });
      return ok(config, { success: true, data: ticket });
    }
    return notFound(config, '工单不存在');
  }

  const ticketResolveMatch = url.match(/^\/api\/kellai\/ai\/service-tickets\/([^/]+)\/resolve$/);
  if (ticketResolveMatch && method === 'post') {
    await sendDelay();
    const ticketId = ticketResolveMatch[1];
    for (const tickets of Object.values(mockServiceTickets)) {
      const ticket = tickets.find((item) => item.id === ticketId);
      if (!ticket) continue;
      ticket.status = 'resolved';
      ticket.resolution = String(data?.resolution || '已处理');
      ticket.resolved_at = new Date().toISOString();
      ticket.updated_at = ticket.resolved_at;
      ticket.ai_rehost_action = '主管已处理高风险会话，AI 可继续按合规话术跟进客户下一步。';
      ticket.events.push({ action: 'resolved', actor: 'mock', at: ticket.updated_at });
      ticket.events.push({ action: 'rehosted_to_ai', actor: 'mock', at: ticket.updated_at });
      return ok(config, { success: true, data: ticket });
    }
    return notFound(config, '工单不存在');
  }

  const serviceLearningMatch = url.match(/^\/api\/kellai\/ai\/service-learning\/(\d+)$/);
  if (serviceLearningMatch && (method === 'get' || method === 'post')) {
    await sendDelay();
    const cid = Number(serviceLearningMatch[1]);
    const customer = MOCK_CUSTOMERS.find((item) => item.customer_id === cid);
    if (!customer) return notFound(config, '客户不存在');
    const messages = messageStore[cid] ?? getMockMessages(cid);
    const tickets = mockServiceTickets[cid] ?? [];
    const resolvedTickets = tickets.filter((item) => item.status === 'resolved');
    const article = {
      id: `service_learning_${cid}`,
      title: `服务复盘：${customer.display_name}`,
      content: '把质检规则、主管处理结论和 AI 回托口径沉淀成客服知识库 SOP。',
      tags: ['服务复盘', '质检', '工单', '合规', '回托AI'],
      source: 'service_learning',
      updated_at: new Date().toISOString(),
    };
    if (method === 'post') {
      mockServiceLearning[cid] = article;
    }
    const persistedArticle = mockServiceLearning[cid] ?? null;
    return ok(config, {
      success: true,
      data: {
        customer_id: cid,
        customer_name: customer.display_name,
        generated_at: new Date().toISOString(),
        persisted: Boolean(persistedArticle),
        passed: Boolean(persistedArticle) && messages.length > 0,
        metrics: {
          inspected_conversations: messages.length,
          inbound_count: messages.filter((msg) => msg.direction === 'inbound').length,
          outbound_count: messages.filter((msg) => msg.direction === 'outbound').length,
          quality_score: 82,
          response_coverage: 1,
          high_risk_cases: resolvedTickets.length ? 1 : 0,
          ticket_total: tickets.length,
          ticket_open: tickets.filter((item) => item.status !== 'resolved').length,
          ticket_resolved: resolvedTickets.length,
          ai_rehosted: tickets.filter((item) => item.ai_rehost_action).length,
          kb_articles_created: persistedArticle ? 1 : 0,
          top_risk_rules: resolvedTickets.length ? ['客户负面情绪', '需要人工/主管介入'] : [],
        },
        recommendations: [
          '将主管已确认的回托口径加入后续自动回复确认清单。',
          '把命中的高风险规则作为客服培训抽查项。',
        ],
        article: persistedArticle,
        article_preview: article,
        search_hits: persistedArticle ? [{ id: article.id, title: article.title, score: 1 }] : [],
      },
    });
  }

  const selfServiceMatch = url.match(/^\/api\/kellai\/ai\/self-service\/(\d+)$/);
  if (selfServiceMatch && method === 'get') {
    await sendDelay();
    const cid = Number(selfServiceMatch[1]);
    const customer = MOCK_CUSTOMERS.find((item) => item.customer_id === cid);
    if (!customer) return notFound(config, '客户不存在');
    const sessions = [...(mockSelfServiceSessions[cid] ?? [])].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
    const resolved = sessions.filter((item) => item.status === 'resolved');
    const handoff = sessions.filter((item) => item.status === 'handoff_required');
    return ok(config, {
      success: true,
      data: {
        customer_id: cid,
        total: sessions.length,
        resolved: resolved.length,
        handoff: handoff.length,
        resolution_rate: sessions.length ? resolved.length / sessions.length : 0,
        latest: sessions[0] ?? null,
        sessions,
      },
    });
  }

  if (selfServiceMatch && method === 'post') {
    await sendDelay();
    const cid = Number(selfServiceMatch[1]);
    const customer = MOCK_CUSTOMERS.find((item) => item.customer_id === cid);
    if (!customer) return notFound(config, '客户不存在');
    const now = new Date().toISOString();
    const query = String(data?.query || customer.last_message_preview || '企微接入和付款后交付怎么安排？');
    const matched = !/火星|硬件维修|离线探针|未知/.test(query);
    const session: any = {
      id: `mock_ssr_${Date.now()}`,
      customer_id: cid,
      customer_name: customer.display_name,
      query,
      channel_type: String(data?.channel_type || customer.channel_sources?.[0] || 'wework'),
      status: matched ? 'resolved' : 'handoff_required',
      matched,
      confidence: matched ? 0.92 : 0,
      answer: matched
        ? '可按知识库回复：企微接入需要提供客服链接或 open_kfid。付款后发送交付清单，并安排渠道配置和团队培训。'
        : '知识库暂未命中，请补充相关产品、价格、交付或售后知识后再回复客户。',
      sources: matched ? [{ id: 'mock_kb_wework_offer', title: '企微接入与首月优惠', score: 1 }] : [],
      message_ids: [`mock-ssr-${cid}-in`, ...(matched ? [`mock-ssr-${cid}-out`] : [])],
      ticket_id: '',
      next_action: matched ? 'AI 已按知识库完成自助解答。' : 'AI 未命中知识库，已生成转人工工单补充答案。',
      created_at: now,
      updated_at: now,
    };
    const inboundMessage = {
      id: session.message_ids[0],
      customer_id: cid,
      customer_name: customer.display_name,
      channel_type: session.channel_type,
      contact_id: customer.contact_id,
      direction: 'inbound' as const,
      content: query,
      read: false,
      created_at: now,
    } as ReturnType<typeof getMockMessages>[number] & { customer_name?: string; read?: boolean };
    const nextMessages = [inboundMessage, ...(messageStore[cid] ?? getMockMessages(cid))];
    if (matched) {
      nextMessages.unshift({
        id: session.message_ids[1],
        customer_id: cid,
        customer_name: customer.display_name,
        channel_type: session.channel_type,
        contact_id: customer.contact_id,
        direction: 'outbound' as const,
        content: `【AI自助解答】${session.answer}`,
        read: true,
        created_at: now,
      } as ReturnType<typeof getMockMessages>[number] & { customer_name?: string; read?: boolean });
    } else {
      const ticket = {
        id: `mock_ticket_ssr_${Date.now()}`,
        customer_id: cid,
        title: 'AI 自助未解决：转人工补充知识',
        status: 'open',
        priority: 'normal',
        risk_level: 'medium',
        assignee: '',
        reason: `客户问题未命中知识库：${query}`,
        recommendations: ['人工客服补充标准答案后沉淀到知识库。', '处理后回托 AI，后续同类问题自动自助解决。'],
        due_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
        ai_rehost_action: '',
        created_at: now,
        updated_at: now,
        events: [{ action: 'created', actor: 'mock', at: now }],
      };
      mockServiceTickets[cid] = [ticket, ...(mockServiceTickets[cid] ?? [])];
      session.ticket_id = ticket.id;
      session.ticket = ticket;
    }
    messageStore[cid] = nextMessages;
    customer.last_message_preview = query;
    customer.tags = Array.from(new Set([...(customer.tags ?? []), 'AI自助', matched ? '知识库命中' : '转人工补知识']));
    mockSelfServiceSessions[cid] = [session, ...(mockSelfServiceSessions[cid] ?? [])];
    return ok(config, { success: true, data: session });
  }

  const outboundCallsMatch = url.match(/^\/api\/kellai\/ai\/outbound-calls\/(\d+)$/);
  if (outboundCallsMatch && method === 'get') {
    await sendDelay();
    const cid = Number(outboundCallsMatch[1]);
    const customer = MOCK_CUSTOMERS.find((item) => item.customer_id === cid);
    if (!customer) return notFound(config, '客户不存在');
    const calls = [...(mockOutboundCalls[cid] ?? [])].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
    const completed = calls.filter((item) => item.status === 'completed');
    const phoneMessages = (messageStore[cid] ?? []).filter((msg) => msg.channel_type === 'phone');
    return ok(config, {
      success: true,
      data: {
        customer_id: cid,
        total: calls.length,
        planned: calls.length - completed.length,
        completed: completed.length,
        latest: calls[0] ?? null,
        calls,
        phone_message_count: phoneMessages.length,
      },
    });
  }

  if (url === '/api/kellai/ai/outbound-calls' && method === 'post') {
    await sendDelay();
    const cid = Number(data?.customer_id || 0);
    const customer = MOCK_CUSTOMERS.find((item) => item.customer_id === cid);
    if (!customer) return notFound(config, '客户不存在');
    const now = new Date().toISOString();
    const call = {
      id: `mock_call_${Date.now()}`,
      customer_id: cid,
      customer_name: customer.display_name,
      purpose: String(data?.purpose || 'follow_up'),
      status: 'planned',
      assignee: String(data?.assignee || 'AI外呼助手'),
      stage_label: stageLabelOf(stageMap.get(cid) || customer.stage),
      script: {
        opening: `您好，我是客来来 AI 外呼助手，想跟进 ${customer.display_name} 的方案和演示安排。`,
        context: `客户当前阶段：${stageLabelOf(stageMap.get(cid) || customer.stage)}`,
        key_points: ['确认需求', '预约演示', '发送方案报价'],
        close_next_action: '发送报价方案，按约定时间完成演示。',
      },
      transcript: [],
      summary: '',
      next_action: '发送报价方案，按约定时间完成演示。',
      created_at: now,
      updated_at: now,
    };
    mockOutboundCalls[cid] = [call, ...(mockOutboundCalls[cid] ?? [])];
    return ok(config, { success: true, data: call });
  }

  const outboundExecuteMatch = url.match(/^\/api\/kellai\/ai\/outbound-calls\/([^/]+)\/execute$/);
  if (outboundExecuteMatch && method === 'post') {
    await sendDelay();
    const callId = outboundExecuteMatch[1];
    for (const [cidText, calls] of Object.entries(mockOutboundCalls)) {
      const call = calls.find((item) => item.id === callId);
      if (!call) continue;
      if (call.status === 'completed') return ok(config, { success: true, data: call });
      const cid = Number(cidText);
      const customer = MOCK_CUSTOMERS.find((item) => item.customer_id === cid);
      if (!customer) return notFound(config, '客户不存在');
      const now = new Date().toISOString();
      const contactId = customer.contact_id || `mock_phone_${cid}`;
      const outboundMessage = {
        id: `${call.id}-outbound`,
        customer_id: cid,
        customer_name: customer.display_name,
        channel_type: 'phone',
        contact_id: contactId,
        direction: 'outbound' as const,
        content: `【AI外呼】${call.script?.opening || '您好，我是客来来 AI 外呼助手。'}`,
        read: true,
        created_at: now,
      } as ReturnType<typeof getMockMessages>[number] & { customer_name?: string; read?: boolean };
      const inboundMessage = {
        id: `${call.id}-inbound`,
        customer_id: cid,
        customer_name: customer.display_name,
        channel_type: 'phone',
        contact_id: contactId,
        direction: 'inbound' as const,
        content: '【电话纪要】客户愿意看演示，也需要方案和报价。下一步：发送报价方案，按约定时间完成演示。',
        intent: '演示邀约',
        ai_intent: '演示邀约',
        read: false,
        created_at: now,
      } as ReturnType<typeof getMockMessages>[number] & { customer_name?: string; ai_intent?: string; read?: boolean };
      messageStore[cid] = [outboundMessage, inboundMessage, ...(messageStore[cid] ?? getMockMessages(cid))];
      stageMap.set(cid, 'quoted');
      customer.stage = 'quoted';
      customer.stage_label = stageLabelOf('quoted');
      customer.channel_sources = Array.from(new Set([...(customer.channel_sources ?? []), 'phone']));
      customer.last_message_preview = inboundMessage.content;
      call.status = 'completed';
      call.outcome = String(data?.outcome || 'demo_booked');
      call.outcome_label = '已约演示';
      call.summary = '客户接受电话跟进并约定演示，需要发送方案和报价。';
      call.next_action = '发送报价方案，按约定时间完成演示。';
      call.duration_sec = 82;
      call.transcript = [
        { role: 'agent', content: call.script?.opening || '您好，我是客来来 AI 外呼助手。', at: now },
        { role: 'customer', content: '可以，我愿意看演示，也麻烦把方案和报价发我。', at: now },
        { role: 'agent', content: '收到，我会发送报价方案，按约定时间完成演示。', at: now },
      ];
      call.message_ids = [outboundMessage.id, inboundMessage.id];
      call.pipeline_stage_label = stageLabelOf('quoted');
      call.executed_at = now;
      call.updated_at = now;
      return ok(config, { success: true, data: call });
    }
    return notFound(config, '外呼任务不存在');
  }

  if (url === '/api/kellai/ai/knowledge-base' && method === 'get') {
    await sendDelay();
    return ok(config, { success: true, data: { articles: mockKnowledgeArticles } });
  }

  if (url === '/api/kellai/ai/knowledge-base' && method === 'post') {
    await sendDelay();
    const article = {
      id: String(data?.id || `mock_kb_${Date.now()}`),
      title: String(data?.title || '未命名知识'),
      content: String(data?.content || ''),
      tags: Array.isArray(data?.tags) ? data.tags.map(String) : [],
      source: String(data?.source || 'mock'),
      updated_at: new Date().toISOString(),
    };
    const index = mockKnowledgeArticles.findIndex((item) => item.id === article.id);
    if (index >= 0) mockKnowledgeArticles[index] = article;
    else mockKnowledgeArticles.push(article);
    return ok(config, { success: true, data: article });
  }

  if (url === '/api/kellai/ai/knowledge-base/suggest' && method === 'post') {
    await sendDelay();
    const query = String(data?.query || '');
    const hit = query.includes('企微') || query.includes('企业微信') || query.includes('优惠')
      ? mockKnowledgeArticles[0]
      : mockKnowledgeArticles[0];
    return ok(config, {
      success: true,
      data: {
        answer: hit
          ? `可按知识库《${hit.title}》回复：${hit.content}`
          : '知识库暂未命中，请先沉淀标准答案。',
        matched: Boolean(hit),
        sources: hit ? [{ id: hit.id, title: hit.title, score: 1 }] : [],
        confidence: hit ? 1 : 0,
      },
    });
  }

  if (url === '/api/kellai/ai/reminders' && method === 'get') {
    await sendDelay();
    return ok(config, { success: true, data: { reminders: getMockReminders() } });
  }

  /* ----- 渠道 ----- */
  if (url === '/api/kellai/channels' && method === 'get') {
    await sendDelay();
    return ok(config, {
      success: true,
      data: Object.values(channelMockState),
    });
  }

  if (url === '/api/kellai/channels/wework/customer-entry' && method === 'get') {
    await sendDelay();
    const source = String(params?.source || 'settings');
    const targetUrl = String(channelMockState.wework.config.kf_url || '');
    const origin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:5173';
    const entryQuery = new URLSearchParams({ source });
    return ok(config, {
      success: Boolean(targetUrl),
      data: {
        entry_url: `${origin}/api/kellai/channels/wework/customer-entry?${entryQuery.toString()}`,
        target_url: targetUrl,
        source,
      },
      error: targetUrl ? '' : '请先配置企业微信客服接待链接或 open_kfid',
    });
  }

  const oauthInitMatch = url.match(/^\/api\/kellai\/channels\/(wechat|wework)\/oauth\/initiate$/);
  if (oauthInitMatch && method === 'post') {
    await sendDelay();
    const ctype = oauthInitMatch[1];
    return ok(config, {
      success: true,
      data: {
        url: `about:blank#mock-${ctype}-oauth`,
        state: `mock_${ctype}_${Date.now()}`,
        qr_proxy_url: ctype === 'wechat'
          ? 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22208%22 height=%22208%22 viewBox=%220 0 208 208%22%3E%3Crect width=%22208%22 height=%22208%22 fill=%22white%22/%3E%3Crect x=%2224%22 y=%2224%22 width=%2252%22 height=%2252%22 fill=%22%2307C160%22/%3E%3Crect x=%22132%22 y=%2224%22 width=%2252%22 height=%2252%22 fill=%22%2307C160%22/%3E%3Crect x=%2224%22 y=%22132%22 width=%2252%22 height=%2252%22 fill=%22%2307C160%22/%3E%3Crect x=%2292%22 y=%2292%22 width=%2220%22 height=%2220%22 fill=%22%2307C160%22/%3E%3Crect x=%22120%22 y=%22120%22 width=%2216%22 height=%2216%22 fill=%22%2307C160%22/%3E%3Crect x=%22152%22 y=%22148%22 width=%2212%22 height=%2212%22 fill=%22%2307C160%22/%3E%3Ctext x=%22104%22 y=%22198%22 text-anchor=%22middle%22 font-size=%2212%22 fill=%22%236b7280%22%3Emock wechat qr%3C/text%3E%3C/svg%3E'
          : '',
        expires_in: 300,
      },
    });
  }

  const oauthStatusMatch = url.match(/^\/api\/kellai\/channels\/(wechat|wework)\/oauth\/status$/);
  if (oauthStatusMatch && method === 'get') {
    await sendDelay();
    const ctype = oauthStatusMatch[1];
    const ch = channelMockState[ctype];
    if (ch) {
      ch.enabled = true;
      ch.connected = true;
      if (ctype === 'wechat') {
        ch.config = { ...ch.config, oauth_authorized: 'true', oauth_openid: 'mock_openid' };
      }
    }
    return ok(config, { success: true, data: { authorized: true, expired: false } });
  }

  /* LLM 状态（ai 命名空间） */
  if (url === '/api/kellai/ai/llm-status' && method === 'get') {
    await sendDelay();
    return ok(config, {
      success: true,
      data: mockLlmConfig,
    });
  }

  if (url === '/api/kellai/ai/llm-config' && method === 'put') {
    await sendDelay();
    const provider = String(data?.provider || mockLlmConfig.provider || 'deepseek');
    mockLlmConfig.provider = provider === 'auto' ? 'xcauto' : provider;
    mockLlmConfig.model = String(data?.model || mockLlmConfig.model || 'deepseek-chat');
    mockLlmConfig.base_url = String(data?.base_url || mockLlmConfig.base_url || 'https://api.deepseek.com/v1');
    mockLlmConfig.connected = true;
    mockLlmConfig.ready = true;
    mockLlmConfig.verified = true;
    mockLlmConfig.lastProbe = {
      success: true,
      connected: true,
      checked_at: new Date().toISOString(),
      provider: mockLlmConfig.provider,
      model: mockLlmConfig.model,
      latency_ms: 90,
      error: '',
    };
    mockLlmConfig.autoReplyEnabled = Boolean(data?.auto_reply_enabled ?? mockLlmConfig.autoReplyEnabled);
    if (Array.isArray(data?.auto_reply_stages)) mockLlmConfig.autoReplyStages = data.auto_reply_stages.map(String);
    if (Array.isArray(data?.confirm_scenarios)) mockLlmConfig.confirmScenarios = data.confirm_scenarios.map(String);
    mockLlmConfig.message = '配置已保存，Mock LLM 已就绪';
    return ok(config, { success: true, data: mockLlmConfig });
  }

  if (url === '/api/kellai/ai/llm-probe' && method === 'post') {
    await sendDelay();
    mockLlmConfig.connected = true;
    mockLlmConfig.ready = true;
    mockLlmConfig.verified = true;
    mockLlmConfig.lastProbe = {
      success: true,
      connected: true,
      checked_at: new Date().toISOString(),
      provider: mockLlmConfig.provider,
      model: mockLlmConfig.model,
      latency_ms: 88,
      error: '',
    };
    return ok(config, { success: true, data: { ...mockLlmConfig, probe: mockLlmConfig.lastProbe } });
  }

  if (url === '/api/kellai/demo/simulate-customer-behavior' && method === 'post') {
    await sendDelay();
    const count = Math.max(1, Math.min(Number(data?.count || 5), 8));
    const scenarios = [
      {
        key: 'late_price_inquiry',
        label: '夜间价格咨询',
        channel_type: 'douyin',
        name: '抖音-夜间咨询',
        company: '三店餐饮',
        content: '你们这个多少钱？我晚上刷到的，想看一下套餐和案例。',
        stage: 'submitted',
        score: 0.82,
        action: '发送三门店套餐和同城案例',
      },
      {
        key: 'repeat_customer_discount',
        label: '老客户复购优惠',
        channel_type: 'wechat',
        name: '微信-私域复购',
        company: '私域老客户',
        content: '之前买过一次，老客户还有优惠吗？合适的话这周再订。',
        stage: 'requirement',
        score: 0.74,
        action: '确认复购数量并给老客户折扣',
      },
      {
        key: 'form_submitted',
        label: '需求表已提交',
        channel_type: 'miniprogram',
        name: '小程序-留资客户',
        company: '小程序留资',
        content: '我已经提交需求表了，麻烦尽快给我一个方案。',
        stage: 'submitted',
        score: 0.86,
        action: '根据需求表生成方案并预约演示',
      },
      {
        key: 'price_sensitive_compare',
        label: '比价异议',
        channel_type: 'pdd',
        name: '拼多多-售前比价',
        company: '电商商家',
        content: '别家便宜一点，你们能不能优惠？有现货吗？',
        stage: 'requirement',
        score: 0.69,
        action: '解释差异价值并给限时方案',
      },
      {
        key: 'contract_urgent',
        label: '签约交付追问',
        channel_type: 'wework',
        name: '企微-签约推进',
        company: '连锁服务商',
        content: '合同怎么签？如果今天付款多久能开始交付？',
        stage: 'pending_sign',
        score: 0.9,
        action: '发送合同和交付排期',
      },
      {
        key: 'paid_delivery',
        label: '付款后交付',
        channel_type: 'wework',
        name: '企微-付款客户',
        company: '已付款客户',
        content: '合同确认了，已经付款了，发我交付清单吧。',
        stage: 'signed',
        score: 0.95,
        action: '发送交付清单并安排上线培训',
      },
      {
        key: 'social_link_request',
        label: '社媒求链接',
        channel_type: 'xiaohongshu',
        name: '小红书-求链接',
        company: '社媒访客',
        content: '怎么买呀？求链接，可以加微信详细说吗？',
        stage: 'requirement',
        score: 0.71,
        action: '引导加微信并收集需求',
      },
      {
        key: 'low_intent_noise',
        label: '低意向闲聊',
        channel_type: 'douyin',
        name: '抖音-围观用户',
        company: '围观访客',
        content: '先收藏了，回头看看，你们页面做得还不错。',
        stage: 'connected',
        score: 0.42,
        action: '轻量触达并延后跟进',
      },
    ].slice(0, count);
    const now = new Date().toISOString();
    const inboxIds: string[] = [];
    const scenarioResults = scenarios.map((scenario, idx) => {
      const storedChannel = scenario.channel_type === 'xiaohongshu' ? 'douyin' : scenario.channel_type;
      const rec = addMockCustomer({
        name: scenario.name,
        company: scenario.company,
        stage: scenario.stage,
        channel_sources: [storedChannel],
        tags: ['客户行为模拟', scenario.label],
      });
      rec.contact_id = `mock_sim_${scenario.key}_${rec.customer_id}`;
      rec.ai_score = scenario.score;
      rec.ai_tags = scenario.stage === 'signed' || scenario.stage === 'pending_sign'
        ? ['高意向', '成交推进']
        : ['客户行为模拟', '需跟进'];
      rec.last_message_preview = scenario.content;
      stageMap.set(rec.customer_id, scenario.stage);
      const messageId = `mock-sim-${rec.customer_id}-${idx}`;
      inboxIds.push(messageId);
      const inboundMessage = {
          id: messageId,
          customer_id: rec.customer_id,
          customer_name: rec.display_name,
          channel_type: storedChannel,
          contact_id: rec.contact_id,
          direction: 'inbound' as const,
          content: scenario.content,
          intent: scenario.label,
          ai_intent: scenario.label,
          read: false,
          created_at: now,
        } as ReturnType<typeof getMockMessages>[number] & { customer_name?: string; ai_intent?: string; read?: boolean };
      const outboundMessage = {
          id: `${messageId}-reply`,
          customer_id: rec.customer_id,
          customer_name: rec.display_name,
          channel_type: storedChannel,
          contact_id: rec.contact_id,
          direction: 'outbound' as const,
          content: scenario.action,
          read: true,
          created_at: now,
        } as ReturnType<typeof getMockMessages>[number] & { customer_name?: string; read?: boolean };
      messageStore[rec.customer_id] = [inboundMessage, outboundMessage];
      return {
        key: scenario.key,
        label: scenario.label,
        channel_type: scenario.channel_type,
        stored_channel: storedChannel,
        contact_id: rec.contact_id,
        customer_id: rec.customer_id,
        expected_stage: scenario.stage,
        final_stage: scenario.stage,
        stage_label: stageLabelOf(scenario.stage),
        ai_score: rec.ai_score,
        next_action: scenario.action,
        passed: true,
      };
    });
    return ok(config, {
      success: true,
      data: {
        created: scenarioResults.length,
        scenario_set: String(data?.scenario_set || 'mock'),
        inbox_message_ids: inboxIds,
        sync: { synced: scenarioResults.length, messages: [] },
        summary: {
          total: scenarioResults.length,
          passed: scenarioResults.length,
          failed: 0,
          synced: scenarioResults.length,
        },
        scenario_results: scenarioResults,
        passed: true,
      },
    });
  }

  if (url === '/api/kellai/demo/llm-full-flow-test' && method === 'post') {
    await sendDelay();
    const rec = addMockCustomer({
      name: 'LLM-抖音闭环客户',
      company: '连锁餐饮门店',
      stage: 'signed',
      channel_sources: ['douyin'],
      tags: ['LLM闭环', '已成交'],
    });
    rec.contact_id = `mock_llm_${rec.customer_id}`;
    rec.ai_score = 0.93;
    rec.ai_tags = ['高意向', '价格敏感', '已成交'];
    rec.last_message_preview = '合同确认了，已经付款，麻烦发我交付清单。';
    stageMap.set(rec.customer_id, 'signed');
    const now = new Date().toISOString();
    messageStore[rec.customer_id] = [
      {
        id: `mock-llm-${rec.customer_id}-1`,
        customer_id: rec.customer_id,
        channel_type: 'douyin',
        contact_id: rec.contact_id,
        direction: 'inbound',
        content: '你们这个怎么收费？我想把抖音和企微线索都接起来。',
        created_at: now,
      },
      {
        id: `mock-llm-${rec.customer_id}-2`,
        customer_id: rec.customer_id,
        channel_type: 'douyin',
        contact_id: rec.contact_id,
        direction: 'outbound',
        content: '我先按你的渠道和消息量给一版方案和报价，首周完成配置和培训。',
        created_at: now,
      },
      {
        id: `mock-llm-${rec.customer_id}-3`,
        customer_id: rec.customer_id,
        channel_type: 'douyin',
        contact_id: rec.contact_id,
        direction: 'inbound',
        content: '合同确认了，已经付款，麻烦发我交付清单。',
        created_at: now,
      },
    ];
    return ok(config, {
      success: true,
      data: {
        simulation_id: `mock-${rec.customer_id}`,
        mode: 'llm',
        llm_ready: true,
        llm_used: true,
        llm_customer_turns: 3,
        llm_agent_turns: 3,
        provider: mockLlmConfig.provider,
        model: mockLlmConfig.model,
        customer_id: rec.customer_id,
        contact_id: rec.contact_id,
        contact_name: rec.display_name,
        channel_type: 'douyin',
        turns_run: 3,
        target_stage: String(data?.target_stage || 'signed'),
        target_stage_label: '已签',
        final_stage: 'signed',
        final_stage_label: '已签',
        ai_score: rec.ai_score,
        next_action: '发送交付清单并安排上线培训',
        passed: true,
        failure_reason: '',
        summary: 'Mock LLM 客户完成 3 轮消息，最终阶段：已签，测试通过。',
        assertions: [
          { key: 'customer_created', label: '已自动建客户', passed: true, required: true },
          { key: 'llm_customer_generated', label: 'LLM 已生成客户行为', passed: true, required: true },
          { key: 'llm_agent_replied', label: 'LLM 已生成销售回复', passed: true, required: true, value: 3 },
          { key: 'target_stage_reached', label: '漏斗已到达已签', passed: true, required: true, value: 'signed' },
        ],
        events: messageStore[rec.customer_id],
      },
    });
  }

  if (url === '/api/kellai/demo/closed-loop-audit' && method === 'post') {
    await sendDelay();
    const rec = addMockCustomer({
      name: '闭环验收客户',
      company: '本地连锁餐饮',
      stage: 'signed',
      channel_sources: ['douyin', 'wework'],
      tags: ['闭环验收', '已成交'],
    });
    rec.contact_id = `mock_audit_${rec.customer_id}`;
    rec.ai_score = 0.91;
    rec.ai_tags = ['高意向', '已成交'];
    stageMap.set(rec.customer_id, 'signed');
    return ok(config, {
      success: true,
      data: {
        audit_id: `mock-audit-${rec.customer_id}`,
        passed: true,
        require_llm: Boolean(data?.require_llm ?? true),
        target_stage: 'signed',
        target_stage_label: '已签',
        checked_at: new Date().toISOString(),
        summary: { total: 33, passed: 33, failed_required: 0, skipped_optional: 0 },
        llm_status: mockLlmConfig,
        benchmark_profile: {
          name: '红熊/黑熊 AI Agent 客服对标',
          summary: { total: 9, passed: 9, failed_required: 0, skipped_optional: 0 },
          failed_required_labels: [],
          dimensions: [
            { key: 'omnichannel_service', label: '全渠道统一接待', required: true, passed: true },
            { key: 'unified_memory', label: '跨渠道长期记忆', required: true, passed: true },
            { key: 'semantic_emotion_understanding', label: '复杂意图、情绪、风险识别', required: true, passed: true },
            { key: 'autonomous_execution', label: '主动执行、工单、回访闭环', required: true, passed: true },
            { key: 'knowledge_learning', label: '知识库沉淀与服务自学习', required: true, passed: true },
            { key: 'growth_revenue_ops', label: '获客、销售、经营增长闭环', required: true, passed: true },
            { key: 'open_business_integration', label: 'CRM、开放平台、Webhook 集成', required: true, passed: true },
            { key: 'multimodal_service', label: '文本、图片、语音多模态服务链路', required: true, passed: true },
            { key: 'real_llm_agent', label: '真实大模型 Agent 成交链路', required: true, passed: true },
          ],
        },
        audit_customer_id: rec.customer_id,
        failure_reason: '',
        checks: [
          { key: 'llm_ready', label: '真实 LLM 已连通', status: 'passed', passed: true, required: true },
          { key: 'customer_created', label: '客户已从消息自动建档', status: 'passed', passed: true, required: true },
          { key: 'messages_persisted', label: '入站/出站消息已入库', status: 'passed', passed: true, required: true },
          { key: 'pipeline_auto_progressed', label: '消息驱动漏斗自动推进', status: 'passed', passed: true, required: true },
          { key: 'ai_score_and_action', label: 'AI 意向分与下一步动作已生成', status: 'passed', passed: true, required: true },
          { key: 'memory_continuity_loop', label: '跨渠道客户记忆连续闭环', status: 'passed', passed: true, required: true },
          { key: 'agent_service_ops_loop', label: 'Agent 客服运营洞察闭环', status: 'passed', passed: true, required: true },
          { key: 'quality_inspection_loop', label: '客服质检、合规、主管复盘闭环', status: 'passed', passed: true, required: true },
          { key: 'human_handoff_ticket_loop', label: '人机协同转人工、工单、回托 AI 闭环', status: 'passed', passed: true, required: true },
          { key: 'service_learning_loop', label: '服务自学习、指标、知识沉淀闭环', status: 'passed', passed: true, required: true },
          { key: 'outbound_call_loop', label: 'AI 外呼、电话跟进、漏斗推进闭环', status: 'passed', passed: true, required: true },
          { key: 'self_service_resolution_loop', label: 'AI 自助解决、知识库回复、未命中转人工闭环', status: 'passed', passed: true, required: true },
          { key: 'agent_assist_autofill_loop', label: '坐席助手、知识推荐、风险提醒、自动填单闭环', status: 'passed', passed: true, required: true },
          { key: 'multimodal_service_loop', label: '多模态消息入库、识别摘要、服务上下文闭环', status: 'passed', passed: true, required: true },
          { key: 'ai_intent', label: 'AI 意图识别可用', status: 'passed', passed: true, required: true },
          { key: 'ai_replies', label: 'AI 推荐话术可用', status: 'passed', passed: true, required: true },
          { key: 'ai_profile', label: '客户画像可生成', status: 'passed', passed: true, required: true },
          { key: 'follow_up_reminder', label: '跟进提醒可生成', status: 'passed', passed: true, required: true },
          { key: 'manual_stage_update', label: '手动阶段变更可保存', status: 'passed', passed: true, required: true },
          { key: 'funnel_summary', label: '漏斗汇总可读取', status: 'passed', passed: true, required: true },
          { key: 'customer_list', label: '客户列表可读取', status: 'passed', passed: true, required: true },
          { key: 'sales_revenue_loop', label: '销售推进、报价、合同闭环', status: 'passed', passed: true, required: true },
          { key: 'customer_management_loop', label: '客户管理新增、编辑、批量、删除闭环', status: 'passed', passed: true, required: true },
          { key: 'llm_settings_loop', label: 'AI 设置保存、读回、探测、恢复闭环', status: 'passed', passed: true, required: true },
          { key: 'knowledge_base_loop', label: '知识库沉淀、检索、回复闭环', status: 'passed', passed: true, required: true },
          { key: 'content_growth_loop', label: '内容生成、投放、数据闭环', status: 'passed', passed: true, required: true },
          { key: 'scout_lead_loop', label: '公域线索发现、触达、转化闭环', status: 'passed', passed: true, required: true },
          { key: 'flow_automation_loop', label: '自动化流程创建、执行、Webhook 闭环', status: 'passed', passed: true, required: true },
          { key: 'finance_decision_loop', label: '财务看板、问答、预算、决策闭环', status: 'passed', passed: true, required: true },
          { key: 'open_platform_loop', label: '开放平台密钥、插件、Webhook 闭环', status: 'passed', passed: true, required: true },
          { key: 'channel_onboarding_loop', label: '渠道接入配置、测试、断开闭环', status: 'passed', passed: true, required: true },
          { key: 'llm_full_flow', label: 'LLM 客户行为到签约闭环', status: 'passed', passed: true, required: true },
          { key: 'redbear_benchmark_coverage', label: '红熊/黑熊 AI 对标能力覆盖', status: 'passed', passed: true, required: true },
        ],
      },
    });
  }

  /* POST /api/kellai/channels/:type/test —— 测试连接 */
  const channelTestMatch = url.match(/^\/api\/kellai\/channels\/([a-z_]+)\/test$/);
  if (channelTestMatch && method === 'post') {
    await sendDelay();
    const ctype = channelTestMatch[1];
    const ch = channelMockState[ctype];
    if (!ch) {
      return notFound(config, `未支持的渠道类型: ${ctype}`);
    }
    // 必填字段不能空
    const missing = (channelRequiredFields[ctype] ?? []).filter(
      (k) => !ch.config[k] || ch.config[k] === '***'
    );
    if (missing.length > 0) {
      const msg = `请先填写完整配置: ${missing.join(', ')}`;
      return ok(config, { success: false, error: msg });
    }
    // mock 一律连接成功
    ch.connected = true;
    ch.enabled = true;
    ch.message = '已连接';
    return ok(config, { success: true, data: { connected: true, message: '连接成功' } });
  }

  /* PUT /api/kellai/channels/:type/config —— 保存配置 */
  const channelConfigMatch = url.match(/^\/api\/kellai\/channels\/([a-z_]+)\/config$/);
  if (channelConfigMatch && method === 'put') {
    await sendDelay();
    const ctype = channelConfigMatch[1];
    const ch = channelMockState[ctype];
    if (!ch) return notFound(config, `未支持的渠道类型: ${ctype}`);
    ch.config = { ...ch.config, ...((data?.config ?? {}) as Record<string, string>) };
    if (data?.name) ch.name = String(data.name);
    ch.enabled = Boolean(data?.enabled ?? ch.enabled);
    return ok(config, { success: true, data: ch });
  }

  /* DELETE /api/kellai/channels/:type —— 断开/删除渠道 */
  const channelDeleteMatch = url.match(/^\/api\/kellai\/channels\/([a-z_]+)$/);
  if (channelDeleteMatch && method === 'delete') {
    await sendDelay();
    const ctype = channelDeleteMatch[1];
    const ch = channelMockState[ctype];
    if (!ch) return notFound(config);
    ch.connected = false;
    ch.enabled = false;
    ch.config = {};
    return ok(config, { success: true, data: ch });
  }

  /* ----- CRM ----- */
  if (url === '/api/kellai/crm' && method === 'get') {
    await sendDelay();
    return ok(config, {
      success: true,
      data: {
        opportunity: { id: 'opp_001', company: 'Acme 科技', status: 'in_progress' },
        quote: { id: 'q_001', status: 'draft', summary: '标准版 50 坐席' },
        invoice: {},
        delivery: {},
        synced_at: new Date().toISOString(),
      },
    });
  }

  /* ----- 客户管理 ----- */
  /* GET /api/kellai/customers —— 列表（搜索 + 多维筛选） */
  if (url === '/api/kellai/customers' && method === 'get') {
    await sendDelay();
    let list = MOCK_CUSTOMERS.map((c) => ({
      customer_id: c.customer_id,
      username: c.username,
      stage: c.stage,
      stage_label: c.stage_label,
      display_name: c.display_name,
      intake_sent: c.intake_sent,
      last_message_preview: c.last_message_preview,
      channel_sources: c.channel_sources,
      ai_score: c.ai_score,
      ai_tags: c.ai_tags,
      updated_at: c.updated_at,
      created_at: c.created_at || c.updated_at,
      name: c.name || '',
      company: c.company || '',
      email: c.email || '',
      phone: c.phone || '',
      owner: c.owner || '',
      note: c.note || '',
      source: c.source || '',
      tags: c.tags || [],
    }));
    const stage = params?.stage ? String(params.stage) : '';
    const channel = params?.channel ? String(params.channel) : '';
    const tag = params?.tag ? String(params.tag) : '';
    const q = params?.q ? String(params.q).toLowerCase() : '';
    const minScore = params?.min_ai_score ? Number(params.min_ai_score) : 0;
    if (stage) list = list.filter((c) => c.stage === stage);
    if (channel) list = list.filter((c) => (c.channel_sources || []).includes(channel));
    if (tag) list = list.filter((c) => (c.tags || []).includes(tag) || (c.ai_tags || []).includes(tag));
    if (q) {
      list = list.filter((c) =>
        [c.display_name, c.name, c.company, c.email, c.phone, c.username].some((f) =>
          String(f || '').toLowerCase().includes(q),
        ),
      );
    }
    if (minScore > 0) list = list.filter((c) => c.ai_score >= minScore);
    return ok(config, {
      success: true,
      data: { customers: list, total: list.length, stage_definitions: mockStageDefinitions() },
    });
  }

  /* POST /api/kellai/customers/batch —— 批量操作 */
  if (url === '/api/kellai/customers/batch' && method === 'post') {
    await sendDelay();
    const ids: number[] = Array.isArray(data?.customer_ids) ? data.customer_ids.map(Number) : [];
    const action = String(data?.action || '');
    let affected = 0;
    for (const id of ids) {
      if (action === 'delete') {
        if (deleteMockCustomer(id)) { stageMap.delete(id); affected += 1; }
      } else if (action === 'set_stage' && data?.stage) {
        if (setMockCustomerStage(id, String(data.stage))) { stageMap.set(id, String(data.stage)); affected += 1; }
      } else if (action === 'add_tag' && data?.tag) {
        const c = MOCK_CUSTOMERS.find((x) => x.customer_id === id);
        if (c) { c.tags = Array.from(new Set([...(c.tags || []), String(data.tag)])); affected += 1; }
      } else if (action === 'remove_tag' && data?.tag) {
        const c = MOCK_CUSTOMERS.find((x) => x.customer_id === id);
        if (c) { c.tags = (c.tags || []).filter((t) => t !== String(data.tag)); affected += 1; }
      }
    }
    return ok(config, { success: true, data: { affected, action } });
  }

  /* POST /api/kellai/customers —— 创建 */
  if (url === '/api/kellai/customers' && method === 'post') {
    await sendDelay();
    if (!String(data?.name || '').trim() && !String(data?.company || '').trim()) {
      return badRequest(config, '请至少填写客户姓名或公司名称');
    }
    const rec = addMockCustomer(data || {});
    stageMap.set(rec.customer_id, rec.stage);
    return ok(config, { success: true, data: { customer_id: rec.customer_id, pipeline: rec } });
  }

  /* PUT /api/kellai/customers/:id —— 更新资料 */
  const customerUpdateMatch = url.match(/^\/api\/kellai\/customers\/(\d+)$/);
  if (customerUpdateMatch && method === 'put') {
    await sendDelay();
    const id = Number(customerUpdateMatch[1]);
    const rec = updateMockCustomer(id, data || {});
    if (!rec) return notFound(config, '客户不存在');
    if (rec.stage) stageMap.set(id, rec.stage);
    return ok(config, { success: true, data: { customer_id: id, pipeline: rec } });
  }

  /* DELETE /api/kellai/customers/:id —— 删除 */
  const customerDeleteMatch = url.match(/^\/api\/kellai\/customers\/(\d+)$/);
  if (customerDeleteMatch && method === 'delete') {
    await sendDelay();
    const id = Number(customerDeleteMatch[1]);
    const deleted = deleteMockCustomer(id);
    stageMap.delete(id);
    return ok(config, { success: true, data: { customer_id: id, deleted } });
  }

  /* ----- v3-v8 扩展端点 ----- */
  const extended = await handleExtendedRoutes(config, method, url, params, data);
  if (extended) return extended;

  /* ----- 兜底：mock 模式下走真请求会报错，便于发现漏配 ----- */
  console.warn('[mock] 未覆盖的接口:', method.toUpperCase(), url, data || params);
  return notFound(config, `mock 模式未实现 ${method.toUpperCase()} ${url}`);
};

function safeJson(s: unknown): any {
  if (typeof s !== 'string') return s;
  try {
    return JSON.parse(s);
  } catch {
    return s;
  }
}

/** 构造一个 mock User（鉴权相关接口用） */
function buildMockUser(email: string, name?: string) {
  const displayName = name || emailToName(email);
  return {
    id: hashEmailToId(email),
    email,
    name: displayName,
    display_name: displayName,
    avatar_url: '',
    phone: '',
    role: 'admin',
    team_id: 1,
    createdAt: '2026-01-01T00:00:00Z',
  };
}

/** 邮箱取名：test@kellai.com -> 测试账号；其它取 @ 前 6 位 */
function emailToName(email: string): string {
  const local = email.split('@')[0] || 'user';
  if (local === 'test') return '测试账号';
  if (local === 'guest') return '访客账号';
  if (local === 'admin') return '管理员';
  return local.slice(0, 6) || 'user';
}

/** 把邮箱映射成一个稳定的数字 id */
function hashEmailToId(email: string): number {
  let h = 0;
  for (let i = 0; i < email.length; i++) {
    h = (h * 31 + email.charCodeAt(i)) | 0;
  }
  return Math.abs(h) || 1;
}
