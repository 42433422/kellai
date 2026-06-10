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
 *   GET    /api/kellai/ai/reminders
 *
 *   GET    /api/kellai/channels
 *   GET    /api/kellai/crm?customer_id=X
 */

import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import {
  MOCK_CUSTOMERS,
  getMockFunnelStages,
  getMockAiProfile,
  getMockMessages,
  getMockReminders,
} from './customers';

/* -------- 内部可变状态：mock 阶段变更会写回这里 -------- */
const stageMap = new Map<number, string>();
MOCK_CUSTOMERS.forEach((c) => stageMap.set(c.customer_id, c.stage));

const messageStore: Record<number, ReturnType<typeof getMockMessages>> = {};
MOCK_CUSTOMERS.forEach((c) => {
  messageStore[c.customer_id] = getMockMessages(c.customer_id);
});

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
  wechat:     { id: 'ch_wechat',     name: '微信',         type: 'wechat',     channel_type: 'wechat',     adapter_class: 'WechatAdapter',     enabled: true,  connected: true,  config: {}, message: '已连接', createdAt: '2026-01-01T00:00:00Z' },
  wework:     { id: 'ch_wework',     name: '企业微信',     type: 'wework',     channel_type: 'wework',     adapter_class: 'WecomAdapter',      enabled: true,  connected: true,  config: { corp_id: 'ww123456', secret: '***', agent_id: '1000002' }, message: '已连接', createdAt: '2026-01-01T00:00:00Z' },
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
      const c = MOCK_CUSTOMERS.find((x) => x.customer_id === cid);
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
      const c = MOCK_CUSTOMERS.find((x) => x.customer_id === cid);
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

  /* LLM 状态（ai 命名空间） */
  if (url === '/api/kellai/ai/llm-status' && method === 'get') {
    await sendDelay();
    return ok(config, {
      success: true,
      data: { connected: true, model: 'deepseek', message: 'LLM 已就绪' },
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
