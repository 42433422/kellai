/**
 * Mock 测试客户数据
 *
 * 用途：本地开发 / 后端没起时，UI 也能看到真实形态的漏斗/消息/AI。
 * 切换：设置页 → "使用 Mock 数据"，或设置 localStorage `kellai:useMock=true`，
 *       或 .env 写 VITE_USE_MOCK=true。
 */

import type { ClientSummary, FunnelStage, CustomerMessage, CustomerAiProfile } from '../types';

/** 漏斗阶段定义（与 Funnel.tsx STAGE_ORDER 对齐） */
const STAGE_ORDER: { id: string; label: string }[] = [
  { id: 'no_contact', label: '未接触' },
  { id: 'connected', label: '已建联' },
  { id: 'requirement', label: '需求采集' },
  { id: 'submitted', label: '已提交' },
  { id: 'quoted', label: '已报价' },
  { id: 'negotiating', label: '议价' },
  { id: 'pending_sign', label: '待签' },
  { id: 'signed', label: '已签' },
  { id: 'delivering', label: '交付中' },
  { id: 'delivered', label: '已交付' },
];

export interface MockCustomer {
  customer_id: number;
  username: string;
  display_name: string;
  stage: string;
  stage_label: string;
  intake_sent: boolean;
  last_message_preview: string;
  channel_sources: string[];
  ai_score: number;
  ai_tags: string[];
  updated_at: string;
  contact_id: string;
  email: string;
  company: string;
  phone: string;
  // 客户管理扩展字段（手动维护）
  name?: string;
  owner?: string;
  note?: string;
  source?: string;
  tags?: string[];
  created_at?: string;
}

