import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { invoke } from '@tauri-apps/api/core';
import QRCodeLib from 'qrcode';
import {
  MessageCircle,
  Users,
  User,
  Bot,
  Clock,
  CheckCircle2,
  XCircle,
  Eye,
  EyeOff,
  Copy,
  Trash2,
  ChevronDown,
  Loader2,
  AlertCircle,
  X,
  HelpCircle,
  QrCode,
  RefreshCw,
  ScanLine,
  ShieldCheck,
} from 'lucide-react';
import { useOnboardingStore } from '../stores/onboarding';
import { useMessageStore } from '../stores/message';
import { ONBOARDING_WELCOME_CACHE_KEY, ONBOARDING_WELCOME_SPEECH_TEXT } from '../constants/onboardingTour';
import { playPreparedTextToSpeech, preloadTextToSpeech, unlockTextToSpeechAudio } from '../hooks/useTextToSpeech';
import { estimateSpeechHoldMs } from '../utils/onboardingSpeech';
import ChannelLogo, { CHANNEL_BRAND_COLOR } from '../components/ChannelLogo';
import { toastStore } from '../stores/toast';
import {
  getAutoReplyRuntimeStatus,
  type AutoReplyRuntimeStatus,
} from '../api/messages';
import { clsx } from 'clsx';
import type {
  Channel,
  LLMConfig,
  TeamInfo,
  TeamMember,
  FollowUpStageRule,
  SOPTemplate,
  NotificationPreferences,
} from '../types';
import {
  getChannels,
  testChannel,
  saveChannelConfig,
  getWeworkCustomerEntry,
  syncChannelInbox,
  getLlmStatus,
  saveLlmConfig,
  probeLlmConfig,
  getLlmDiagnostics,
  getTeamInfo,
  getTeamMembers,
  inviteMember,
  updateMemberRole,
  getUserInfo,
  updateUserInfo,
  initiateWeworkOAuth,
  checkWeworkOAuthStatus,
  syncWeworkCustomers,
  getWeworkAcquisitionMembers,
  createWeworkAcquisitionLink,
  initiateWechatOAuth,
  checkWechatOAuthStatus,
  initiateDouyinOAuth,
  checkDouyinOAuthStatus,
  getDouyinWebPortalStatus,
  connectDouyinWebPortal,
  syncDouyinWebPortal,
  startDouyinWebPortalMonitor,
  stopDouyinWebPortalMonitor,
  disconnectDouyinWebPortal,
  getXcmaxIntegrationStatus,
  getXcmaxBindingPending,
  approveXcmaxBinding,
  cancelXcmaxBinding,
  disconnectXcmaxBinding,
} from '../api/settings';

type OnboardingSpeechWindow = Window & {
  __kellaiOnboardingWelcomePreplayedUntil?: number;
};

/* ========== 常量与映射 ========== */

/** Tab 配置 */
const TABS = [
  { key: 'channels', label: '渠道管理', icon: MessageCircle },
  { key: 'ai', label: 'AI 助手', icon: Bot },
  { key: 'followup', label: '跟进规则', icon: Clock },
  { key: 'team', label: '团队管理', icon: Users },
  { key: 'xcmax', label: 'XCMAX AI', icon: ShieldCheck },
  { key: 'profile', label: '个人设置', icon: User },
] as const;

type TabKey = (typeof TABS)[number]['key'];

/** 渠道名称映射 */
const channelNameMap: Record<string, string> = {
  wechat: '微信开放平台',
  wework: '企业微信',
  phone: '电话',
  douyin: '抖音',
  miniprogram: '公众号/小程序',
  email: '邮件',
  sms: '短信',
  web: '网页',
  // 电商平台
  pdd: '拼多多',
  taobao: '淘宝',
  jd: '京东',
  alibaba: '1688',
  // 海外
  whatsapp: 'WhatsApp',
  telegram: 'Telegram',
  line: 'LINE',
};

/** 渠道分组（用于分区渲染） */
const channelGroups: Array<{ key: string; title: string; types: string[] }> = [
  { key: 'im', title: '即时通讯', types: ['wechat', 'wework', 'douyin', 'miniprogram'] },
  { key: 'ecom', title: '电商平台', types: ['pdd', 'taobao', 'jd', 'alibaba'] },
  { key: 'oversea', title: '海外渠道', types: ['whatsapp', 'telegram', 'line'] },
  { key: 'other', title: '其他方式', types: ['phone', 'email', 'sms', 'web'] },
];

/** 渠道认证方式：scan = 扫码授权（推荐，零配置），form = 凭据表单 */
type ChannelAuthMode = 'scan' | 'form' | 'select' | 'none' | 'both';

/** 渠道认证方式映射：哪些渠道用扫码，哪些用凭据表单 */
const channelAuthModeMap: Record<string, ChannelAuthMode> = {
  // 即时通讯 → 扫码授权（服务商代配置）
  wechat: 'both',
  wework: 'both',
  douyin: 'both',
  miniprogram: 'scan',
  // 电商平台 → 扫码授权（商家工作台扫码登录）
  pdd: 'scan',
  taobao: 'scan',
  jd: 'scan',
  alibaba: 'scan',
  // 海外 → 凭据表单（API Key / Bot Token 等，无扫码）
  whatsapp: 'form',
  telegram: 'form',
  line: 'form',
  // 其他
  phone: 'select',   // 选外呼线路
  email: 'none',     // 无需配置
  sms: 'none',
  web: 'none',
};

/** 扫码授权提示语（按渠道定制） */
const channelScanTips: Record<string, { app: string; description: string }> = {
  wechat: { app: '微信', description: '使用微信扫码完成开放平台网站应用授权，授权后可保存 openid/unionid 并接收公众号回调消息' },
  wework: { app: '企业微信', description: '企业管理员扫码安装客来来第三方应用，一次授权后自动同步真实客户列表' },
  douyin: { app: '抖音', description: '网站应用完成测试白名单，小程序私信能力负责把真实客户消息接入统一工作台并支持回复' },
  miniprogram: { app: '微信', description: '使用微信扫一扫，授权公众号/小程序接入' },
  pdd: { app: '拼多多商家版', description: '使用拼多多商家 App 扫码，授权客服工作台' },
  taobao: { app: '千牛', description: '使用千牛 App 扫码，授权客服工作台' },
  jd: { app: '京麦', description: '使用京麦 App 扫码，授权客服工作台' },
  alibaba: { app: '千牛 / 阿里卖家', description: '使用 1688 卖家端 App 扫码，授权客服工作台' },
};

/** 渠道配置字段映射（仅 form 模式用） */
const channelConfigFieldsMap: Record<string, { key: string; label: string; type: 'text' | 'password' | 'select'; placeholder?: string; options?: { label: string; value: string }[] }[]> = {
  wechat: [
    { key: 'app_id', label: '开放平台 AppID', type: 'text', placeholder: 'wx1234567890abcdef' },
    { key: 'app_secret', label: '开放平台 AppSecret', type: 'password', placeholder: '请输入网站应用 AppSecret' },
    { key: 'official_app_id', label: '公众号 AppID（可选）', type: 'text', placeholder: '用于客服消息发送' },
    { key: 'official_app_secret', label: '公众号 AppSecret（可选）', type: 'password', placeholder: '用于拉取公众号 access_token' },
    { key: 'token', label: '回调 Token（可选）', type: 'password', placeholder: '公众平台服务器配置 Token' },
    { key: 'encoding_aes_key', label: 'EncodingAESKey（可选）', type: 'password', placeholder: '明文模式可留空' },
    { key: 'bot_webhook', label: '兼容 Webhook（可选）', type: 'text', placeholder: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...' },
  ],
  wework: [
    { key: 'corp_id', label: 'Corp ID（企业 ID）', type: 'text', placeholder: 'ww1234567890' },
    { key: 'secret', label: 'Secret（应用密钥）', type: 'password', placeholder: '请输入应用 Secret' },
    { key: 'agent_id', label: 'Agent ID（应用 ID）', type: 'text', placeholder: '1000002' },
    { key: 'bot_webhook', label: '群机器人 Webhook（可选）', type: 'text', placeholder: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...' },
    { key: 'kf_url', label: '客服接待链接（可选）', type: 'text', placeholder: 'https://work.weixin.qq.com/kfid/...' },
    { key: 'open_kfid', label: '客服账号 ID（自动解析，可选）', type: 'text', placeholder: 'kfcxxxxxxxxxxxxxxxx' },
  ],
  phone: [
    { key: 'line', label: '外呼线路', type: 'select', options: [
      { label: '线路 1 - 电信', value: 'line1' },
      { label: '线路 2 - 移动', value: 'line2' },
      { label: '线路 3 - 联通', value: 'line3' },
    ] },
  ],
  douyin: [
    { key: 'app_id', label: '网站应用 Client Key', type: 'text', placeholder: '用于测试白名单和基础账号授权' },
    { key: 'app_secret', label: '网站应用 Client Secret', type: 'password', placeholder: '抖音开放平台移动/网站应用密钥' },
    { key: 'miniapp_app_id', label: '抖音小程序 AppID', type: 'text', placeholder: 'tt 开头的小程序 AppID' },
    { key: 'miniapp_secret', label: '小程序 Webhook AppSecret', type: 'password', placeholder: '开发配置 → Webhooks 中的 AppSecret（不是密钥管理 AppSecret）' },
  ],
  miniprogram: [
    { key: 'app_id', label: 'App ID', type: 'text', placeholder: '请输入公众号/小程序 App ID' },
    { key: 'app_secret', label: 'App Secret', type: 'password', placeholder: '请输入 App Secret' },
  ],
  // 电商平台
  pdd: [
    { key: 'client_id', label: 'Client ID', type: 'text', placeholder: '拼多多开放平台 Client ID' },
    { key: 'client_secret', label: 'Client Secret', type: 'password', placeholder: '请输入 Client Secret' },
  ],
  taobao: [
    { key: 'app_key', label: 'App Key', type: 'text', placeholder: '淘宝开放平台 App Key' },
    { key: 'app_secret', label: 'App Secret', type: 'password', placeholder: '请输入 App Secret' },
  ],
  jd: [
    { key: 'app_key', label: 'App Key', type: 'text', placeholder: '京东开放平台 App Key' },
    { key: 'app_secret', label: 'App Secret', type: 'password', placeholder: '请输入 App Secret' },
  ],
  alibaba: [
    { key: 'app_key', label: 'App Key', type: 'text', placeholder: '1688 开放平台 App Key' },
    { key: 'app_secret', label: 'App Secret', type: 'password', placeholder: '请输入 App Secret' },
  ],
  // 海外
  whatsapp: [
    { key: 'phone_number_id', label: 'Phone Number ID', type: 'text', placeholder: 'WhatsApp Business Phone Number ID' },
    { key: 'access_token', label: 'Access Token', type: 'password', placeholder: '请输入 Access Token' },
  ],
  telegram: [
    { key: 'bot_token', label: 'Bot Token', type: 'password', placeholder: '从 @BotFather 获取' },
  ],
  line: [
    { key: 'channel_access_token', label: 'Channel Access Token', type: 'password', placeholder: 'LINE Official Account Token' },
  ],
};

const channelRequiredConfigFieldsMap: Record<string, string[]> = {
  wechat: ['app_id', 'app_secret'],
  wework: ['corp_id', 'secret', 'agent_id'],
  douyin: ['app_id', 'app_secret', 'miniapp_app_id', 'miniapp_secret'],
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

/** 默认平台列表（API 返回空时用作兜底） */
const DEFAULT_PLATFORMS: string[] = channelGroups.flatMap((g) => g.types);

/** 根据 type 构造"未连接"占位 Channel */
function makeDisconnectedChannel(type: string, _idx: number): Channel {
  return {
    id: `default-${type}`,
    name: channelNameMap[type] ?? type,
    type: type as Channel['type'],
    connected: false,
    enabled: false,
    config: {},
    createdAt: new Date().toISOString(),
  };
}

function fieldLabelOf(channelType: string, fieldKey: string) {
  const field = (channelConfigFieldsMap[channelType] ?? []).find((item) => item.key === fieldKey);
  return field?.label ?? fieldKey;
}

function onboardingFallback(channel: Channel) {
  const fields = channelConfigFieldsMap[channel.type] ?? [];
  const requiredFields = channelRequiredConfigFieldsMap[channel.type] ?? fields.map((item) => item.key);
  const optionalFields = fields.map((item) => item.key).filter((key) => !requiredFields.includes(key));
  const savedFields = Object.entries(channel.config || {})
    .filter(([, value]) => String(value ?? '').trim())
    .map(([key]) => key);
  const missing = requiredFields.filter((key) => !String(channel.config?.[key] ?? '').trim());
  const requiredComplete = missing.length === 0;
  const mode = channelAuthModeMap[channel.type] ?? 'form';
  const hasScan = mode === 'scan' || mode === 'both';
  const hasManual = fields.length > 0;
  const status = channel.connected ? 'connected' : savedFields.length > 0 ? 'saved' : mode === 'none' ? 'ready' : 'not_started';
  return {
    status,
    recommended_mode: mode === 'both' ? 'scan' : mode,
    auth_modes: mode === 'both' ? ['scan', 'form'] : [mode],
    required_fields: requiredFields,
    optional_fields: optionalFields,
    missing_required_fields: missing,
    saved_fields: savedFields,
    materials: hasManual ? ['准备平台后台账号和应用凭据'] : [],
    external_steps: mode === 'none'
      ? ['无需平台侧动作，可直接使用该来源']
      : hasScan
        ? ['在对应平台后台确认授权账号', '扫码或回填凭据后测试连接']
        : ['按字段回填凭据后测试连接'],
    success_criteria: ['测试连接通过', '同步收件箱后能在消息中心看到客户消息'],
    stages: [
      { key: 'prepare', label: '准备材料', status: savedFields.length || channel.connected || !requiredFields.length ? 'done' : 'current' },
      {
        key: 'configure',
        label: '授权/配置',
        status: channel.connected || (savedFields.length && requiredComplete)
          ? 'done'
          : savedFields.length && !requiredComplete
            ? 'current'
            : requiredFields.length
              ? 'pending'
              : 'skipped',
      },
      { key: 'test', label: '测试连接', status: channel.connected ? 'done' : savedFields.length && requiredComplete ? 'current' : 'pending' },
      { key: 'sync', label: '同步收件箱', status: channel.connected ? 'current' : 'pending' },
    ],
    next_action: channel.connected
      ? '同步收件箱，确认客户消息能进入漏斗。'
      : savedFields.length
        ? requiredComplete
          ? '点击测试连接，确认平台凭据可用。'
          : '补齐必填字段并保存后，再测试连接。'
        : mode === 'none'
          ? '无需配置，可直接作为客户来源使用。'
          : '先准备平台材料，然后按向导授权或回填字段。',
    can_scan: hasScan,
    can_manual: hasManual,
    enabled: channel.enabled,
  } as NonNullable<Channel['onboarding']>;
}

function onboardingOf(channel: Channel) {
  return channel.onboarding ?? onboardingFallback(channel);
}

function connectedOnboarding(profile: NonNullable<Channel['onboarding']>) {
  return {
    ...profile,
    status: 'connected' as const,
    missing_required_fields: [],
    stages: profile.stages.map((step) => ({
      ...step,
      status: step.key === 'sync' ? 'current' as const : 'done' as const,
    })),
    next_action: '同步收件箱，确认客户消息能进入漏斗。',
  };
}

/** LLM 模型选项 */
const LLM_MODELS = [
  { label: '自定义兼容', value: 'custom' },
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'OpenAI', value: 'openai' },
  { label: '通义千问', value: 'qwen' },
  { label: 'Moonshot', value: 'moonshot' },
  { label: 'SiliconFlow', value: 'siliconflow' },
  { label: '火山方舟/豆包', value: 'ark' },
  { label: '智谱 GLM', value: 'zhipu' },
  { label: 'MiniMax', value: 'minimax' },
  { label: 'Xiaomi MiMo', value: 'mimo' },
  { label: 'xAI Grok', value: 'xai' },
  { label: 'XCauto（修茈）', value: 'xcauto' },
];

const LLM_DEFAULT_PARAMS: Record<string, { model: string; baseUrl: string }> = {
  custom: { model: 'gpt-4o-mini', baseUrl: 'https://api.openai.com/v1' },
  deepseek: { model: 'deepseek-chat', baseUrl: 'https://api.deepseek.com/v1' },
  openai: { model: 'gpt-4o-mini', baseUrl: 'https://api.openai.com/v1' },
  qwen: { model: 'qwen-plus', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  moonshot: { model: 'moonshot-v1-8k', baseUrl: 'https://api.moonshot.cn/v1' },
  siliconflow: { model: 'deepseek-ai/DeepSeek-V3', baseUrl: 'https://api.siliconflow.cn/v1' },
  ark: { model: 'doubao-seed-1-6', baseUrl: 'https://ark.cn-beijing.volces.com/api/v3' },
  zhipu: { model: 'glm-4-flash', baseUrl: 'https://open.bigmodel.cn/api/paas/v4' },
  minimax: { model: 'MiniMax-Text-01', baseUrl: 'https://api.minimax.chat/v1' },
  mimo: { model: 'mimo-v2.5-pro', baseUrl: 'https://token-plan-cn.xiaomimimo.com/v1' },
  xai: { model: 'grok-3-mini', baseUrl: 'https://api.x.ai/v1' },
  xcauto: { model: 'deepseek-chat', baseUrl: 'https://api.deepseek.com/v1' },
};

const LLM_PROVIDER_VALUES = new Set(LLM_MODELS.map((item) => item.value));

function isKnownLlmProvider(value: string) {
  return LLM_PROVIDER_VALUES.has(value);
}

function normalizeLlmProvider(value: string) {
  const raw = String(value || '').trim().toLowerCase();
  if (raw === 'auto') return 'xcauto';
  if (['volcengine', 'volcengine-ark', 'volcengine_ark', 'doubao', 'doubao-ark', 'doubao_ark', 'huoshan', '火山', '方舟'].includes(raw)) return 'ark';
  if (['zhipuai', 'glm', 'bigmodel', '智谱'].includes(raw)) return 'zhipu';
  if (['xiaomi', 'xiaomi-mimo', 'xiaomi_mimo', 'xiaomimimo', 'mi-mimo', 'mi_mimo', '小米'].includes(raw)) return 'mimo';
  if (raw === 'grok') return 'xai';
  return isKnownLlmProvider(raw) ? raw : 'deepseek';
}

/** 自动回复适用阶段 */
const AUTO_REPLY_STAGES = [
  { value: 'idle', label: '未接触' },
  { value: 'connected', label: '已建联' },
  { value: 'intake', label: '需求采集' },
  { value: 'intake_done', label: '已提交' },
  { value: 'quoted', label: '已报价' },
  { value: 'negotiating', label: '议价' },
  { value: 'contract_pending', label: '待签' },
  { value: 'signed', label: '已签' },
  { value: 'delivering', label: '交付中' },
  { value: 'delivered', label: '已交付' },
];

/** 需确认场景 */
const CONFIRM_SCENARIOS = ['涉及价格', '合同条款', '交付时间'];

/** 默认跟进规则 */
const DEFAULT_FOLLOW_UP_RULES: FollowUpStageRule[] = [
  { stage: 'new', stageLabel: '未接触', timeoutDays: 7, remindMethods: ['站内', '桌面通知'] },
  { stage: 'contacted', stageLabel: '已建联', timeoutDays: 3, remindMethods: ['站内', '桌面通知'] },
  { stage: 'qualified', stageLabel: '需求采集', timeoutDays: 2, remindMethods: ['站内', '桌面通知', '企微'] },
  { stage: 'proposal', stageLabel: '已提交', timeoutDays: 3, remindMethods: ['站内', '桌面通知'] },
  { stage: 'negotiation', stageLabel: '已报价', timeoutDays: 2, remindMethods: ['站内', '桌面通知', '企微'] },
  { stage: 'deal', stageLabel: '谈判中', timeoutDays: 1, remindMethods: ['站内', '桌面通知', '企微'] },
];

/** 预置 SOP 模板 */
const DEFAULT_SOP_TEMPLATES: SOPTemplate[] = [
  { id: '1', name: '新线索首次跟进', stage: '未接触', stepsCount: 4, steps: ['发送欢迎消息', '了解客户基本需求', '记录客户信息', '安排下次跟进时间'] },
  { id: '2', name: '需求确认流程', stage: '需求采集', stepsCount: 5, steps: ['回顾历史沟通记录', '确认核心需求', '评估匹配度', '提供初步方案', '约定方案讨论时间'] },
  { id: '3', name: '报价后跟进', stage: '已报价', stepsCount: 3, steps: ['确认客户已收到报价', '解答报价疑问', '推动决策进度'] },
  { id: '4', name: '成交推进 SOP', stage: '谈判中', stepsCount: 4, steps: ['确认关键决策人态度', '处理最后异议', '确定签约时间', '准备合同'] },
];

/** 角色选项 */
const ROLE_OPTIONS = [
  { label: '管理员', value: 'admin' },
  { label: '销售', value: 'sales' },
  { label: '只读', value: 'readonly' },
];

/** 提醒方式选项 */
const REMIND_METHOD_OPTIONS = ['站内', '桌面通知', '企微'];

/* ========== 通用组件 ========== */

/** 开关组件 */
function Toggle({ checked, onChange, ariaLabel }: { checked: boolean; onChange: (v: boolean) => void; ariaLabel?: string }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      aria-label={ariaLabel}
      role="switch"
      aria-checked={checked}
      className={clsx(
        'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200',
        checked ? 'bg-blue-600' : 'bg-gray-200'
      )}
    >
      <span
        className={clsx(
          'pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition duration-200',
          checked ? 'translate-x-5' : 'translate-x-0'
        )}
      />
    </button>
  );
}

/** 多选标签组 */
function MultiSelectTags({
  options,
  selected,
  onChange,
}: {
  options: Array<string | { value: string; label: string }>;
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const toggle = (item: string) => {
    if (selected.includes(item)) {
      onChange(selected.filter((s) => s !== item));
    } else {
      onChange([...selected, item]);
    }
  };

  return (
    <div className="flex flex-wrap gap-2">
      {options.map((opt) => {
        const value = typeof opt === 'string' ? opt : opt.value;
        const label = typeof opt === 'string' ? opt : opt.label;
        return (
        <button
          key={value}
          type="button"
          onClick={() => toggle(value)}
          className={clsx(
            'rounded-full px-3 py-1 text-xs font-medium transition-colors',
            selected.includes(value)
              ? 'bg-blue-100 text-blue-700 ring-1 ring-blue-300'
              : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
          )}
        >
          {label}
        </button>
        );
      })}
    </div>
  );
}

/* ========== Tab 1：渠道管理 ========== */

function ChannelTab() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [configChannel, setConfigChannel] = useState<Channel | null>(null);
  const [scanChannel, setScanChannel] = useState<Channel | null>(null);
  const [entryChannel, setEntryChannel] = useState<Channel | null>(null);
  const [acquisitionChannel, setAcquisitionChannel] = useState<Channel | null>(null);
  const [douyinWebPortalChannel, setDouyinWebPortalChannel] = useState<Channel | null>(null);
  const [onboardingChannel, setOnboardingChannel] = useState<Channel | null>(null);
  const [configValues, setConfigValues] = useState<Record<string, string>>({});
  const [testingChannel, setTestingChannel] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string }>>({});
  const [syncingChannel, setSyncingChannel] = useState<string | null>(null);
  const [syncResult, setSyncResult] = useState<Record<string, { success: boolean; message: string }>>({});

  useEffect(() => {
    getChannels()
      .then((res) => {
        const data = (res as any)?.data?.data ?? (res as any)?.data ?? res;
        const normalized = Array.isArray(data)
          ? data.filter((item) => DEFAULT_PLATFORMS.includes(String(item?.type ?? item?.channel_type ?? '')))
          : [];
        setChannels(normalized);
      })
      .catch(() => setError('加载渠道列表失败'))
      .finally(() => setLoading(false));
  }, []);

  /** 打开配置弹窗 */
  const openConfig = (channel: Channel) => {
    setConfigChannel(channel);
    const fields = channelConfigFieldsMap[channel.type] ?? [];
    const values: Record<string, string> = {};
    fields.forEach((f) => {
      values[f.key] = (channel.config[f.key] as string) ?? '';
    });
    setConfigValues(values);
  };

  const openOnboarding = (channel: Channel) => {
    setOnboardingChannel(channel);
    const fields = channelConfigFieldsMap[channel.type] ?? [];
    const values: Record<string, string> = {};
    fields.forEach((f) => {
      values[f.key] = (channel.config[f.key] as string) ?? '';
    });
    setConfigValues(values);
  };

  /** 测试连接 */
  const handleTest = async (channelType: string) => {
    setTestingChannel(channelType);
    setTestResult((prev) => ({ ...prev, [channelType]: { success: false, message: '测试中...' } }));
    try {
      const res = (await testChannel(channelType)) as any;
      const body = res?.data ?? res;
      const data = body?.data ?? body;
      const message = data?.message || body?.message || body?.error || '连接成功';
      const ok = Boolean(body?.success && (data?.connected ?? data?.success ?? body?.success));
      setTestResult((prev) => ({ ...prev, [channelType]: { success: ok, message } }));
      if (ok) {
        const markConnected = (c: Channel): Channel => ({
          ...c,
          connected: true,
          enabled: true,
          onboarding: connectedOnboarding(onboardingOf({ ...c, connected: true, enabled: true })),
        });
        setChannels((prev) =>
          prev.map((c) => (c.type === channelType ? markConnected(c) : c))
        );
        if (onboardingChannel?.type === channelType) {
          setOnboardingChannel((prev) => (prev ? markConnected(prev) : prev));
        }
      }
      return ok;
    } catch (err) {
      const data = (err as any)?.response?.data;
      setTestResult((prev) => ({
        ...prev,
        [channelType]: { success: false, message: data?.message || data?.error || '连接失败，请检查配置' },
      }));
      return false;
    } finally {
      setTestingChannel(null);
    }
  };

  /** 保存渠道配置到后端 */
  const handleSaveConfig = async (channelType: string, values: Record<string, string>) => {
    try {
      const res = (await saveChannelConfig(channelType, values, { enabled: true })) as any;
      const body = res?.data ?? res;
      if (body?.success === false) {
        throw new Error(body?.error || body?.message || '渠道配置校验失败');
      }
      const data = body?.data ?? body;
      setChannels((prev) =>
        prev.map((c) => {
          if (c.type !== channelType) return c;
          const returnedConfig = data?.config && typeof data.config === 'object'
            ? data.config as Record<string, string>
            : values;
          const mergedConfig = { ...c.config, ...returnedConfig };
          return {
            ...c,
            enabled: Boolean(data?.enabled ?? true),
            connected: Boolean(data?.connected ?? false),
            config: mergedConfig,
            onboarding: data?.onboarding ?? onboardingFallback({ ...c, connected: false, enabled: Boolean(data?.enabled ?? true), config: mergedConfig }),
          };
        })
      );
      if (onboardingChannel?.type === channelType) {
        setOnboardingChannel((prev) => {
          if (!prev) return prev;
          const returnedConfig = data?.config && typeof data.config === 'object'
            ? data.config as Record<string, string>
            : values;
          const mergedConfig = { ...prev.config, ...returnedConfig };
          return {
            ...prev,
            enabled: Boolean(data?.enabled ?? true),
            connected: Boolean(data?.connected ?? false),
            config: mergedConfig,
            onboarding: data?.onboarding ?? onboardingFallback({ ...prev, connected: false, enabled: Boolean(data?.enabled ?? true), config: mergedConfig }),
          };
        });
      }
      setTestResult((prev) => ({ ...prev, [channelType]: { success: true, message: '已保存配置，下一步测试连接' } }));
    } catch (err) {
      setTestResult((prev) => ({
        ...prev,
        [channelType]: { success: false, message: `保存失败: ${(err as Error)?.message ?? '未知错误'}` },
      }));
      throw err;
    }
  };

  const handleSyncInbox = async (channelType: string) => {
    setSyncingChannel(channelType);
    setSyncResult((prev) => ({ ...prev, [channelType]: { success: false, message: '同步中...' } }));
    try {
      const res = (await syncChannelInbox(channelType, 20)) as any;
      const data = res?.data?.data ?? res?.data ?? res;
      const synced = Number(data?.synced ?? 0);
      const errors = Array.isArray(data?.errors) ? data.errors : [];
      const ok = errors.length === 0;
      setSyncResult((prev) => ({
        ...prev,
        [channelType]: {
          success: ok,
          message: ok ? `已同步 ${synced} 条消息` : `同步完成，${errors.length} 个错误`,
        },
      }));
    } catch (err) {
      setSyncResult((prev) => ({
        ...prev,
        [channelType]: { success: false, message: `同步失败: ${(err as Error)?.message ?? '未知错误'}` },
      }));
    } finally {
      setSyncingChannel(null);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-gray-400" /><span className="ml-2 text-sm text-gray-400">加载中...</span></div>;
  }

  if (error) {
    return <div className="flex items-center justify-center py-20"><AlertCircle className="h-5 w-5 text-red-400" /><span className="ml-2 text-sm text-red-500">{error}</span></div>;
  }

  /** 用 DEFAULT_PLATFORMS 补齐后端尚未注册的轻量入口，保持接入页固定完整。 */
  const channelsByType = new Map<Channel['type'], Channel>(
    DEFAULT_PLATFORMS.map((t, i) => {
      const ch = makeDisconnectedChannel(t, i);
      return [ch.type, ch];
    })
  );
  channels.forEach((channel) => {
    if (DEFAULT_PLATFORMS.includes(channel.type)) {
      channelsByType.set(channel.type, channel);
    }
  });
  const displayChannels: Channel[] = DEFAULT_PLATFORMS
    .map((type) => channelsByType.get(type as Channel['type']))
    .filter(Boolean) as Channel[];

  return (
    <div data-tour="settings-channels">
      <h2 className="text-lg font-semibold text-gray-900">渠道管理</h2>
      <p className="mt-1 text-sm text-gray-500">管理消息渠道连接与配置</p>

      {/* 顶栏：连接中/总计 概览 */}
      <div className="mt-4 flex items-center gap-4 rounded-lg border border-gray-100 bg-gray-50 px-4 py-2.5 text-xs text-gray-500">
        <span>
          已连接 <b className="text-green-600">{displayChannels.filter((c) => c.connected).length}</b> / {displayChannels.length}
        </span>
        <span>·</span>
        <span>共 {channelGroups.length} 个分组</span>
      </div>

      {/* 分区渲染：即时通讯 / 电商 / 海外 / 其他 */}
      {channelGroups.map((group) => {
        const groupChannels = group.types
          .map((t) => channelsByType.get(t as Channel['type']))
          .filter(Boolean) as Channel[];
        if (groupChannels.length === 0) return null;
        return (
          <section key={group.key} className="mt-6">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-700">
              <span className="inline-block h-3 w-1 rounded-full bg-blue-500" />
              {group.title}
              <span className="text-[11px] font-normal text-gray-400">
                {groupChannels.filter((c) => c.connected).length}/{groupChannels.length}
              </span>
            </h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {groupChannels.map((channel) => {
                const result = testResult[channel.type];
                const sync = syncResult[channel.type];
                const profile = onboardingOf(channel);
                const missingCount = profile.missing_required_fields.length;
                const doneSteps = profile.stages.filter((step) => step.status === 'done').length;
                const hasCustomerEntry =
                  channel.type === 'wework' &&
                  Boolean(channel.config?.kf_url || channel.config?.open_kfid);
                const hasBasicDouyinAuthorization =
                  channel.type === 'douyin' &&
                  String(channel.config?.oauth_authorized ?? '').toLowerCase() === 'true';
                return (
                  <div
                    key={channel.id}
                    data-tour="settings-channel-card"
                    data-channel-type={channel.type}
                    className={clsx(
                      "rounded-xl border bg-white p-4 shadow-sm transition",
                      channel.connected
                        ? "border-green-200 ring-1 ring-green-100"
                        : "border-gray-200 hover:border-blue-300"
                    )}
                  >
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg" style={{ background: `${CHANNEL_BRAND_COLOR[channel.type] ?? '#3b82f6'}1a` }}>
                  <ChannelLogo type={channel.type} size={28} />
                </div>
                <div className="flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-medium text-gray-900">{channelNameMap[channel.type] ?? channel.name}</p>
                    <span className={clsx(
                      'rounded-full px-2 py-0.5 text-[11px] font-medium',
                      channel.connected
                        ? 'bg-green-50 text-green-700'
                        : hasBasicDouyinAuthorization
                          ? 'bg-blue-50 text-blue-700'
                        : profile.status === 'saved'
                          ? 'bg-blue-50 text-blue-700'
                          : 'bg-gray-100 text-gray-500'
                    )}>
                      {channel.connected ? '已接入' : hasBasicDouyinAuthorization ? '基础授权' : profile.status === 'saved' ? '待测试' : profile.status === 'ready' ? '可用' : '未接入'}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    {channel.connected ? (
                      <>
                        <span className="h-2 w-2 rounded-full bg-green-500" />
                        <span className="text-xs text-green-600">已连接</span>
                      </>
                    ) : hasBasicDouyinAuthorization ? (
                      <>
                        <span className="h-2 w-2 rounded-full bg-blue-500" />
                        <span className="text-xs text-blue-600">已授权，私信权限待开通</span>
                      </>
                    ) : (
                      <>
                        <span className="h-2 w-2 rounded-full bg-gray-300" />
                        <span className="text-xs text-gray-400">未连接</span>
                      </>
                    )}
                  </div>
                </div>
              </div>

              <div className="mt-4 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                <div className="flex items-center justify-between gap-2">
                  <span>接入进度 {doneSteps}/{profile.stages.length}</span>
                  <span>{profile.recommended_mode === 'scan' ? '推荐扫码' : profile.recommended_mode === 'form' ? '回填凭据' : profile.recommended_mode === 'select' ? '选择线路' : '无需配置'}</span>
                </div>
                <div className="mt-2 grid grid-cols-4 gap-1">
                  {profile.stages.map((step) => (
                    <span
                      key={step.key}
                      title={step.label}
                      className={clsx(
                        'h-1.5 rounded-full',
                        step.status === 'done'
                          ? 'bg-green-500'
                          : step.status === 'current'
                            ? 'bg-blue-500'
                            : step.status === 'skipped'
                              ? 'bg-slate-200'
                              : 'bg-slate-300'
                      )}
                    />
                  ))}
                </div>
                <p className="mt-2 line-clamp-2">{profile.next_action}</p>
                {hasBasicDouyinAuthorization && channel.message && (
                  <p className="mt-1 text-blue-700">{channel.message}</p>
                )}
                {missingCount > 0 && (
                  <p className="mt-1 text-amber-700">缺少 {missingCount} 项：{profile.missing_required_fields.map((key) => fieldLabelOf(channel.type, key)).join('、')}</p>
                )}
              </div>

              {/* 操作按钮 */}
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <button
                  onClick={() => openOnboarding(channel)}
                  aria-label={`接入 ${channelNameMap[channel.type] ?? channel.name}`}
                  data-tour="settings-channel-config-btn"
                  className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-blue-700"
                >
                  接入向导
                </button>
                <button
                  onClick={() => handleTest(channel.type)}
                  disabled={testingChannel === channel.type}
                  aria-label={`测试 ${channelNameMap[channel.type] ?? channel.name} 连接`}
                  className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 transition hover:bg-gray-50 disabled:opacity-50"
                >
                  {testingChannel === channel.type ? '测试中...' : '测试连接'}
                </button>
                <button
                  onClick={() => handleSyncInbox(channel.type)}
                  disabled={syncingChannel === channel.type}
                  aria-label={`同步 ${channelNameMap[channel.type] ?? channel.name} 收件箱`}
                  className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 transition hover:bg-gray-50 disabled:opacity-50"
                >
                  {syncingChannel === channel.type ? '同步中...' : '同步收件箱'}
                </button>
                {hasCustomerEntry && (
                  <button
                    type="button"
                    onClick={() => setEntryChannel(channel)}
                    aria-label="企业微信客户入口二维码"
                    className="inline-flex items-center gap-1 rounded-lg border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-700 transition hover:bg-blue-50"
                  >
                    <QrCode className="h-3.5 w-3.5" />
                    客户入口二维码
                  </button>
                )}
                {channel.type === 'wework' && (
                  <button
                    type="button"
                    onClick={() => setAcquisitionChannel(channel)}
                    aria-label="创建企业微信获客链接"
                    className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 px-3 py-1.5 text-xs font-medium text-emerald-700 transition hover:bg-emerald-50"
                  >
                    <QrCode className="h-3.5 w-3.5" />
                    创建获客链接
                  </button>
                )}
                {channel.type === 'douyin' && (
                  <button
                    type="button"
                    onClick={() => setDouyinWebPortalChannel(channel)}
                    aria-label="配置抖音网站 Token"
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-800 transition hover:bg-slate-50"
                  >
                    <MessageCircle className="h-3.5 w-3.5" />
                    网站 Token
                  </button>
                )}
              </div>

              {/* 测试结果 */}
              {result && (
                <div className={clsx('mt-3 flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs', result.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700')}>
                  {result.success ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
                  {result.message}
                </div>
              )}
              {sync && (
                <div className={clsx('mt-2 flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs', sync.success ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700')}>
                  {sync.success ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertCircle className="h-3.5 w-3.5" />}
                  {sync.message}
                </div>
              )}
                  </div>
                );
              })}
            </div>
          </section>
        );
      })}

      {/* 接入向导弹窗 - 主流程：准备材料 → 授权/配置 → 测试连接 → 同步收件箱 */}
      {onboardingChannel && (
        <ChannelOnboardingModal
          channel={onboardingChannel}
          values={configValues}
          testResult={testResult[onboardingChannel.type]}
          syncResult={syncResult[onboardingChannel.type]}
          testing={testingChannel === onboardingChannel.type}
          syncing={syncingChannel === onboardingChannel.type}
          onChange={setConfigValues}
          onClose={() => setOnboardingChannel(null)}
          onSave={handleSaveConfig}
          onTest={handleTest}
          onSync={handleSyncInbox}
          onScan={() => {
            const ch = onboardingChannel;
            setOnboardingChannel(null);
            setScanChannel(ch);
          }}
          onOpenStandaloneConfig={() => {
            const ch = onboardingChannel;
            setOnboardingChannel(null);
            openConfig(ch);
          }}
        />
      )}

      {/* 手动配置弹窗 - both 模式或 form 模式 */}
      {configChannel && (channelAuthModeMap[configChannel.type] === 'form' || channelAuthModeMap[configChannel.type] === 'both') && (
        <ChannelConfigModal
          channel={configChannel}
          values={configValues}
          onChange={setConfigValues}
          onClose={() => setConfigChannel(null)}
          onSave={handleSaveConfig}
        />
      )}
      {/* 扫码授权弹窗 - scan 模式或 both 模式 */}
      {(scanChannel || (configChannel && channelAuthModeMap[configChannel.type] === 'scan')) && (
        <ChannelScanModal
          channel={(scanChannel || configChannel)!}
          onClose={() => { setScanChannel(null); setConfigChannel(null); }}
          onSuccess={async () => {
            const ch = (scanChannel || configChannel)!;
            setChannels((prev) =>
              prev.map((c) =>
                c.type === ch.type ? { ...c, connected: true, enabled: true } : c
              )
            );
            setTestResult((prev) => ({
              ...prev,
              [ch.type]: { success: true, message: '扫码授权成功' },
            }));
            if (ch.type === 'douyin') {
              const connected = await handleTest(ch.type);
              if (connected) {
                await handleSyncInbox(ch.type);
                await useMessageStore.getState().fetchUnread();
                setTestResult((prev) => ({
                  ...prev,
                  [ch.type]: {
                    success: true,
                    message: '扫码授权成功；新的抖音私信会在 15 秒内自动出现在消息中心',
                  },
                }));
                toastStore.success('抖音授权成功，正在监听新私信');
              }
            }
            setScanChannel(null);
            setConfigChannel(null);
          }}
        />
      )}

      {entryChannel && (
        <WeworkCustomerEntryModal
          channel={entryChannel}
          onClose={() => setEntryChannel(null)}
        />
      )}

      {acquisitionChannel && (
        <WeworkAcquisitionLinkModal
          channel={acquisitionChannel}
          onClose={() => setAcquisitionChannel(null)}
        />
      )}

      {douyinWebPortalChannel && (
        <DouyinWebPortalModal
          onClose={() => setDouyinWebPortalChannel(null)}
          onConnected={() => {
            setChannels((prev) =>
              prev.map((channel) =>
                channel.type === 'douyin'
                  ? {
                      ...channel,
                      connected: true,
                      enabled: true,
                      message: '抖音网站数据已连接并监听实时私信',
                      config: { ...channel.config, web_portal_connected: 'true' },
                    }
                  : channel
              )
            );
            setTestResult((prev) => ({
              ...prev,
              douyin: { success: true, message: '网站数据已连接，联系人和消息正在同步' },
            }));
          }}
        />
      )}
    </div>
  );
}

type DouyinWebPortalState = {
  connected: boolean;
  status: string;
  account_name?: string;
  monitor_running?: boolean;
  contact_count?: number;
  last_sync_at?: string;
  last_message_at?: string;
  last_error?: string;
};

function DouyinWebPortalModal({
  onClose,
  onConnected,
}: {
  onClose: () => void;
  onConnected: () => void;
}) {
  const [portalState, setPortalState] = useState<DouyinWebPortalState | null>(null);
  const [tokenOrUrl, setTokenOrUrl] = useState('');
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState('');
  const [error, setError] = useState('');
  const [result, setResult] = useState('');

  const unwrap = (res: any) => res?.data?.data ?? res?.data ?? res;

  const refreshStatus = useCallback(async () => {
    const res = await getDouyinWebPortalStatus();
    setPortalState(unwrap(res));
  }, []);

  useEffect(() => {
    refreshStatus()
      .catch((err: any) => {
        const body = err?.response?.data;
        setError(body?.detail?.message || body?.message || '读取网站 Token 状态失败');
      })
      .finally(() => setLoading(false));
  }, [refreshStatus]);

  const connectAndSync = async () => {
    if (!tokenOrUrl.trim()) {
      setError('请输入网站 Token');
      return;
    }
    setWorking('connect');
    setError('');
    setResult('');
    try {
      await connectDouyinWebPortal(tokenOrUrl.trim());
      const syncRes = await syncDouyinWebPortal(300, 20);
      const syncData = unwrap(syncRes);
      await startDouyinWebPortalMonitor();
      await useMessageStore.getState().fetchUnread();
      await refreshStatus();
      setTokenOrUrl('');
      setResult(`已同步 ${Number(syncData?.contacts ?? 0)} 位联系人、${Number(syncData?.messages ?? 0)} 条消息，并开始实时监听`);
      onConnected();
      toastStore.success('抖音网站数据已接入客来来');
    } catch (err: any) {
      const body = err?.response?.data;
      setError(body?.detail?.message || body?.message || body?.error || err?.message || '网站 Token 接入失败');
    } finally {
      setWorking('');
    }
  };

  const syncNow = async () => {
    setWorking('sync');
    setError('');
    try {
      const res = await syncDouyinWebPortal(300, 20);
      const data = unwrap(res);
      await useMessageStore.getState().fetchUnread();
      await refreshStatus();
      setResult(`已同步 ${Number(data?.contacts ?? 0)} 位联系人、${Number(data?.messages ?? 0)} 条消息`);
    } catch (err: any) {
      const body = err?.response?.data;
      setError(body?.detail?.message || body?.message || err?.message || '同步失败');
    } finally {
      setWorking('');
    }
  };

  const toggleMonitor = async () => {
    const running = Boolean(portalState?.monitor_running);
    setWorking('monitor');
    setError('');
    try {
      if (running) {
        await stopDouyinWebPortalMonitor();
        setResult('已停止实时监听');
      } else {
        await startDouyinWebPortalMonitor();
        setResult('已开始实时监听新私信');
      }
      await refreshStatus();
    } catch (err: any) {
      const body = err?.response?.data;
      setError(body?.detail?.message || body?.message || err?.message || '切换监听状态失败');
    } finally {
      setWorking('');
    }
  };

  const disconnect = async () => {
    setWorking('disconnect');
    setError('');
    try {
      await disconnectDouyinWebPortal();
      await refreshStatus();
      setResult('已断开网站数据连接');
    } catch (err: any) {
      const body = err?.response?.data;
      setError(body?.detail?.message || body?.message || err?.message || '断开失败');
    } finally {
      setWorking('');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-xl overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between border-b border-slate-100 px-6 py-5">
          <div>
            <h3 className="text-base font-semibold text-slate-950">抖音网站 Token</h3>
            <p className="mt-1 text-xs text-slate-500">输入 Token 后同步账号、客户、历史消息和实时新私信</p>
          </div>
          <button onClick={onClose} aria-label="关闭" className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4 px-6 py-5">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-slate-500">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 正在读取连接状态
            </div>
          ) : (
            <>
              <div className={clsx(
                'rounded-xl border px-4 py-3',
                portalState?.connected ? 'border-green-200 bg-green-50' : 'border-slate-200 bg-slate-50'
              )}>
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className={clsx('h-2.5 w-2.5 rounded-full', portalState?.connected ? 'bg-green-500' : 'bg-slate-300')} />
                    <span className="text-sm font-semibold text-slate-900">
                      {portalState?.connected ? `已连接${portalState.account_name ? `：${portalState.account_name}` : ''}` : '尚未连接'}
                    </span>
                  </div>
                  {portalState?.connected && (
                    <span className={clsx(
                      'rounded-full px-2.5 py-1 text-[11px] font-medium',
                      portalState.monitor_running ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'
                    )}>
                      {portalState.monitor_running ? '实时监听中' : '监听已停止'}
                    </span>
                  )}
                </div>
                {portalState?.connected && (
                  <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-600">
                    <span>联系人：{Number(portalState.contact_count ?? 0)}</span>
                    <span>状态：{portalState.status || 'connected'}</span>
                  </div>
                )}
              </div>

              {!portalState?.connected && (
                <>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-slate-700">网站 Token</label>
                    <input
                      type="password"
                      value={tokenOrUrl}
                      onChange={(event) => setTokenOrUrl(event.target.value)}
                      placeholder="请输入网站 Token"
                      autoComplete="off"
                      className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                    <p className="mt-1 text-[11px] text-slate-500">Token 会在本机加密保存，不保存网站账号密码。</p>
                  </div>
                  <button
                    type="button"
                    onClick={connectAndSync}
                    disabled={working === 'connect'}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
                  >
                    {working === 'connect' && <Loader2 className="h-4 w-4 animate-spin" />}
                    {working === 'connect' ? '连接并同步中...' : '连接、同步并开始监听'}
                  </button>
                </>
              )}

              {portalState?.connected && (
                <div className="grid gap-2 sm:grid-cols-3">
                  <button
                    type="button"
                    onClick={syncNow}
                    disabled={Boolean(working)}
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
                  >
                    {working === 'sync' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                    立即同步
                  </button>
                  <button
                    type="button"
                    onClick={toggleMonitor}
                    disabled={Boolean(working)}
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-blue-200 px-3 py-2 text-xs font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-60"
                  >
                    {working === 'monitor' && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    {portalState.monitor_running ? '停止监听' : '开始监听'}
                  </button>
                  <button
                    type="button"
                    onClick={disconnect}
                    disabled={Boolean(working)}
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
                  >
                    {working === 'disconnect' && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    断开连接
                  </button>
                </div>
              )}

              {result && (
                <div className="flex items-start gap-2 rounded-lg bg-green-50 px-3 py-2 text-xs text-green-700">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{result}</span>
                </div>
              )}
              {(error || portalState?.last_error) && (
                <div className="flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{error || portalState?.last_error}</span>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** 渠道接入向导弹窗 */
function ChannelOnboardingModal({
  channel,
  values,
  testResult,
  syncResult,
  testing,
  syncing,
  onChange,
  onClose,
  onSave,
  onTest,
  onSync,
  onScan,
  onOpenStandaloneConfig,
}: {
  channel: Channel;
  values: Record<string, string>;
  testResult?: { success: boolean; message: string };
  syncResult?: { success: boolean; message: string };
  testing: boolean;
  syncing: boolean;
  onChange: (v: Record<string, string>) => void;
  onClose: () => void;
  onSave: (channelType: string, values: Record<string, string>) => Promise<void>;
  onTest: (channelType: string) => Promise<boolean | void>;
  onSync: (channelType: string) => Promise<void>;
  onScan: () => void;
  onOpenStandaloneConfig: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const profile = onboardingOf(channel);
  const fields = channelConfigFieldsMap[channel.type] ?? [];
  const channelLabel = channelNameMap[channel.type] ?? channel.name;
  const doneSteps = profile.stages.filter((step) => step.status === 'done').length;
  const progress = profile.stages.length ? Math.round((doneSteps / profile.stages.length) * 100) : 100;
  const remoteCredentialsConfigured = (
    channel.type === 'douyin'
    && String(channel.config?.remote_credentials_configured ?? '').toLowerCase() === 'true'
  );
  const remoteMiniappConfigured = (
    channel.type === 'douyin'
    && String(channel.config?.remote_miniapp_configured ?? '').toLowerCase() === 'true'
  );
  const liveMissingFields = profile.required_fields.filter((key) => {
    if (remoteCredentialsConfigured && ['app_id', 'app_secret', 'client_key', 'client_secret'].includes(key)) {
      return false;
    }
    if (remoteMiniappConfigured && ['miniapp_app_id', 'miniapp_secret'].includes(key)) {
      return false;
    }
    const currentValue = values[key] ?? (channel.config?.[key] as string | undefined) ?? '';
    return !String(currentValue).trim();
  });
  const scanBlockedByMissingCredentials =
    profile.can_scan && liveMissingFields.length > 0;
  const modeLabel: Record<string, string> = {
    scan: '推荐扫码授权',
    form: '回填平台凭据',
    select: '选择业务线路',
    none: '无需额外配置',
  };

  const saveConfig = async () => {
    setSaving(true);
    try {
      await onSave(channel.type, values);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      data-tour="channel-config-modal"
      data-channel-onboarding-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-3 backdrop-blur-sm sm:p-6"
      onClick={onClose}
    >
      <div
        data-tour="channel-config-modal-body"
        className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl" style={{ background: `${CHANNEL_BRAND_COLOR[channel.type] ?? '#3b82f6'}1a` }}>
              <ChannelLogo type={channel.type} size={30} />
            </div>
            <div className="min-w-0">
              <h3 className="truncate text-base font-semibold text-slate-950">接入向导 - {channelLabel}</h3>
              <p className="mt-1 text-xs text-slate-500">{profile.next_action}</p>
            </div>
          </div>
          <button onClick={onClose} aria-label="关闭接入向导" className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="overflow-y-auto px-5 py-5 sm:px-6">
          <div className="grid gap-5 lg:grid-cols-[1fr_1.1fr]">
            <section className="space-y-4">
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">接入进度</p>
                    <p className="mt-1 text-xs text-slate-500">{doneSteps}/{profile.stages.length} 项完成</p>
                  </div>
                  <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600 ring-1 ring-slate-200">
                    {modeLabel[profile.recommended_mode] ?? '回填平台凭据'}
                  </span>
                </div>
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
                  <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} />
                </div>
                <div className="mt-4 space-y-2">
                  {profile.stages.map((step) => (
                    <div key={step.key} className="flex items-center gap-3 rounded-lg bg-white px-3 py-2 ring-1 ring-slate-100">
                      <span
                        className={clsx(
                          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
                          step.status === 'done'
                            ? 'bg-green-100 text-green-700'
                            : step.status === 'current'
                              ? 'bg-blue-100 text-blue-700'
                              : step.status === 'skipped'
                                ? 'bg-slate-100 text-slate-400'
                                : 'bg-slate-100 text-slate-500'
                        )}
                      >
                        {step.status === 'done' ? <CheckCircle2 className="h-4 w-4" /> : <Clock className="h-4 w-4" />}
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-slate-800">{step.label}</p>
                        <p className="text-xs text-slate-500">
                          {step.status === 'done' ? '已完成' : step.status === 'current' ? '当前步骤' : step.status === 'skipped' ? '已跳过' : '待处理'}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                <div className="rounded-xl border border-slate-200 p-4">
                  <p className="text-sm font-semibold text-slate-900">需要准备</p>
                  {profile.materials.length > 0 ? (
                    <ul className="mt-3 space-y-2 text-xs leading-relaxed text-slate-600">
                      {profile.materials.map((item) => (
                        <li key={item} className="flex gap-2">
                          <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" />
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-3 text-xs text-slate-500">当前渠道无需额外材料。</p>
                  )}
                </div>

                <div className="rounded-xl border border-slate-200 p-4">
                  <p className="text-sm font-semibold text-slate-900">平台侧动作</p>
                  <ul className="mt-3 space-y-2 text-xs leading-relaxed text-slate-600">
                    {profile.external_steps.map((item, index) => (
                      <li key={`${index}-${item}`} className="flex gap-2">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[10px] font-semibold text-slate-500">{index + 1}</span>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </section>

            <section className="space-y-4">
              <div className="rounded-xl border border-blue-100 bg-blue-50/60 p-4">
                <div className="flex items-start gap-3">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
                  <div>
                    <p className="text-sm font-semibold text-blue-950">下一步</p>
                    <p className="mt-1 text-xs leading-relaxed text-blue-800">{profile.next_action}</p>
                    {liveMissingFields.length > 0 && (
                      <p className="mt-2 text-xs text-amber-700">
                        还缺少：{liveMissingFields.map((key) => fieldLabelOf(channel.type, key)).join('、')}
                      </p>
                    )}
                  </div>
                </div>
              </div>

              {profile.can_scan && (
                <button
                  type="button"
                  data-tour="channel-onboarding-scan"
                  onClick={onScan}
                  disabled={scanBlockedByMissingCredentials}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-slate-950 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  <QrCode className="h-4 w-4" />
                  {scanBlockedByMissingCredentials
                    ? `先保存${liveMissingFields.map((key) => fieldLabelOf(channel.type, key)).join('、')}`
                    : '扫码授权'}
                </button>
              )}

              {fields.length > 0 ? (
                <div className="rounded-xl border border-slate-200 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-slate-900">凭据配置</p>
                    <button
                      type="button"
                      onClick={onOpenStandaloneConfig}
                      className="text-xs font-medium text-blue-600 hover:text-blue-700"
                    >
                      单独配置
                    </button>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    {fields.map((field) => {
                      const required = profile.required_fields.includes(field.key);
                      return (
                        <div key={field.key} className={field.type === 'password' ? 'sm:col-span-2' : undefined}>
                          <label className="mb-1 flex items-center gap-1 text-xs font-medium text-slate-700">
                            {field.label}
                            {required && <span className="text-amber-600">*</span>}
                          </label>
                          {field.type === 'select' ? (
                            <select
                              value={values[field.key] ?? ''}
                              onChange={(e) => onChange({ ...values, [field.key]: e.target.value })}
                              aria-label={field.label}
                              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                            >
                              <option value="">请选择</option>
                              {field.options?.map((opt) => (
                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                              ))}
                            </select>
                          ) : (
                            <input
                              type={field.type}
                              placeholder={field.placeholder}
                              value={values[field.key] ?? ''}
                              onChange={(e) => onChange({ ...values, [field.key]: e.target.value })}
                              aria-label={field.label}
                              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                  <button
                    type="button"
                    onClick={saveConfig}
                    disabled={saving}
                    data-tour="channel-config-save"
                    className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:opacity-60"
                  >
                    {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                    {saving ? '保存中...' : '保存配置'}
                  </button>
                </div>
              ) : (
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
                  该渠道无需额外配置，直接测试连接或同步收件箱即可。
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => onTest(channel.type)}
                  disabled={testing}
                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                >
                  {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  {testing ? '测试中...' : '测试连接'}
                </button>
                <button
                  type="button"
                  onClick={() => onSync(channel.type)}
                  disabled={syncing}
                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                >
                  {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  {syncing ? '同步中...' : '同步收件箱'}
                </button>
              </div>

              {(testResult || syncResult) && (
                <div className="space-y-2">
                  {testResult && (
                    <div className={clsx('flex items-center gap-2 rounded-lg px-3 py-2 text-xs', testResult.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700')}>
                      {testResult.success ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
                      <span>{testResult.message}</span>
                    </div>
                  )}
                  {syncResult && (
                    <div className={clsx('flex items-center gap-2 rounded-lg px-3 py-2 text-xs', syncResult.success ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700')}>
                      {syncResult.success ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
                      <span>{syncResult.message}</span>
                    </div>
                  )}
                </div>
              )}

              <div className="rounded-xl border border-slate-200 p-4">
                <p className="text-sm font-semibold text-slate-900">验收标准</p>
                <ul className="mt-3 space-y-2 text-xs leading-relaxed text-slate-600">
                  {profile.success_criteria.map((item) => (
                    <li key={item} className="flex gap-2">
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-600" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}

/** 渠道配置弹窗 */
function ChannelConfigModal({
  channel,
  values,
  onChange,
  onClose,
  onSave,
}: {
  channel: Channel;
  values: Record<string, string>;
  onChange: (v: Record<string, string>) => void;
  onClose: () => void;
  onSave: (channelType: string, values: Record<string, string>) => Promise<void>;
}) {
  const fields = channelConfigFieldsMap[channel.type] ?? [];

  return (
    <div data-tour="channel-config-modal" className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div data-tour="channel-config-modal-body" className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-900">
            配置 - {channelNameMap[channel.type] ?? channel.name}
          </h3>
          <button onClick={onClose} aria-label="关闭配置" className="rounded-md p-1 text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mt-5 space-y-4">
          {fields.length === 0 ? (
            <div className="rounded-lg bg-gray-50 p-4 text-sm text-gray-500">
              该渠道暂无可配置项，请直接点击下方"测试连接"验证可用性。
            </div>
          ) : (
            fields.map((field) => (
              <div key={field.key}>
                <label className="mb-1 block text-sm font-medium text-gray-700">{field.label}</label>
                {field.type === 'select' ? (
                  <select
                    value={values[field.key] ?? ''}
                    onChange={(e) => onChange({ ...values, [field.key]: e.target.value })}
                    aria-label={field.label}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-black placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="">请选择</option>
                    {field.options?.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={field.type}
                    placeholder={field.placeholder}
                    value={values[field.key] ?? ''}
                    onChange={(e) => onChange({ ...values, [field.key]: e.target.value })}
                    aria-label={field.label}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-black placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                )}
              </div>
            ))
          )}
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <button
            onClick={onClose}
            data-tour="channel-config-cancel"
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 transition hover:bg-gray-50"
          >
            取消
          </button>
          <button
            onClick={async () => {
              try {
                await onSave(channel.type, values);
                onClose();
              } catch {
                /* 失败提示在父组件展示，保持弹窗打开 */
              }
            }}
            data-tour="channel-config-save"
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-700"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  );
}

type WeworkCustomerEntryPayload = {
  entry_url: string;
  target_url: string;
  source: string;
};

function WeworkCustomerEntryModal({
  channel,
  onClose,
}: {
  channel: Channel;
  onClose: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [entry, setEntry] = useState<WeworkCustomerEntryPayload | null>(null);
  const [qrImageUrl, setQrImageUrl] = useState('');
  const channelLabel = channelNameMap[channel.type] ?? channel.name;

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError('');
      setQrImageUrl('');
      try {
        const res = (await getWeworkCustomerEntry('settings')) as any;
        const body = res?.data ?? res;
        const data = (body?.data ?? body) as WeworkCustomerEntryPayload;
        if (body?.success === false || !data?.entry_url) {
          throw new Error(body?.error || '企业微信客服入口未配置');
        }
        const image = await QRCodeLib.toDataURL(data.entry_url, {
          width: 224,
          margin: 1,
          color: { dark: '#0f172a', light: '#ffffff' },
        });
        if (cancelled) return;
        setEntry(data);
        setQrImageUrl(image);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : '生成客户入口二维码失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [channel.config?.kf_url, channel.config?.open_kfid]);

  const copyEntryUrl = async () => {
    if (!entry?.entry_url) return;
    try {
      await navigator.clipboard.writeText(entry.entry_url);
      toastStore.success('客户入口链接已复制');
    } catch {
      toastStore.error('复制失败，请手动复制链接');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
              <QrCode className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900">客户入口二维码</h3>
              <p className="mt-0.5 text-xs text-gray-500">{channelLabel}</p>
            </div>
          </div>
          <button onClick={onClose} aria-label="关闭客户入口二维码" className="rounded-md p-1 text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mt-6 flex flex-col items-center">
          <div className="flex h-64 w-64 items-center justify-center rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            {loading ? (
              <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
            ) : qrImageUrl ? (
              <img src={qrImageUrl} alt="企业微信客户入口二维码" className="h-56 w-56" draggable={false} />
            ) : (
              <div className="flex flex-col items-center text-center text-sm text-amber-700">
                <AlertCircle className="h-8 w-8" />
                <span className="mt-2">{error || '无法生成二维码'}</span>
              </div>
            )}
          </div>

          {entry && (
            <div className="mt-4 w-full space-y-3">
              <div className="rounded-lg bg-slate-50 px-3 py-2">
                <div className="text-xs font-medium text-slate-500">客来来入口</div>
                <div className="mt-1 break-all text-xs text-slate-700">{entry.entry_url}</div>
              </div>
              <div className="rounded-lg bg-blue-50 px-3 py-2">
                <div className="text-xs font-medium text-blue-700">企业微信客服</div>
                <div className="mt-1 break-all text-xs text-blue-700">{entry.target_url}</div>
              </div>
            </div>
          )}
        </div>

        <div className="mt-6 grid grid-cols-2 gap-3">
          <button
            type="button"
            onClick={copyEntryUrl}
            disabled={!entry}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Copy className="h-4 w-4" />
            复制链接
          </button>
          <button
            type="button"
            onClick={() => entry?.entry_url && window.open(entry.entry_url, '_blank', 'noopener,noreferrer')}
            disabled={!entry}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            打开入口
          </button>
        </div>
      </div>
    </div>
  );
}

type WeworkAcquisitionMember = {
  userid: string;
  name: string;
};

type WeworkAcquisitionLink = {
  link_id: string;
  link_name: string;
  url: string;
  create_time: number;
};

function WeworkAcquisitionLinkModal({
  channel,
  onClose,
}: {
  channel: Channel;
  onClose: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [members, setMembers] = useState<WeworkAcquisitionMember[]>([]);
  const [selectedUserids, setSelectedUserids] = useState<string[]>([]);
  const [linkName, setLinkName] = useState('客来来获客链接');
  const [createdLink, setCreatedLink] = useState<WeworkAcquisitionLink | null>(null);
  const [qrImageUrl, setQrImageUrl] = useState('');
  const channelLabel = channelNameMap[channel.type] ?? channel.name;

  useEffect(() => {
    let cancelled = false;
    const loadMembers = async () => {
      setLoading(true);
      setError('');
      try {
        const res = (await getWeworkAcquisitionMembers()) as any;
        const body = res?.data ?? res;
        const data = body?.data ?? body;
        if (body?.success === false) {
          throw new Error(body?.error || '无法读取企业微信跟进员工');
        }
        const nextMembers = Array.isArray(data?.members)
          ? data.members
              .map((item: any) => ({
                userid: String(item?.userid || ''),
                name: String(item?.name || item?.userid || ''),
              }))
              .filter((item: WeworkAcquisitionMember) => item.userid)
          : [];
        if (!nextMembers.length) {
          throw new Error('当前团队没有可用于获客链接的企业微信成员');
        }
        if (cancelled) return;
        setMembers(nextMembers);
        setSelectedUserids(nextMembers.map((item: WeworkAcquisitionMember) => item.userid));
      } catch (err: any) {
        if (cancelled) return;
        const body = err?.response?.data;
        setError(body?.error || body?.message || err?.message || '读取跟进员工失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void loadMembers();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleMember = (userid: string) => {
    setSelectedUserids((current) =>
      current.includes(userid)
        ? current.filter((value) => value !== userid)
        : [...current, userid]
    );
  };

  const createLink = async () => {
    const cleanName = linkName.trim();
    if (!cleanName) {
      setError('请填写获客链接名称');
      return;
    }
    if (!selectedUserids.length) {
      setError('请至少选择一位跟进员工');
      return;
    }
    setCreating(true);
    setError('');
    try {
      const res = (await createWeworkAcquisitionLink({
        link_name: cleanName,
        userids: selectedUserids,
        skip_verify: true,
      })) as any;
      const body = res?.data ?? res;
      const data = body?.data ?? body;
      if (body?.success === false || !data?.link?.url) {
        throw new Error(body?.error || '企业微信未返回有效的获客链接');
      }
      const link = data.link as WeworkAcquisitionLink;
      const image = await QRCodeLib.toDataURL(link.url, {
        width: 224,
        margin: 1,
        color: { dark: '#0f172a', light: '#ffffff' },
      });
      setCreatedLink(link);
      setQrImageUrl(image);
      toastStore.success('企业微信获客链接已创建');
    } catch (err: any) {
      const body = err?.response?.data;
      setError(body?.error || body?.message || err?.message || '创建获客链接失败');
    } finally {
      setCreating(false);
    }
  };

  const copyLink = async () => {
    if (!createdLink?.url) return;
    try {
      await navigator.clipboard.writeText(createdLink.url);
      toastStore.success('获客链接已复制');
    } catch {
      toastStore.error('复制失败，请手动复制链接');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" onClick={onClose}>
      <div className="max-h-[88vh] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-6 shadow-xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
              <QrCode className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900">创建获客链接</h3>
              <p className="mt-0.5 text-xs text-gray-500">{channelLabel} · 当前登录团队</p>
            </div>
          </div>
          <button onClick={onClose} aria-label="关闭创建获客链接" className="rounded-md p-1 text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        {createdLink ? (
          <div className="mt-6">
            <div className="flex justify-center">
              <div className="flex h-64 w-64 items-center justify-center rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
                {qrImageUrl && <img src={qrImageUrl} alt="企业微信获客链接二维码" className="h-56 w-56" draggable={false} />}
              </div>
            </div>
            <div className="mt-4 rounded-lg bg-emerald-50 px-3 py-3">
              <div className="text-xs font-medium text-emerald-700">{createdLink.link_name}</div>
              <div className="mt-1 break-all text-xs text-emerald-800">{createdLink.url}</div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <button type="button" onClick={copyLink} className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
                <Copy className="h-4 w-4" />
                复制链接
              </button>
              <button type="button" onClick={() => window.open(createdLink.url, '_blank', 'noopener,noreferrer')} className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700">
                打开链接
              </button>
            </div>
            <button
              type="button"
              onClick={() => {
                setCreatedLink(null);
                setQrImageUrl('');
                setLinkName('客来来获客链接');
              }}
              className="mt-3 w-full rounded-lg px-4 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-50"
            >
              再创建一个
            </button>
          </div>
        ) : (
          <div className="mt-6 space-y-5">
            <div>
              <label className="text-sm font-medium text-gray-700">链接名称</label>
              <input
                value={linkName}
                maxLength={30}
                onChange={(event) => setLinkName(event.target.value)}
                placeholder="例如：官网咨询入口"
                className="mt-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
              />
              <div className="mt-1 text-right text-xs text-gray-400">{linkName.length}/30</div>
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-gray-700">跟进员工</label>
                <span className="text-xs text-gray-400">已选 {selectedUserids.length} 人</span>
              </div>
              <div className="mt-2 max-h-52 overflow-y-auto rounded-lg border border-gray-200">
                {loading ? (
                  <div className="flex items-center justify-center px-4 py-8 text-sm text-gray-500">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />读取企业微信成员…
                  </div>
                ) : members.map((member) => (
                  <label key={member.userid} className="flex cursor-pointer items-center gap-3 border-b border-gray-100 px-4 py-3 last:border-b-0 hover:bg-gray-50">
                    <input
                      type="checkbox"
                      checked={selectedUserids.includes(member.userid)}
                      onChange={() => toggleMember(member.userid)}
                      className="h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
                    />
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-gray-800">{member.name}</div>
                      <div className="truncate text-xs text-gray-400">{member.userid}</div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-700">
              链接只使用当前登录团队的企业微信授权创建，不会读取或复用其他账号的成员与客户数据。客户点击后将直接添加所选员工，并标记为本应用带来的客户。
            </div>

            {error && (
              <div className="flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="button"
              onClick={createLink}
              disabled={loading || creating || !selectedUserids.length || !linkName.trim()}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <QrCode className="h-4 w-4" />}
              {creating ? '创建中…' : '创建链接并生成二维码'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ========== 扫码授权弹窗 ========== */

/** 扫码状态机 */
type ScanStatus = 'waiting' | 'scanned' | 'success' | 'expired';

type WeWorkLoginOptions = {
  scriptUrl: string;
  appid: string;
  agentid: string;
  redirect_uri: string;
  state: string;
  href?: string;
  lang?: string;
  business_type?: string;
};

type WeWorkLoginInstance = {
  destroyed?: () => void;
};

declare global {
  interface Window {
    WwLogin?: new (options: Record<string, string>) => WeWorkLoginInstance;
  }
}

/** 渠道扫码授权弹窗 */
function ChannelScanModal({
  channel,
  onClose,
  onSuccess,
}: {
  channel: Channel;
  onClose: () => void;
  onSuccess: () => void | Promise<void>;
}) {
  const tip = channelScanTips[channel.type] ?? { app: '对应 App', description: '使用对应 App 扫描二维码' };
  const accentByType: Record<string, string> = {
    wechat: '#07C160',
    wework: '#2B7CE9',
    douyin: '#161823',
    miniprogram: '#07C160',
    pdd: '#E02E24',
    taobao: '#FF6F00',
    jd: '#E1251B',
    alibaba: '#FF6A00',
  };
  const accent = accentByType[channel.type] ?? '#3b82f6';

  const [status, setStatus] = useState<ScanStatus>('waiting');
  const [oauthUrl, setOauthUrl] = useState<string>('');
  const [oauthState, setOauthState] = useState<string>('');
  const [qrImageUrl, setQrImageUrl] = useState<string>('');
  const [weworkLogin, setWeworkLogin] = useState<WeWorkLoginOptions | null>(null);
  const [weworkContainerId] = useState(() => `kellai-wework-login-${Math.random().toString(36).slice(2)}`);
  const [countdown, setCountdown] = useState(300); // 5分钟过期
  const [initError, setInitError] = useState('');
  const [refreshSeed, setRefreshSeed] = useState(0);

  const oauthApi = channel.type === 'wechat'
    ? { initiate: initiateWechatOAuth, check: checkWechatOAuthStatus }
    : channel.type === 'wework'
      ? { initiate: initiateWeworkOAuth, check: checkWeworkOAuthStatus }
      : channel.type === 'douyin'
        ? { initiate: initiateDouyinOAuth, check: checkDouyinOAuthStatus }
        : null;

  // 发起 OAuth
  useEffect(() => {
    let cancelled = false;
    const initiate = async () => {
      if (!oauthApi) {
        setInitError(`${channelNameMap[channel.type] ?? channel.name} 暂未提供扫码授权接口，请使用凭据配置`);
        return;
      }
      try {
        setWeworkLogin(null);
        const res = (await oauthApi.initiate()) as any;
        const body = res?.data ?? res;
        const data = body?.data ?? body;
        if (data?.url && data?.state) {
          if (!cancelled) {
            setOauthUrl(data.url);
            setOauthState(data.state);
            let nextQrImageUrl = String(data.qr_proxy_url || data.qr_image_url || '');
            const qrText = String(data.qr_text || '');
            if (channel.type !== 'douyin' && !nextQrImageUrl && qrText) {
              nextQrImageUrl = await QRCodeLib.toDataURL(qrText, {
                width: 416,
                margin: 1,
                errorCorrectionLevel: 'M',
                color: { dark: '#101828', light: '#ffffff' },
              });
            }
            if (!cancelled) setQrImageUrl(nextQrImageUrl);
            const wwLogin = data.ww_login;
            if (data.embed_type === 'ww_login' && wwLogin) {
              setWeworkLogin({
                scriptUrl: String(data.script_url || 'https://wwcdn.weixin.qq.com/node/wework/wwopen/js/wwLogin-1.2.7.js'),
                appid: String(wwLogin.appid || ''),
                agentid: String(wwLogin.agentid || ''),
                redirect_uri: String(wwLogin.redirect_uri || ''),
                state: String(wwLogin.state || data.state),
                href: String(wwLogin.href || ''),
                lang: String(wwLogin.lang || 'zh_CN'),
                business_type: String(wwLogin.business_type || 'sso'),
              });
            }
            setCountdown(Number(data.expires_in || 300));
          }
        } else {
          if (!cancelled) setInitError(body?.error || data?.error || '获取授权链接失败');
        }
      } catch (err: any) {
        const data = err?.response?.data;
        if (!cancelled) setInitError(data?.error || data?.message || '获取授权链接失败');
      }
    };
    initiate();
    return () => { cancelled = true; };
  }, [channel.type, refreshSeed]);

  useEffect(() => {
    if (channel.type !== 'wework' || !weworkLogin || initError || status !== 'waiting') return;
    let cancelled = false;
    let instance: WeWorkLoginInstance | null = null;

    const loadScript = () =>
      new Promise<void>((resolve, reject) => {
        if (window.WwLogin) {
          resolve();
          return;
        }
        const existing = document.querySelector<HTMLScriptElement>('script[data-kellai-wework-login="1"]');
        if (existing) {
          existing.addEventListener('load', () => resolve(), { once: true });
          existing.addEventListener('error', () => reject(new Error('企业微信登录组件加载失败')), { once: true });
          return;
        }
        const script = document.createElement('script');
        script.src = weworkLogin.scriptUrl;
        script.async = true;
        script.dataset.kellaiWeworkLogin = '1';
        script.onload = () => resolve();
        script.onerror = () => reject(new Error('企业微信登录组件加载失败'));
        document.head.appendChild(script);
      });

    loadScript()
      .then(() => {
        if (cancelled) return;
        const LoginCtor = window.WwLogin;
        if (!LoginCtor) {
          setInitError('企业微信登录组件加载失败');
          return;
        }
        const container = document.getElementById(weworkContainerId);
        if (!container) {
          setInitError('企业微信扫码容器加载失败');
          return;
        }
        instance = new LoginCtor({
          id: weworkContainerId,
          appid: weworkLogin.appid,
          agentid: weworkLogin.agentid,
          redirect_uri: weworkLogin.redirect_uri,
          state: weworkLogin.state,
          href: weworkLogin.href || '',
          lang: weworkLogin.lang || 'zh_CN',
          business_type: weworkLogin.business_type || 'sso',
        });
      })
      .catch((err: Error) => {
        if (!cancelled) setInitError(err.message || '企业微信登录组件加载失败');
      });

    return () => {
      cancelled = true;
      instance?.destroyed?.();
      const container = document.getElementById(weworkContainerId);
      if (container) container.replaceChildren();
    };
  }, [channel.type, initError, status, weworkContainerId, weworkLogin]);

  // 轮询授权状态
  useEffect(() => {
    if (!oauthState || (status !== 'waiting' && status !== 'scanned')) return;
    const interval = setInterval(async () => {
      try {
        if (!oauthApi) return;
        const res = (await oauthApi.check(oauthState)) as any;
        const body = res?.data ?? res;
        const data = body?.data ?? body;
        if (data?.authorized) {
          setStatus('scanned');
          if (channel.type === 'wework') {
            try {
              await syncWeworkCustomers();
            } catch (err: any) {
              const errorBody = err?.response?.data;
              setInitError(errorBody?.error || errorBody?.message || '企业微信已授权，但客户列表同步失败');
              return;
            }
          }
          setTimeout(() => setStatus('success'), 800);
        } else if (data?.scanned) {
          setStatus('scanned');
        } else if (data?.expired) {
          setStatus('expired');
        } else if (data?.canceled) {
          setStatus('expired');
        }
      } catch {
        // 忽略轮询错误
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [channel.type, oauthState, status]);

  // 倒计时
  useEffect(() => {
    if (initError) return;
    if (status !== 'waiting' && status !== 'scanned') return;
    if (countdown <= 0) {
      setStatus('expired');
      return;
    }
    const t = window.setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => window.clearTimeout(t);
  }, [countdown, initError, status]);

  // 成功后回调
  useEffect(() => {
    if (status !== 'success') return;
    const t = window.setTimeout(() => {
      void onSuccess();
    }, 1200);
    return () => window.clearTimeout(t);
  }, [status, onSuccess]);

  const refresh = () => {
    setStatus('waiting');
    setOauthUrl('');
    setOauthState('');
    setQrImageUrl('');
    setWeworkLogin(null);
    setCountdown(300);
    setInitError('');
    setRefreshSeed((value) => value + 1);
  };

  const channelLabel = channelNameMap[channel.type] ?? channel.name;

  // 格式化倒计时
  const formatCountdown = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

  return (
    <div data-tour="channel-config-modal" className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div
        data-tour="channel-config-modal-body"
        className="relative w-full max-w-sm overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="h-1.5 w-full" style={{ background: accent }} />
        <button
          onClick={onClose}
          aria-label="关闭配置"
          data-tour="channel-config-cancel"
          className="absolute right-3 top-5 z-10 rounded-md p-1 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600"
        >
          <X className="h-5 w-5" />
        </button>

        <div className="p-7">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg" style={{ background: `${accent}1a` }}>
              <QrCode className="h-5 w-5" style={{ color: accent }} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900">{tip.app} 扫码授权</h3>
              <p className="mt-0.5 text-xs text-gray-500">连接 {channelLabel}</p>
            </div>
          </div>

          <div className="mt-6 flex flex-col items-center">
            <div
              data-tour="channel-qrcode"
              className={clsx(
                'relative rounded-2xl border p-3 transition-all duration-500',
                status === 'success' ? 'border-green-200 bg-green-50/40' : 'border-gray-200 bg-white'
              )}
            >
              {/* 已扫描遮罩 */}
              {status === 'scanned' && (
                <div className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-xl bg-white/95">
                  <div className="flex h-16 w-16 animate-pulse items-center justify-center rounded-full bg-blue-100">
                    <ScanLine className="h-8 w-8 text-blue-600" />
                  </div>
                  <p className="mt-3 text-sm font-semibold text-gray-900">已扫描，请在手机上确认</p>
                  <p className="mt-1 text-xs text-gray-500">等待 {tip.app} 授权…</p>
                </div>
              )}

              {/* 成功遮罩 */}
              {status === 'success' && (
                <div className="absolute inset-0 z-20 flex flex-col items-center justify-center rounded-xl bg-white/95">
                  <div className="flex h-16 w-16 animate-[ping_1.2s_ease-out] items-center justify-center rounded-full bg-green-100">
                    <ShieldCheck className="h-9 w-9 text-green-600" />
                  </div>
                  <p className="mt-3 text-sm font-semibold text-green-700">授权成功</p>
                  <p className="mt-1 text-xs text-gray-500">{channelLabel} 已连接</p>
                </div>
              )}

              {/* 过期遮罩 */}
              {status === 'expired' && (
                <div className="absolute inset-0 z-20 flex flex-col items-center justify-center rounded-xl bg-white/95">
                  <XCircle className="h-12 w-12 text-gray-400" />
                  <p className="mt-2 text-sm font-semibold text-gray-700">二维码已过期</p>
                  <button
                    onClick={refresh}
                    className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
                  >
                    <RefreshCw className="h-3.5 w-3.5" /> 刷新二维码
                  </button>
                </div>
              )}

              {/* QR 码主体 */}
              <div className={clsx('transition-opacity duration-300', status === 'expired' ? 'opacity-20' : 'opacity-100')}>
                {initError ? (
                  <div className="flex h-[208px] w-[208px] flex-col items-center justify-center rounded-lg bg-gray-50 text-center">
                    <AlertCircle className="h-8 w-8 text-amber-500" />
                    <p className="mt-2 text-xs text-gray-600">{initError}</p>
                    <button
                      onClick={refresh}
                      className="mt-2 text-xs text-blue-600 hover:underline"
                    >
                      重试
                    </button>
                  </div>
                ) : channel.type === 'douyin' && oauthUrl ? (
                  <div className="flex h-[208px] w-[208px] flex-col items-center justify-center rounded-lg bg-gray-50 text-center">
                    <ShieldCheck className="h-9 w-9 text-gray-500" />
                    <p className="mt-2 px-3 text-xs leading-relaxed text-gray-600">
                      抖音限制 App 内直接扫码 OAuth 链接。请打开官方授权页，扫页面内的抖音二维码完成绑定。
                    </p>
                    <button
                      type="button"
                      onClick={() => window.open(oauthUrl, '_blank', 'noopener,noreferrer')}
                      className="mt-3 rounded-lg bg-slate-950 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
                    >
                      打开官方授权页
                    </button>
                  </div>
                ) : qrImageUrl ? (
                  <img
                    src={qrImageUrl}
                    width="208"
                    height="208"
                    alt={`${channelLabel} 扫码授权二维码`}
                    className="h-[208px] w-[208px] rounded-lg object-contain"
                  />
                ) : weworkLogin && channel.type === 'wework' ? (
                  <div className="h-[400px] w-[300px] overflow-hidden rounded-lg bg-white">
                    <div id={weworkContainerId} className="h-[400px] w-[300px]" />
                  </div>
                ) : oauthUrl && channel.type === 'wechat' ? (
                  <div className="flex h-[208px] w-[208px] flex-col items-center justify-center rounded-lg bg-gray-50 text-center">
                    <QrCode className="h-9 w-9 text-gray-400" />
                    <p className="mt-2 px-3 text-xs leading-relaxed text-gray-600">
                      未能直接解析二维码，请打开官方授权页完成扫码。
                    </p>
                    <button
                      type="button"
                      onClick={() => window.open(oauthUrl, '_blank', 'noopener,noreferrer')}
                      className="mt-3 rounded-lg bg-slate-950 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
                    >
                      打开授权页
                    </button>
                  </div>
                ) : oauthUrl ? (
                  <iframe
                    src={oauthUrl}
                    width="208"
                    height="208"
                    frameBorder="0"
                    sandbox="allow-scripts allow-same-origin"
                    style={{ borderRadius: '8px' }}
                    title={`${channelLabel} 扫码授权`}
                  />
                ) : (
                  <div className="flex h-[208px] w-[208px] items-center justify-center">
                    <Loader2 className="h-8 w-8 animate-spin text-gray-300" />
                  </div>
                )}
              </div>
            </div>

            {/* 倒计时 / 状态行 */}
            <div className="mt-4 flex items-center gap-2 text-xs text-gray-500">
              {initError ? (
                <>
                  <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
                  <span className="text-amber-700">请先完成必填配置后再生成二维码</span>
                </>
              ) : status === 'waiting' && (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" style={{ color: accent }} />
                  <span>
                    {channel.type === 'douyin' ? '授权链接' : '二维码'} <b className="text-gray-700 tabular-nums">{formatCountdown(countdown)}</b> 后失效
                  </span>
                </>
              )}
              {status === 'scanned' && (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />
                  <span>已扫码，等待授权中…</span>
                </>
              )}
              {status === 'success' && (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                  <span className="text-green-700">授权成功，正在保存配置…</span>
                </>
              )}
              {status === 'expired' && (
                <span>请点击上方"刷新二维码"重新生成</span>
              )}
            </div>
          </div>

          {/* 底部操作 */}
          <div className="mt-6 flex items-center justify-between gap-3">
            <button
              onClick={refresh}
              disabled={status === 'scanned' || status === 'success'}
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium text-gray-600 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              刷新二维码
            </button>
            <button
              onClick={onClose}
              className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 transition hover:bg-gray-50"
            >
              稍后再说
            </button>
          </div>

          <p className="mt-4 rounded-lg bg-gray-50 px-3 py-2 text-[11px] leading-relaxed text-gray-500">
            💡 {tip.description}
          </p>
        </div>
      </div>
    </div>
  );
}

/* ========== Tab 2：AI 助手 ========== */

function AIAssistantTab() {
  type LlmDiagnostics = {
    config_path?: string;
    config_exists?: boolean;
    saved_provider?: string;
    saved_model?: string;
    saved_has_api_key?: boolean;
    effective_provider?: string;
    effective_model?: string;
    effective_base_url?: string;
    effective_source?: string;
    effective_has_api_key?: boolean;
    dotenvs?: Array<{ path?: string; exists?: boolean; llm_keys_present?: string[] }>;
    env_presence?: Record<string, boolean>;
    last_probe?: { success?: boolean; checked_at?: string; provider?: string; model?: string; latency_ms?: number; error?: string };
  };
  const [config, setConfig] = useState<LLMConfig>({
    model: 'xcauto',
    llmModel: '',
    baseUrl: '',
    keyPrefix: '',
    apiKey: '',
    connected: false,
    autoReplyEnabled: false,
    autoReplyStages: [],
    confirmScenarios: [],
  });
  const [showApiKey, setShowApiKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [probing, setProbing] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  const [saveMessageType, setSaveMessageType] = useState<'success' | 'error' | 'info'>('info');
  const [diagnostics, setDiagnostics] = useState<LlmDiagnostics | null>(null);
  const [autoReplyRuntime, setAutoReplyRuntime] = useState<AutoReplyRuntimeStatus | null>(null);

  const refreshDiagnostics = useCallback(() => {
    getLlmDiagnostics()
      .then((res) => {
        const data = (res as any)?.data?.data ?? (res as any)?.data ?? res;
        setDiagnostics(data && typeof data === 'object' ? data : null);
      })
      .catch(() => setDiagnostics(null));
  }, []);

  const refreshAutoReplyRuntime = useCallback(() => {
    getAutoReplyRuntimeStatus()
      .then((res) => {
        const data = (res as any)?.data?.data ?? (res as any)?.data ?? res;
        setAutoReplyRuntime(data && typeof data === 'object' ? data : null);
      })
      .catch(() => setAutoReplyRuntime(null));
  }, []);

  useEffect(() => {
    getLlmStatus()
      .then((res) => {
        const data = (res as any)?.data?.data ?? (res as any)?.data ?? res;
        if (data && typeof data === 'object') {
          const provider = normalizeLlmProvider(String(data.provider || data.model || config.model));
          setConfig((prev) => ({
            ...prev,
            model: provider,
            llmModel: String(data.model || prev.llmModel || ''),
            baseUrl: String(data.base_url || prev.baseUrl || ''),
            keyPrefix: String(data.key_prefix || prev.keyPrefix || ''),
            message: String(data.message || prev.message || ''),
            connected: Boolean(data.connected ?? prev.connected),
            autoReplyEnabled: data.autoReplyEnabled ?? prev.autoReplyEnabled,
            autoReplyStages: data.autoReplyStages ?? prev.autoReplyStages,
            confirmScenarios: data.confirmScenarios ?? prev.confirmScenarios,
          }));
        }
      })
      .catch(() => {});
    refreshDiagnostics();
    refreshAutoReplyRuntime();
    const timer = window.setInterval(refreshAutoReplyRuntime, 10_000);
    return () => window.clearInterval(timer);
  }, [refreshDiagnostics, refreshAutoReplyRuntime]);

  const handleSave = async () => {
    setSaving(true);
    setSaveMessage('');
    try {
      const provider = normalizeLlmProvider(config.model);
      const res = await saveLlmConfig({
        provider: provider === 'xcauto' ? 'auto' : provider,
        model: config.llmModel || LLM_DEFAULT_PARAMS[provider]?.model || '',
        base_url: config.baseUrl || LLM_DEFAULT_PARAMS[provider]?.baseUrl || '',
        api_key: config.apiKey,
        auto_reply_enabled: config.autoReplyEnabled,
        auto_reply_stages: config.autoReplyStages,
        confirm_scenarios: config.confirmScenarios,
      });
      const data = (res as any)?.data?.data ?? (res as any)?.data ?? res;
      const connected = Boolean(data?.connected);
      setConfig((prev) => ({
        ...prev,
        model: normalizeLlmProvider(String(data?.provider || provider)),
        llmModel: String(data?.model || prev.llmModel || ''),
        baseUrl: String(data?.base_url || prev.baseUrl || ''),
        keyPrefix: String(data?.key_prefix || prev.keyPrefix || ''),
        message: String(data?.message || prev.message || ''),
        apiKey: '',
        connected,
        autoReplyEnabled: Boolean(data?.autoReplyEnabled ?? prev.autoReplyEnabled),
        autoReplyStages: Array.isArray(data?.autoReplyStages) ? data.autoReplyStages : prev.autoReplyStages,
        confirmScenarios: Array.isArray(data?.confirmScenarios) ? data.confirmScenarios : prev.confirmScenarios,
      }));
      setSaveMessageType(connected ? 'success' : 'error');
      setSaveMessage(data?.message || (connected ? '配置已保存并连通' : '配置已保存，但真实连通测试未通过'));
      refreshDiagnostics();
      refreshAutoReplyRuntime();
    } catch (error) {
      setSaveMessageType('error');
      setSaveMessage('保存失败，请检查后端服务和 API Key');
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMessage(''), 3000);
    }
  };

  const handleProbe = async () => {
    setProbing(true);
    setSaveMessage('');
    try {
      const res = await probeLlmConfig();
      const data = (res as any)?.data?.data ?? (res as any)?.data ?? res;
      const connected = Boolean(data?.connected);
      setConfig((prev) => ({
        ...prev,
        model: normalizeLlmProvider(String(data?.provider || prev.model)),
        llmModel: String(data?.model || prev.llmModel || ''),
        baseUrl: String(data?.base_url || prev.baseUrl || ''),
        keyPrefix: String(data?.key_prefix || prev.keyPrefix || ''),
        message: String(data?.message || prev.message || ''),
        connected,
      }));
      const probe = data?.probe || data?.lastProbe || {};
      setSaveMessageType(connected ? 'success' : 'error');
      setSaveMessage(connected ? '真实 LLM 连通测试通过' : String(probe?.error || data?.message || '真实 LLM 连通测试未通过'));
      refreshDiagnostics();
    } catch {
      setSaveMessageType('error');
      setSaveMessage('测试连接失败，请检查后端服务');
    } finally {
      setProbing(false);
      setTimeout(() => setSaveMessage(''), 4000);
    }
  };

  return (
    <div data-tour="settings-ai">
      <h2 className="text-lg font-semibold text-gray-900">AI 助手配置</h2>
      <p className="mt-1 text-sm text-gray-500">配置 LLM 模型与自动回复策略</p>

      <div className="mt-6 space-y-6">
        {/* 模型配置 */}
        <div data-tour="ai-model-card" className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-800">模型配置</h3>
          <div className="mt-4 space-y-4">
            {/* LLM 模型选择 */}
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">LLM 模型</label>
              <div className="relative">
                <select
                  value={config.model}
                  onChange={(e) => {
                    const provider = normalizeLlmProvider(e.target.value);
                    const defaults = LLM_DEFAULT_PARAMS[provider];
                    setConfig({
                      ...config,
                      model: provider,
                      llmModel: config.llmModel || defaults?.model || '',
                      baseUrl: config.baseUrl || defaults?.baseUrl || '',
                    });
                  }}
                  aria-label="LLM 模型"
                  className="w-full appearance-none rounded-lg border border-gray-300 px-3 py-2 pr-8 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  {LLM_MODELS.map((m) => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              </div>
            </div>

            {/* 模型名称 */}
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">模型名称</label>
              <input
                type="text"
                value={config.llmModel ?? ''}
                onChange={(e) => setConfig({ ...config, llmModel: e.target.value })}
                placeholder={LLM_DEFAULT_PARAMS[config.model]?.model || '请输入模型名'}
                aria-label="模型名称"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            {/* Base URL */}
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Base URL</label>
              <input
                type="text"
                value={config.baseUrl ?? ''}
                onChange={(e) => setConfig({ ...config, baseUrl: e.target.value })}
                placeholder={LLM_DEFAULT_PARAMS[config.model]?.baseUrl || 'https://example.com/v1'}
                aria-label="Base URL"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            {/* API Key */}
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">API Key</label>
              <div className="relative">
                <input
                  type={showApiKey ? 'text' : 'password'}
                  value={config.apiKey}
                  onChange={(e) => setConfig({ ...config, apiKey: e.target.value })}
                  placeholder="请输入 API Key"
                  aria-label="API Key"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <button
                  type="button"
                  onClick={() => setShowApiKey(!showApiKey)}
                  aria-label={showApiKey ? '隐藏 API Key' : '显示 API Key'}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {/* 连接状态 */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-500">连接状态：</span>
              {config.connected ? (
                <span className="flex items-center gap-1 text-xs font-medium text-green-600">
                  <CheckCircle2 className="h-3.5 w-3.5" /> 已连接
                </span>
              ) : (
                <span className="flex items-center gap-1 text-xs font-medium text-gray-400">
                  <XCircle className="h-3.5 w-3.5" /> 未连接
                </span>
              )}
              {config.keyPrefix && (
                <span className="rounded bg-gray-100 px-2 py-0.5 text-[11px] text-gray-500">{config.keyPrefix}</span>
              )}
            </div>

            {diagnostics && (
              <div className="rounded-lg border border-gray-100 bg-gray-50 p-3 text-xs text-gray-600">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    {diagnostics.effective_has_api_key ? (
                      <CheckCircle2 className="h-4 w-4 text-green-500" />
                    ) : (
                      <AlertCircle className="h-4 w-4 text-amber-500" />
                    )}
                    <span className="font-medium text-gray-700">后端读取诊断</span>
                  </div>
                  <button
                    type="button"
                    onClick={refreshDiagnostics}
                    className="text-blue-600 hover:text-blue-700"
                  >
                    刷新
                  </button>
                </div>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  <div>
                    <span className="text-gray-400">配置文件：</span>
                    {diagnostics.config_exists ? '已存在' : '不存在'}
                  </div>
                  <div>
                    <span className="text-gray-400">有效来源：</span>
                    {diagnostics.effective_source || '未读取到 Key'}
                  </div>
                  <div>
                    <span className="text-gray-400">有效模型：</span>
                    {diagnostics.effective_model || diagnostics.saved_model || '-'}
                  </div>
                  <div>
                    <span className="text-gray-400">最近探测：</span>
                    {diagnostics.last_probe?.success ? '通过' : diagnostics.last_probe?.error || '未探测'}
                  </div>
                </div>
                <p className="mt-2 break-all text-[11px] text-gray-400">
                  {diagnostics.config_path}
                </p>
                {!diagnostics.effective_has_api_key && (
                  <div className="mt-2 rounded-md bg-amber-50 px-2 py-1.5 text-amber-700">
                    当前后端没有读到真实 API Key。请在本页保存 API Key，或在项目根目录、`backend`、`desktop` 下的 `.env` / `.env.local` / `.env.production` 写入对应环境变量后重启后端。
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* 自动回复策略 */}
        <div data-tour="ai-auto-reply-card" className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-800">自动回复策略</h3>
          <div className="mt-4 space-y-4">
            {/* 启用自动回复 */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-700">启用自动回复</p>
                <p className="text-xs text-gray-400">AI 将根据配置自动回复客户消息</p>
              </div>
              <Toggle
                checked={config.autoReplyEnabled}
                onChange={(v) => setConfig({ ...config, autoReplyEnabled: v })}
                ariaLabel="启用自动回复"
              />
            </div>

            <div className={clsx(
              'rounded-lg border px-3 py-2.5 text-xs',
              autoReplyRuntime?.enabled
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : 'border-gray-200 bg-gray-50 text-gray-500',
            )}>
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium">
                  {autoReplyRuntime?.enabled ? '真实客户自动回复运行中' : '真实客户自动回复未开启'}
                </span>
                {autoReplyRuntime?.enabled && (
                  <span className="h-2 w-2 rounded-full bg-emerald-500" aria-label="运行中" />
                )}
              </div>
              <p className="mt-1 leading-relaxed">
                保持客来来与对应渠道客户端登录；桌面端约每 5 秒检查一次新消息并自动发送。
              </p>
              {autoReplyRuntime?.counts && (
                <p className="mt-1 text-[11px]">
                  已发送 {Number(autoReplyRuntime.counts.sent || 0)} 条 ·
                  待处理 {Number(autoReplyRuntime.counts.pending || 0) + Number(autoReplyRuntime.counts.processing || 0)} 条 ·
                  失败重试 {Number(autoReplyRuntime.counts.failed || 0)} 条
                </p>
              )}
              {autoReplyRuntime?.latest?.last_error && (
                <p className="mt-1 break-words text-[11px] text-red-600">
                  最近失败：{autoReplyRuntime.latest.last_error}
                </p>
              )}
            </div>

            {/* 适用阶段 */}
            <div>
              <p className="mb-2 text-sm font-medium text-gray-700">适用阶段</p>
              <MultiSelectTags
                options={AUTO_REPLY_STAGES}
                selected={config.autoReplyStages}
                onChange={(v) => setConfig({ ...config, autoReplyStages: v })}
              />
            </div>

            {/* 安全兜底场景 */}
            <div>
              <p className="mb-2 text-sm font-medium text-gray-700">安全兜底场景</p>
              <p className="mb-2 text-xs text-gray-400">价格、合同和交付等敏感问题会自动回复“已收到，核实后回复”，不直接承诺。</p>
              <MultiSelectTags
                options={CONFIRM_SCENARIOS}
                selected={config.confirmScenarios}
                onChange={(v) => setConfig({ ...config, confirmScenarios: v })}
              />
            </div>
          </div>
        </div>

        {/* 保存按钮 */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving || probing}
            aria-label="保存配置"
            data-tour="ai-save-config"
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? '保存中...' : '保存配置'}
          </button>
          <button
            onClick={handleProbe}
            disabled={saving || probing}
            aria-label="测试 LLM 连接"
            className="rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-50"
          >
            {probing ? '测试中...' : '测试连接'}
          </button>
          {saveMessage && (
            <span
              className={clsx(
                'flex items-center gap-1 text-sm',
                saveMessageType === 'success' ? 'text-green-600' : saveMessageType === 'error' ? 'text-red-500' : 'text-gray-500'
              )}
            >
              {saveMessageType === 'error' ? <AlertCircle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />} {saveMessage}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ========== Tab 3：跟进规则 ========== */

function FollowUpTab() {
  const [rules, setRules] = useState<FollowUpStageRule[]>(DEFAULT_FOLLOW_UP_RULES);
  const [templates] = useState<SOPTemplate[]>(DEFAULT_SOP_TEMPLATES);
  const [expandedTemplate, setExpandedTemplate] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');

  const handleSave = async () => {
    setSaving(true);
    setSaveMessage('');
    await new Promise((r) => setTimeout(r, 800));
    setSaving(false);
    setSaveMessage('规则已保存');
    setTimeout(() => setSaveMessage(''), 3000);
  };

  /** 切换提醒方式 */
  const toggleRemindMethod = (ruleIndex: number, method: string) => {
    setRules((prev) =>
      prev.map((rule, i) => {
        if (i !== ruleIndex) return rule;
        const methods = rule.remindMethods.includes(method)
          ? rule.remindMethods.filter((m) => m !== method)
          : [...rule.remindMethods, method];
        return { ...rule, remindMethods: methods };
      })
    );
  };

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900">跟进规则</h2>
      <p className="mt-1 text-sm text-gray-500">配置各阶段超时提醒与 SOP 模板</p>

      <div className="mt-6 space-y-6">
        {/* 超时时间配置 */}
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-100 px-5 py-4">
            <h3 className="text-sm font-semibold text-gray-800">阶段超时配置</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="px-5 py-3 text-left font-medium text-gray-500">阶段名称</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">超时时间（天）</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">提醒方式</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule, idx) => (
                  <tr key={rule.stage} className="border-b border-gray-50 last:border-0">
                    <td className="px-5 py-3 font-medium text-gray-900">{rule.stageLabel}</td>
                    <td className="px-5 py-3">
                      <input
                        type="number"
                        min={1}
                        value={rule.timeoutDays}
                        onChange={(e) =>
                          setRules((prev) =>
                            prev.map((r, i) =>
                              i === idx ? { ...r, timeoutDays: Number(e.target.value) || 1 } : r
                            )
                          )
                        }
                        aria-label={`${rule.stageLabel} 超时时间`}
                        className="w-20 rounded-lg border border-gray-300 px-2 py-1 text-center text-sm text-black placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-slate-600 dark:text-white"
                      />
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        {REMIND_METHOD_OPTIONS.map((method) => (
                          <button
                            key={method}
                            type="button"
                            onClick={() => toggleRemindMethod(idx, method)}
                            aria-label={`${rule.stageLabel} ${method}提醒`}
                            className={clsx(
                              'rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors',
                              rule.remindMethods.includes(method)
                                ? 'bg-blue-100 text-blue-700 ring-1 ring-blue-300'
                                : 'bg-gray-100 text-gray-400 hover:bg-gray-200'
                            )}
                          >
                            {method}
                          </button>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* SOP 模板管理 */}
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-100 px-5 py-4">
            <h3 className="text-sm font-semibold text-gray-800">SOP 模板</h3>
          </div>
          <div className="divide-y divide-gray-50">
            {templates.map((tpl) => (
              <div key={tpl.id} className="px-5 py-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{tpl.name}</p>
                    <p className="mt-0.5 text-xs text-gray-400">
                      适用阶段：{tpl.stage} · {tpl.stepsCount} 个步骤
                    </p>
                  </div>
                  <button
                    onClick={() => setExpandedTemplate(expandedTemplate === tpl.id ? null : tpl.id)}
                    aria-label={`${expandedTemplate === tpl.id ? '收起' : '查看'} ${tpl.name} 详情`}
                    className="rounded-lg border border-gray-200 px-3 py-1 text-xs font-medium text-gray-600 transition hover:bg-gray-50"
                  >
                    {expandedTemplate === tpl.id ? '收起' : '查看'}
                  </button>
                </div>
                {/* 步骤详情 */}
                {expandedTemplate === tpl.id && (
                  <div className="mt-3 space-y-2 pl-4">
                    {tpl.steps.map((step, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-medium text-blue-700">
                          {i + 1}
                        </span>
                        <p className="text-sm text-gray-600">{step}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* 保存按钮 */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? '保存中...' : '保存规则'}
          </button>
          {saveMessage && (
            <span className="flex items-center gap-1 text-sm text-green-600">
              <CheckCircle2 className="h-4 w-4" /> {saveMessage}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ========== Tab 4：团队管理 ========== */

function TeamTab() {
  const [teamInfo, setTeamInfo] = useState<TeamInfo | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [inviteEmail, setInviteEmail] = useState('');
  const [invitePhone, setInvitePhone] = useState('');
  const [inviteRole, setInviteRole] = useState('sales');
  const [inviting, setInviting] = useState(false);
  const [inviteMessage, setInviteMessage] = useState('');
  const [copied, setCopied] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([getTeamInfo(), getTeamMembers()])
      .then(([teamRes, membersRes]) => {
        const teamData = (teamRes as any)?.data ?? teamRes;
        const membersData = (membersRes as any)?.data ?? membersRes;
        if (teamData) setTeamInfo(teamData as TeamInfo);
        setMembers(Array.isArray(membersData) ? membersData : []);
      })
      .catch(() => setError('加载团队信息失败'))
      .finally(() => setLoading(false));
  }, []);

  /** 邀请成员 */
  const handleInvite = async () => {
    if (!inviteEmail && !invitePhone) return;
    setInviting(true);
    setInviteMessage('');
    try {
      await inviteMember(inviteEmail, invitePhone, inviteRole);
      setInviteMessage('邀请已发送');
      setInviteEmail('');
      setInvitePhone('');
      // 刷新成员列表
      const res = await getTeamMembers();
      const data = (res as any)?.data ?? res;
      setMembers(Array.isArray(data) ? data : members);
    } catch {
      setInviteMessage('邀请失败，请重试');
    } finally {
      setInviting(false);
      setTimeout(() => setInviteMessage(''), 3000);
    }
  };

  /** 修改角色 */
  const handleRoleChange = async (userId: number, role: string) => {
    try {
      await updateMemberRole(userId, role);
      setMembers((prev) =>
        prev.map((m) => (m.userId === userId ? { ...m, role: role as TeamMember['role'] } : m))
      );
    } catch {
      // 静默失败
    }
  };

  /** 复制邀请码 */
  const handleCopyCode = () => {
    if (teamInfo?.inviteCode) {
      navigator.clipboard.writeText(teamInfo.inviteCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-gray-400" /><span className="ml-2 text-sm text-gray-400">加载中...</span></div>;
  }

  if (error) {
    return <div className="flex items-center justify-center py-20"><AlertCircle className="h-5 w-5 text-red-400" /><span className="ml-2 text-sm text-red-500">{error}</span></div>;
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900">团队管理</h2>
      <p className="mt-1 text-sm text-gray-500">管理团队成员与权限</p>

      <div className="mt-6 space-y-6">
        {/* 团队信息卡片 */}
        {teamInfo && (
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-semibold text-gray-900">{teamInfo.name}</h3>
                <p className="mt-1 text-sm text-gray-500">{teamInfo.memberCount} 名成员</p>
              </div>
              <div className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2">
                <span className="text-xs text-gray-500">邀请码：</span>
                <span className="font-mono text-sm font-semibold text-gray-900">{teamInfo.inviteCode}</span>
                <button
                  onClick={handleCopyCode}
                  className="rounded p-1 text-gray-400 transition hover:text-blue-600"
                >
                  {copied ? <CheckCircle2 className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 邀请成员 */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-800">邀请成员</h3>
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <div className="min-w-[180px] flex-1">
              <label className="mb-1 block text-xs font-medium text-gray-500">邮箱</label>
              <input
                type="email"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="member@example.com"
                aria-label="邀请邮箱"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-black placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div className="min-w-[180px] flex-1">
              <label className="mb-1 block text-xs font-medium text-gray-500">手机号</label>
              <input
                type="tel"
                value={invitePhone}
                onChange={(e) => setInvitePhone(e.target.value)}
                placeholder="选填"
                aria-label="邀请手机号"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-black placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div className="min-w-[120px]">
              <label className="mb-1 block text-xs font-medium text-gray-500">角色</label>
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
                aria-label="邀请角色"
                className="w-full appearance-none rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {ROLE_OPTIONS.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>
            <button
              onClick={handleInvite}
              disabled={inviting || (!inviteEmail && !invitePhone)}
              aria-label="邀请成员"
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
            >
              {inviting ? '邀请中...' : '邀请'}
            </button>
          </div>
          {inviteMessage && (
            <p className={clsx('mt-2 text-xs', inviteMessage.includes('失败') ? 'text-red-500' : 'text-green-600')}>
              {inviteMessage}
            </p>
          )}
        </div>

        {/* 成员列表 */}
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-100 px-5 py-4">
            <h3 className="text-sm font-semibold text-gray-800">成员列表</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="px-5 py-3 text-left font-medium text-gray-500">成员</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">邮箱</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">角色</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">加入时间</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">操作</th>
                </tr>
              </thead>
              <tbody>
                {members.map((member) => (
                  <tr key={member.userId} className="border-b border-gray-50 last:border-0">
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 text-xs font-medium text-white">
                          {member.displayName?.charAt(0) ?? 'U'}
                        </div>
                        <span className="font-medium text-gray-900">{member.displayName}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3 text-gray-500">{member.email}</td>
                    <td className="px-5 py-3">
                      <select
                        value={member.role}
                        onChange={(e) => handleRoleChange(member.userId, e.target.value)}
                        aria-label={`设置 ${member.displayName} 的角色`}
                        className="appearance-none rounded-md border border-gray-200 px-2 py-1 text-xs font-medium focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      >
                        {ROLE_OPTIONS.map((r) => (
                          <option key={r.value} value={r.value}>{r.label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-5 py-3 text-gray-500">{member.joinedAt?.slice(0, 10) ?? '-'}</td>
                    <td className="px-5 py-3">
                      {confirmRemove === member.userId ? (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-red-500">确认移除？</span>
                          <button
                            onClick={() => {
                              setMembers((prev) => prev.filter((m) => m.userId !== member.userId));
                              setConfirmRemove(null);
                            }}
                            className="text-xs font-medium text-red-600 hover:text-red-700"
                          >
                            确认
                          </button>
                          <button
                            onClick={() => setConfirmRemove(null)}
                            className="text-xs font-medium text-gray-400 hover:text-gray-600"
                          >
                            取消
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setConfirmRemove(member.userId)}
                          className="flex items-center gap-1 text-xs text-gray-400 transition hover:text-red-500"
                        >
                          <Trash2 className="h-3.5 w-3.5" /> 移除
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ========== Tab 5：个人设置 ========== */

function ProfileTab() {
  const [displayName, setDisplayName] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [notifications, setNotifications] = useState<NotificationPreferences>({
    desktopNotification: true,
    highIntentNotification: true,
    followUpReminder: true,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [mockReloading, setMockReloading] = useState(false);
  // Mock 数据开关
  const [mockOn, setMockOn] = useState<boolean>(() => {
    if (!import.meta.env.DEV) return false;
    try {
      return localStorage.getItem('kellai:useMock') === '1';
    } catch {
      return false;
    }
  });
  const toggleMock = (v: boolean) => {
    if (!import.meta.env.DEV) return;
    setMockOn(v);
    setMockReloading(true);
    try {
      if (v) localStorage.setItem('kellai:useMock', '1');
      else localStorage.removeItem('kellai:useMock');
    } catch {
      // ignore
    }
    window.setTimeout(() => window.location.reload(), 450);
  };
  const [saveMessage, setSaveMessage] = useState('');

  // 新手教程
  const resetOnboarding = useOnboardingStore((s) => s.reset);
  const setOnboardingActive = useOnboardingStore((s) => s.setActive);
  const onboardingState = useOnboardingStore((s) => s.state);
  const onboardingLabel =
    onboardingState === "completed"
      ? "已完成"
      : onboardingState === "skipped"
      ? "已跳过"
      : "未开始";

  useEffect(() => {
    void preloadTextToSpeech(ONBOARDING_WELCOME_SPEECH_TEXT, ONBOARDING_WELCOME_CACHE_KEY);
  }, []);

  const handleRestartOnboarding = () => {
    unlockTextToSpeechAudio();
    const speechWindow = window as OnboardingSpeechWindow;
    const fallbackUntil = Date.now() + estimateSpeechHoldMs(ONBOARDING_WELCOME_SPEECH_TEXT, null);
    const preplayed = playPreparedTextToSpeech(
      ONBOARDING_WELCOME_SPEECH_TEXT,
      ONBOARDING_WELCOME_CACHE_KEY,
      {
        onPlaybackStart: (info) => {
          speechWindow.__kellaiOnboardingWelcomePreplayedUntil =
            Date.now() + estimateSpeechHoldMs(ONBOARDING_WELCOME_SPEECH_TEXT, info.durationSeconds);
        },
        onPlaybackError: () => {
          speechWindow.__kellaiOnboardingWelcomePreplayedUntil = 0;
        },
      }
    );
    if (preplayed) {
      speechWindow.__kellaiOnboardingWelcomePreplayedUntil = fallbackUntil;
    } else {
      void preloadTextToSpeech(ONBOARDING_WELCOME_SPEECH_TEXT, ONBOARDING_WELCOME_CACHE_KEY);
    }
    resetOnboarding();
    setOnboardingActive(false);
    window.setTimeout(() => setOnboardingActive(true), 0);
  };

  useEffect(() => {
    getUserInfo()
      .then((res) => {
        const data = (res as any)?.data ?? res;
        if (data) {
          setDisplayName(data.display_name ?? data.name ?? '');
          setAvatarUrl(data.avatar_url ?? data.avatar ?? '');
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaveMessage('');
    try {
      await updateUserInfo({ display_name: displayName, avatar_url: avatarUrl });
      setSaveMessage('保存成功');
    } catch {
      setSaveMessage('保存失败');
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMessage(''), 3000);
    }
  };

  /** 快捷键列表 */
  const shortcuts = [
    { key: '⌘ K', desc: '全局搜索' },
    { key: '⌘ N', desc: '新建客户' },
    { key: '⌘ Enter', desc: '发送消息' },
    { key: '⌘ Shift+F', desc: '跳转漏斗' },
    { key: '⌘ ,', desc: '打开设置' },
  ];

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-gray-400" /><span className="ml-2 text-sm text-gray-400">加载中...</span></div>;
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900">个人设置</h2>
      <p className="mt-1 text-sm text-gray-500">管理个人信息与通知偏好</p>

      <div className="mt-6 space-y-6">
        {/* 基本信息 */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-800">基本信息</h3>
          <div className="mt-4 space-y-4">
            {/* 头像 */}
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">头像</label>
              <div className="flex items-center gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 text-xl font-bold text-white">
                  {displayName?.charAt(0) ?? 'U'}
                </div>
                <div className="flex-1">
                  <input
                    type="url"
                    value={avatarUrl}
                    onChange={(e) => setAvatarUrl(e.target.value)}
                    placeholder="输入头像 URL"
                    aria-label="头像 URL"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-black placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <p className="mt-1 text-xs text-gray-400">输入图片链接地址</p>
                </div>
              </div>
            </div>

            {/* 显示名称 */}
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">显示名称</label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="请输入显示名称"
                aria-label="显示名称"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-black placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>
        </div>

        {/* 通知偏好 */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-800">通知偏好</h3>
          <div className="mt-4 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-700">桌面通知</p>
                <p className="text-xs text-gray-400">接收桌面推送通知</p>
              </div>
              <Toggle
                checked={notifications.desktopNotification}
                onChange={(v) => setNotifications({ ...notifications, desktopNotification: v })}
                ariaLabel="桌面通知"
              />
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-700">高意向消息通知</p>
                <p className="text-xs text-gray-400">AI 识别高意向客户时通知</p>
              </div>
              <Toggle
                checked={notifications.highIntentNotification}
                onChange={(v) => setNotifications({ ...notifications, highIntentNotification: v })}
                ariaLabel="高意向消息通知"
              />
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-700">跟进提醒通知</p>
                <p className="text-xs text-gray-400">客户跟进超时时提醒</p>
              </div>
              <Toggle
                checked={notifications.followUpReminder}
                onChange={(v) => setNotifications({ ...notifications, followUpReminder: v })}
                ariaLabel="跟进提醒通知"
              />
            </div>
          </div>
        </div>

        {/* 快捷键说明 */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-800">快捷键</h3>
          <div className="mt-4 space-y-2">
            {shortcuts.map((s) => (
              <div key={s.key} className="flex items-center justify-between py-1.5">
                <span className="text-sm text-gray-600">{s.desc}</span>
                <kbd className="rounded-md bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-600">{s.key}</kbd>
              </div>
            ))}
          </div>
        </div>

        {/* 新手教程 */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-800">新手教程</h3>
          <p className="mt-1 text-xs text-gray-500">
            想再走一遍 5 大核心功能的引导吗？点下方按钮随时重看。
          </p>
          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={handleRestartOnboarding}
              className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-blue-500 to-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:from-blue-600 hover:to-indigo-700"
            >
              <HelpCircle className="h-4 w-4" />
              重新开始新手教程
            </button>
            <span className="text-xs text-gray-400">
              当前状态：<span className="font-medium text-gray-600">{onboardingLabel}</span>
            </span>
          </div>
        </div>

        {import.meta.env.DEV && (
          <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-amber-800">🧪 Mock 测试数据</h3>
            <p className="mt-1 text-xs text-amber-700">
              后端没起 / 想测 UI 时打开。开启后所有 <code className="rounded bg-amber-100 px-1">/api/kellai/*</code> 会用本地 12 个测试客户响应。
              切换后会自动刷新，让请求 adapter 立即生效。
            </p>
            <div className="mt-3 flex items-center gap-3">
              <Toggle
                checked={mockOn}
                onChange={toggleMock}
                ariaLabel="使用 Mock 数据"
              />
              <span className="text-xs text-amber-700">
                {mockReloading
                  ? `正在切换到${mockOn ? ' Mock 模式' : '真实后端'}...`
                  : mockOn
                  ? '当前：Mock 模式已开启'
                  : '当前：Mock 模式关闭'}
              </span>
              <button
                onClick={() => window.location.reload()}
                className="ml-auto rounded-md border border-amber-300 bg-white px-3 py-1 text-xs text-amber-700 hover:bg-amber-100"
              >
                刷新页面生效
              </button>
            </div>
          </div>
        )}

        {/* 保存按钮 */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? '保存中...' : '保存'}
          </button>
          {saveMessage && (
            <span className={clsx('flex items-center gap-1 text-sm', saveMessage.includes('失败') ? 'text-red-500' : 'text-green-600')}>
              {saveMessage.includes('失败') ? <AlertCircle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
              {saveMessage}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ========== 主组件：设置中心 ========== */

type XcmaxScope = { id: string; label: string; description: string };
type XcmaxPending = {
  request_id: string;
  authorization_secret: string;
  requested_scopes: XcmaxScope[];
  expires_at: string;
};
type XcmaxStatus = {
  state: 'connected' | 'pending' | 'not_connected' | 'offline';
  connected?: boolean;
  connection?: {
    authorized_scopes?: string[];
    authorized_by?: { display_name?: string };
    connected_at?: string;
  } | null;
  message?: string;
};

function apiData<T>(response: any): T {
  return (response?.data?.data ?? response?.data ?? response) as T;
}

function XcmaxIntegrationTab() {
  const [status, setStatus] = useState<XcmaxStatus>({ state: 'not_connected' });
  const [pending, setPending] = useState<XcmaxPending | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setError('');
    try {
      const next = apiData<XcmaxStatus>(await getXcmaxIntegrationStatus());
      setStatus(next);
      if (next.state === 'pending') {
        setPending(apiData<XcmaxPending | null>(await getXcmaxBindingPending()));
      } else {
        setPending(null);
      }
    } catch (err: any) {
      setError(err?.response?.data?.error || err?.message || '无法连接 XCMAX 桌面端');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const openXcmax = async () => {
    try {
      await invoke('open_xcmax_desktop');
    } catch {
      window.open('xcmax://im?source=kellai', '_blank', 'noopener,noreferrer');
    }
  };

  const approve = async () => {
    if (!pending) return;
    setWorking(true);
    setError('');
    try {
      await approveXcmaxBinding({
        request_id: pending.request_id,
        authorization_secret: pending.authorization_secret,
        accepted_scopes: pending.requested_scopes.map((scope) => scope.id),
      });
      setPending(null);
      await refresh();
      toastStore.success('已授权 XCMAX AI 读取客来来客户数据');
      void openXcmax();
    } catch (err: any) {
      setError(err?.response?.data?.error || err?.response?.data?.message || err?.message || '授权失败');
    } finally {
      setWorking(false);
    }
  };

  const cancel = async () => {
    if (!pending) return;
    setWorking(true);
    setError('');
    try {
      await cancelXcmaxBinding({
        request_id: pending.request_id,
        authorization_secret: pending.authorization_secret,
      });
      setPending(null);
      await refresh();
    } catch (err: any) {
      setError(err?.response?.data?.error || err?.message || '取消授权失败');
    } finally {
      setWorking(false);
    }
  };

  const disconnect = async () => {
    if (!window.confirm('解除后，XCMAX 将不能读取客来来中的客户档案和会话。')) return;
    setWorking(true);
    setError('');
    try {
      await disconnectXcmaxBinding();
      await refresh();
    } catch (err: any) {
      setError(err?.response?.data?.error || err?.message || '解除绑定失败');
    } finally {
      setWorking(false);
    }
  };

  if (loading) {
    return <div className="flex min-h-[260px] items-center justify-center text-sm text-gray-500"><Loader2 className="mr-2 h-5 w-5 animate-spin" />读取授权状态…</div>;
  }

  const connected = status.state === 'connected' && Boolean(status.connected);
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <div className="text-sm font-medium text-blue-700">客户 IM 数据来源</div>
        <h2 className="mt-1 text-xl font-semibold text-gray-900">连接 XCMAX AI</h2>
        <p className="mt-2 text-sm leading-6 text-gray-600">XCMAX 的 AI 工作台可基于客来来客户会话生成建议；客户沟通仍在客来来内完成。</p>
      </div>

      {connected ? (
        <div className="border border-emerald-200 bg-emerald-50 p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-emerald-800"><CheckCircle2 className="h-5 w-5" />已连接</div>
          <p className="mt-2 text-sm text-emerald-700">当前客来来登录账号已完成授权，XCMAX 会立即识别为已连接。</p>
          <div className="mt-3 text-xs text-emerald-700">已允许：{status.connection?.authorized_scopes?.length || 0} 项只读权限</div>
          <div className="mt-5 flex gap-3">
            <button type="button" onClick={openXcmax} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-800">打开 XCMAX AI</button>
            <button type="button" disabled={working} onClick={disconnect} className="rounded-lg border border-emerald-300 bg-white px-4 py-2 text-sm font-medium text-emerald-800 hover:bg-emerald-100">解除绑定</button>
          </div>
        </div>
      ) : pending ? (
        <div className="border border-blue-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-semibold text-gray-900"><ShieldCheck className="h-5 w-5 text-blue-600" />授权 XCMAX AI</div>
          <p className="mt-2 text-sm leading-6 text-gray-600">将以当前登录的客来来账号完成授权。XCMAX 不会获得发送客户消息的权限。</p>
          <div className="mt-4 divide-y divide-gray-100 border-y border-gray-100">
            {pending.requested_scopes.map((scope) => (
              <div key={scope.id} className="flex items-start gap-3 py-3">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
                <div><div className="text-sm font-medium text-gray-900">{scope.label}</div><div className="mt-1 text-xs leading-5 text-gray-500">{scope.description}</div></div>
              </div>
            ))}
          </div>
          <div className="mt-5 flex gap-3">
            <button type="button" disabled={working} onClick={approve} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">{working ? '授权中…' : '允许并进入 XCMAX AI'}</button>
            <button type="button" disabled={working} onClick={cancel} className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">取消</button>
          </div>
        </div>
      ) : (
        <div className="border border-gray-200 bg-white p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-gray-900"><ShieldCheck className="h-5 w-5 text-gray-500" />等待 XCMAX 发起绑定</div>
          <p className="mt-2 text-sm leading-6 text-gray-600">请在 XCMAX 的“信息”中打开“客户消息 · 客来来”并点击绑定；客来来会自动进入此授权页。</p>
          <button type="button" onClick={openXcmax} className="mt-5 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800">打开 XCMAX AI</button>
        </div>
      )}

      {error && <div className="flex items-center gap-2 border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><AlertCircle className="h-4 w-4 shrink-0" />{error}</div>}
    </div>
  );
}

const TAB_KEYS: TabKey[] = ['channels', 'ai', 'followup', 'team', 'xcmax', 'profile'];

export default function Settings() {
  // 支持通过 URL ?tab=xxx 跳到指定 tab（教程用）
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = searchParams.get('tab') as TabKey | null;
  const [activeTab, setActiveTabState] = useState<TabKey>(
    tabFromUrl && TAB_KEYS.includes(tabFromUrl) ? tabFromUrl : 'channels'
  );
  // URL ?tab 变化时同步到 state（教程从 /settings?tab=channels → /settings?tab=ai 时，
  // React Router 不会重新挂载组件，必须用 effect 监听）
  useEffect(() => {
    if (tabFromUrl && TAB_KEYS.includes(tabFromUrl) && tabFromUrl !== activeTab) {
      setActiveTabState(tabFromUrl);
    }
  }, [tabFromUrl]);
  const setActiveTab = (k: TabKey) => {
    setActiveTabState(k);
    // 同步到 URL，方便分享 / 教程锚定
    setSearchParams({ tab: k }, { replace: true });
  };

  /** 渲染当前 Tab 内容 */
  const renderContent = () => {
    switch (activeTab) {
      case 'channels':
        return <ChannelTab />;
      case 'ai':
        return <AIAssistantTab />;
      case 'followup':
        return <FollowUpTab />;
      case 'team':
        return <TeamTab />;
      case 'xcmax':
        return <XcmaxIntegrationTab />;
      case 'profile':
        return <ProfileTab />;
    }
  };

  return (
    <div className="flex h-full gap-6">
      {/* 左侧 Tab 导航（sticky 在内容区顶部，不随右栏滚动） */}
      <nav className="w-48 shrink-0">
        <div className="sticky top-0 space-y-1">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={clsx(
                  'flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                  activeTab === tab.key
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                )}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            );
          })}
        </div>
      </nav>

      {/* 右侧内容区：用 min-h-0 + overflow-y-auto 允许内部滚动，
          避免 Tab 内容（如渠道管理、跟进规则）超出视口高度把整页撑高 */}
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto pr-1">
        {renderContent()}
      </div>
    </div>
  );
}