export const MOCK_CUSTOMERS: MockCustomer[] = [
  {
    customer_id: 1001,
    username: 'zhang_wei',
    display_name: '张伟',
    stage: 'no_contact',
    stage_label: '未接触',
    intake_sent: false,
    last_message_preview: '你好，请问你们 CRM 系统怎么收费？',
    channel_sources: ['wework'],
    ai_score: 0.32,
    ai_tags: ['初次咨询', '价格敏感'],
    updated_at: '2026-06-08T14:22:00Z',
    contact_id: 'ww_zhang_wei_001',
    email: 'zhang.wei@acme-corp.cn',
    company: 'Acme 科技',
    phone: '13800138001',
  },
  {
    customer_id: 1002,
    username: 'li_na',
    display_name: '李娜',
    stage: 'no_contact',
    stage_label: '未接触',
    intake_sent: false,
    last_message_preview: '我们公司在选型，想了解一下产品',
    channel_sources: ['miniapp'],
    ai_score: 0.41,
    ai_tags: ['正在选型'],
    updated_at: '2026-06-08T11:05:00Z',
    contact_id: 'ma_li_na_002',
    email: 'li.na@bluewave.io',
    company: '蓝海信息',
    phone: '13800138002',
  },
  {
    customer_id: 1003,
    username: 'wang_fang',
    display_name: '王芳',
    stage: 'connected',
    stage_label: '已建联',
    intake_sent: false,
    last_message_preview: '嗯，我们有几个具体的问题想问',
    channel_sources: ['phone', 'wework'],
    ai_score: 0.58,
    ai_tags: ['决策人', '中等意向'],
    updated_at: '2026-06-08T16:40:00Z',
    contact_id: 'ww_wang_fang_003',
    email: 'wang.fang@globalmart.cn',
    company: '全球购',
    phone: '13800138003',
  },
  {
    customer_id: 1004,
    username: 'liu_jian',
    display_name: '刘建',
    stage: 'connected',
    stage_label: '已建联',
    intake_sent: true,
    last_message_preview: '好的，需求表我先填一下',
    channel_sources: ['wework'],
    ai_score: 0.62,
    ai_tags: ['已建联', '有预算'],
    updated_at: '2026-06-08T09:15:00Z',
    contact_id: 'ww_liu_jian_004',
    email: 'liu.jian@smartlogistics.com',
    company: '智链物流',
    phone: '13800138004',
  },
  {
    customer_id: 1005,
    username: 'chen_xiao',
    display_name: '陈晓',
    stage: 'requirement',
    stage_label: '需求采集',
    intake_sent: true,
    last_message_preview: '我们大概需要 50 个坐席，能给个方案吗？',
    channel_sources: ['wework', 'email'],
    ai_score: 0.74,
    ai_tags: ['明确需求', '中高意向'],
    updated_at: '2026-06-08T18:20:00Z',
    contact_id: 'ww_chen_xiao_005',
    email: 'chen.xiao@retailplus.cn',
    company: '零售 Plus',
    phone: '13800138005',
  },
  {
    customer_id: 1006,
    username: 'zhao_lei',
    display_name: '赵磊',
    stage: 'submitted',
    stage_label: '已提交',
    intake_sent: true,
    last_message_preview: '需求表已经填好提交了，等你们评估',
    channel_sources: ['wework'],
    ai_score: 0.81,
    ai_tags: ['高意向', '表单已提交'],
    updated_at: '2026-06-08T20:10:00Z',
    contact_id: 'ww_zhao_lei_006',
    email: 'zhao.lei@fintech-hub.com',
    company: '金融汇',
    phone: '13800138006',
  },
  {
    customer_id: 1007,
    username: 'sun_yu',
    display_name: '孙雨',
    stage: 'quoted',
    stage_label: '已报价',
    intake_sent: true,
    last_message_preview: '报价单收到了，我们老板这周会过一下',
    channel_sources: ['wework', 'email'],
    ai_score: 0.85,
    ai_tags: ['报价中', '关键决策'],
    updated_at: '2026-06-08T15:30:00Z',
    contact_id: 'ww_sun_yu_007',
    email: 'sun.yu@manufact.cn',
    company: '制造云',
    phone: '13800138007',
  },
  {
    customer_id: 1008,
    username: 'zhou_tian',
    display_name: '周天',
    stage: 'negotiating',
    stage_label: '议价',
    intake_sent: true,
    last_message_preview: '价格能再谈谈吗？我们预算确实有限',
    channel_sources: ['phone'],
    ai_score: 0.78,
    ai_tags: ['议价中', '价格敏感'],
    updated_at: '2026-06-08T17:50:00Z',
    contact_id: 'ph_zhou_tian_008',
    email: 'zhou.tian@startup.io',
    company: '创业星',
    phone: '13800138008',
  },
  {
    customer_id: 1009,
    username: 'wu_jing',
    display_name: '吴静',
    stage: 'pending_sign',
    stage_label: '待签',
    intake_sent: true,
    last_message_preview: '合同我们法务看过了，这两天走流程',
    channel_sources: ['wework'],
    ai_score: 0.92,
    ai_tags: ['高优', '即将签约'],
    updated_at: '2026-06-08T19:00:00Z',
    contact_id: 'ww_wu_jing_009',
    email: 'wu.jing@bigcorp.cn',
    company: '大集团',
    phone: '13800138009',
  },
  {
    customer_id: 1010,
    username: 'zheng_hao',
    display_name: '郑昊',
    stage: 'signed',
    stage_label: '已签',
    intake_sent: true,
    last_message_preview: '已签约，期待后续合作',
    channel_sources: ['email'],
    ai_score: 0.96,
    ai_tags: ['已成交', 'VIP'],
    updated_at: '2026-06-08T10:00:00Z',
    contact_id: 'em_zheng_hao_010',
    email: 'zheng.hao@enterprise.cn',
    company: '企业集团',
    phone: '13800138010',
  },
  {
    customer_id: 1011,
    username: 'qian_li',
    display_name: '钱丽',
    stage: 'delivering',
    stage_label: '交付中',
    intake_sent: true,
    last_message_preview: '部署到一半了，这周能上线吗？',
    channel_sources: ['wework', 'phone'],
    ai_score: 0.95,
    ai_tags: ['交付中', 'VIP'],
    updated_at: '2026-06-08T13:25:00Z',
    contact_id: 'ww_qian_li_011',
    email: 'qian.li@chaincloud.cn',
    company: '链云',
    phone: '13800138011',
  },
  {
    customer_id: 1012,
    username: 'ke_ai',
    display_name: '柯艾',
    stage: 'delivered',
    stage_label: '已交付',
    intake_sent: true,
    last_message_preview: '系统已经用了一个月，团队很满意',
    channel_sources: ['wework'],
    ai_score: 0.98,
    ai_tags: ['老客户', '高满意度'],
    updated_at: '2026-06-08T08:00:00Z',
    contact_id: 'ww_ke_ai_012',
    email: 'ke.ai@brandleader.com',
    company: '品牌领跑',
    phone: '13800138012',
  },
];

/** 客户按阶段分组（用于漏斗） */
export function getMockFunnelStages(): FunnelStage[] {
  return STAGE_ORDER.map((s) => {
    const clients: ClientSummary[] = MOCK_CUSTOMERS
      .filter((c) => c.stage === s.id)
      .map<ClientSummary>((c) => ({
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
      }));
    return {
      id: s.id,
      label: s.label,
      count: clients.length,
      clients,
    };
  });
}

/** 单个客户的 AI 画像（用于 CustomerDetail / AIAssistant） */
export function getMockAiProfile(customerId: number): CustomerAiProfile | null {
  const c = MOCK_CUSTOMERS.find((x) => x.customer_id === customerId);
  if (!c) return null;
  return {
    customer_id: c.customer_id,
    needs_preference: `${c.company} 主要关注客户管理效率，希望打通企微渠道。`,
    decision_role: c.ai_score > 0.7 ? '决策人' : '影响者',
    budget_awareness: c.ai_score > 0.6 ? '有预算意识' : '价格敏感',
    urgency: c.ai_score > 0.8 ? 'high' : c.ai_score > 0.5 ? 'medium' : 'low',
    one_line_profile: `${c.display_name} 来自 ${c.company}，${c.ai_tags.join('、')}，AI 评分 ${(c.ai_score * 100).toFixed(0)} 分。`,
    ai_tags: c.ai_tags,
    ai_score: c.ai_score,
  };
}

/** 单个客户的消息历史（兼容 Messages.tsx 里的 MessageItem 结构） */
export function getMockMessages(customerId: number): CustomerMessage[] {
  const c = MOCK_CUSTOMERS.find((x) => x.customer_id === customerId);
  if (!c) return [];
  const channel = c.channel_sources[0] || 'wework';
  const baseTime = new Date('2026-06-07T10:00:00Z').getTime();
  const HOUR = 3600 * 1000;
  const mk = (
    i: number,
    direction: 'inbound' | 'outbound',
    content: string,
    intent?: string,
    read = true
  ): CustomerMessage & { customer_name: string; read: boolean; ai_intent?: string } => ({
    id: `${c.customer_id}-m${i}`,
    customer_id: c.customer_id,
    customer_name: c.display_name,
    channel_type: channel,
    contact_id: c.contact_id,
    direction,
    content,
    intent,
    ai_intent: intent,
    read,
    created_at: new Date(baseTime + i * HOUR).toISOString(),
  });
  return [
    mk(1, 'inbound', '你好，看到你们的产品介绍，想了解一下', '初次咨询', true),
    mk(2, 'outbound', '您好！我是 客来来 的销售顾问，可以简单介绍一下贵公司的情况吗？', undefined, true),
    mk(3, 'inbound', c.last_message_preview, '需求沟通', false),
    mk(4, 'outbound', '好的，我整理一下方案发您，稍等~', undefined, true),
    mk(5, 'inbound', '好，谢谢', '积极回应', true),
  ] as unknown as CustomerMessage[];
}

/** 跟进提醒（用于 Dashboard） */
export function getMockReminders() {
  return MOCK_CUSTOMERS
    .filter((c) => c.ai_score > 0.4 && c.stage !== 'delivered' && c.stage !== 'signed')
    .map((c) => ({
      customer_id: c.customer_id,
      display_name: c.display_name,
      stage: c.stage,
      hours_since_last_contact: Math.floor(Math.random() * 48) + 4,
      suggested_action:
        c.ai_score > 0.7
          ? '高意向客户，建议本周内主动联系推进'
          : '保持 3 天一次的节奏，简短问候',
    }));
}

/* ============================================================
 *  客户管理：可变存储 + CRUD（让 mock 模式下增删改持久于会话）
 * ============================================================ */

/** 阶段 ID → 中文标签 */
export function stageLabelOf(stageId: string): string {
  return STAGE_ORDER.find((s) => s.id === stageId)?.label ?? stageId;
}

/** 阶段定义（供客户管理页下拉使用） */
export function mockStageDefinitions() {
  return STAGE_ORDER.map((s) => ({ id: s.id, label: s.label }));
}

/** 下一个可用的客户 ID（手动创建从 90001 起） */
export function nextMockCustomerId(): number {
  const max = MOCK_CUSTOMERS.reduce((m, c) => Math.max(m, c.customer_id), 90000);
  return max + 1;
}

interface MockProfileInput {
  name?: string;
  company?: string;
  email?: string;
  phone?: string;
  note?: string;
  owner?: string;
  source?: string;
  stage?: string;
  tags?: string[];
  channel_sources?: string[];
}

/** 新建 mock 客户，返回新记录 */
export function addMockCustomer(profile: MockProfileInput): MockCustomer {
  const id = nextMockCustomerId();
  const stage = profile.stage || 'no_contact';
  const now = new Date().toISOString();
  const record: MockCustomer = {
    customer_id: id,
    username: (profile.name || profile.company || `cust_${id}`).trim(),
    display_name: (profile.company || profile.name || `客户 ${id}`).trim(),
    stage,
    stage_label: stageLabelOf(stage),
    intake_sent: false,
    last_message_preview: '',
    channel_sources: profile.channel_sources ?? [],
    ai_score: 0,
    ai_tags: [],
    updated_at: now,
    contact_id: '',
    email: profile.email ?? '',
    company: profile.company ?? '',
    phone: profile.phone ?? '',
    name: profile.name ?? '',
    owner: profile.owner ?? '',
    note: profile.note ?? '',
    source: profile.source ?? '',
    tags: profile.tags ?? [],
    created_at: now,
  };
  MOCK_CUSTOMERS.unshift(record);
  return record;
}

/** 更新 mock 客户资料，返回更新后的记录（不存在则返回 null） */
export function updateMockCustomer(id: number, profile: MockProfileInput): MockCustomer | null {
  const c = MOCK_CUSTOMERS.find((x) => x.customer_id === id);
  if (!c) return null;
  if (profile.name !== undefined) c.name = profile.name;
  if (profile.company !== undefined) c.company = profile.company;
  if (profile.email !== undefined) c.email = profile.email;
  if (profile.phone !== undefined) c.phone = profile.phone;
  if (profile.note !== undefined) c.note = profile.note;
  if (profile.owner !== undefined) c.owner = profile.owner;
  if (profile.source !== undefined) c.source = profile.source;
  if (profile.tags !== undefined) c.tags = profile.tags;
  if (profile.channel_sources !== undefined) c.channel_sources = profile.channel_sources;
  if (profile.stage && profile.stage !== c.stage) {
    c.stage = profile.stage;
    c.stage_label = stageLabelOf(profile.stage);
  }
  // display_name 跟随资料刷新
  c.display_name = (c.company || c.name || c.display_name).trim();
  c.updated_at = new Date().toISOString();
  return c;
}

/** 删除 mock 客户，返回是否删除成功 */
export function deleteMockCustomer(id: number): boolean {
  const idx = MOCK_CUSTOMERS.findIndex((x) => x.customer_id === id);
  if (idx === -1) return false;
  MOCK_CUSTOMERS.splice(idx, 1);
  return true;
}

/** 设置 mock 客户阶段（漏斗拖拽与客户管理共用，保持一致） */
export function setMockCustomerStage(id: number, stage: string): MockCustomer | null {
  const c = MOCK_CUSTOMERS.find((x) => x.customer_id === id);
  if (!c) return null;
  c.stage = stage;
  c.stage_label = stageLabelOf(stage);
  c.updated_at = new Date().toISOString();
  return c;
}
