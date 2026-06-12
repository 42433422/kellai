import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
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
import ChannelLogo, { CHANNEL_BRAND_COLOR } from '../components/ChannelLogo';
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
  getLlmStatus,
  getTeamInfo,
  getTeamMembers,
  inviteMember,
  updateMemberRole,
  getUserInfo,
  updateUserInfo,
} from '../api/settings';

/* ========== 常量与映射 ========== */

/** Tab 配置 */
const TABS = [
  { key: 'channels', label: '渠道管理', icon: MessageCircle },
  { key: 'ai', label: 'AI 助手', icon: Bot },
  { key: 'followup', label: '跟进规则', icon: Clock },
  { key: 'team', label: '团队管理', icon: Users },
  { key: 'profile', label: '个人设置', icon: User },
] as const;

type TabKey = (typeof TABS)[number]['key'];

/** 渠道名称映射 */
const channelNameMap: Record<string, string> = {
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
  { key: 'im', title: '即时通讯', types: ['wework', 'douyin', 'miniprogram'] },
  { key: 'ecom', title: '电商平台', types: ['pdd', 'taobao', 'jd', 'alibaba'] },
  { key: 'oversea', title: '海外渠道', types: ['whatsapp', 'telegram', 'line'] },
  { key: 'other', title: '其他方式', types: ['phone', 'email', 'sms', 'web'] },
];

/** 渠道认证方式：scan = 扫码授权（推荐，零配置），form = 凭据表单 */
type ChannelAuthMode = 'scan' | 'form' | 'select' | 'none';

/** 渠道认证方式映射：哪些渠道用扫码，哪些用凭据表单 */
const channelAuthModeMap: Record<string, ChannelAuthMode> = {
  // 即时通讯 → 扫码授权（服务商代配置）
  wework: 'scan',
  douyin: 'scan',
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
  wework: { app: '企业微信', description: '使用企业微信 App 扫描二维码，授权后即可接收客户消息' },
  douyin: { app: '抖音', description: '使用抖音 App 扫描二维码，授权商家工作台' },
  miniprogram: { app: '微信', description: '使用微信扫一扫，授权公众号/小程序接入' },
  pdd: { app: '拼多多商家版', description: '使用拼多多商家 App 扫码，授权客服工作台' },
  taobao: { app: '千牛', description: '使用千牛 App 扫码，授权客服工作台' },
  jd: { app: '京麦', description: '使用京麦 App 扫码，授权客服工作台' },
  alibaba: { app: '千牛 / 阿里卖家', description: '使用 1688 卖家端 App 扫码，授权客服工作台' },
};

/** 渠道配置字段映射（仅 form 模式用） */
const channelConfigFieldsMap: Record<string, { key: string; label: string; type: 'text' | 'password' | 'select'; placeholder?: string; options?: { label: string; value: string }[] }[]> = {
  wework: [
    { key: 'corp_id', label: 'Corp ID（企业 ID）', type: 'text', placeholder: 'ww1234567890' },
    { key: 'secret', label: 'Secret（应用密钥）', type: 'password', placeholder: '请输入应用 Secret' },
    { key: 'agent_id', label: 'Agent ID（应用 ID）', type: 'text', placeholder: '1000002' },
    { key: 'bot_webhook', label: '群机器人 Webhook（可选）', type: 'text', placeholder: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...' },
  ],
  phone: [
    { key: 'line', label: '外呼线路', type: 'select', options: [
      { label: '线路 1 - 电信', value: 'line1' },
      { label: '线路 2 - 移动', value: 'line2' },
      { label: '线路 3 - 联通', value: 'line3' },
    ] },
  ],
  douyin: [
    { key: 'app_id', label: 'App ID', type: 'text', placeholder: '请输入抖音 App ID' },
    { key: 'app_secret', label: 'App Secret', type: 'password', placeholder: '请输入抖音 App Secret' },
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

/** LLM 模型选项 */
const LLM_MODELS = [
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'OpenAI', value: 'openai' },
  { label: '通义千问', value: 'qwen' },
  { label: 'Moonshot', value: 'moonshot' },
  { label: 'SiliconFlow', value: 'siliconflow' },
  { label: 'XCauto（修茈）', value: 'xcauto' },
];

/** 自动回复适用阶段 */
const AUTO_REPLY_STAGES = [
  '已建联', '需求采集', '已提交', '已报价', '谈判中', '成交',
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
  options: string[];
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
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => toggle(opt)}
          className={clsx(
            'rounded-full px-3 py-1 text-xs font-medium transition-colors',
            selected.includes(opt)
              ? 'bg-blue-100 text-blue-700 ring-1 ring-blue-300'
              : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
          )}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

/* ========== Tab 1：渠道管理 ========== */

function ChannelTab() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [configChannel, setConfigChannel] = useState<Channel | null>(null);
  const [configValues, setConfigValues] = useState<Record<string, string>>({});
  const [testingChannel, setTestingChannel] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string }>>({});

  useEffect(() => {
    getChannels()
      .then((res) => {
        const data = (res as any)?.data ?? res;
        setChannels(Array.isArray(data) ? data : []);
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

  /** 测试连接 */
  const handleTest = async (channelType: string) => {
    setTestingChannel(channelType);
    setTestResult((prev) => ({ ...prev, [channelType]: { success: false, message: '测试中...' } }));
    try {
      const res = (await testChannel(channelType)) as any;
      const data = res?.data ?? res;
      const message = data?.message || '连接成功';
      const ok = Boolean(res?.success && (data?.success ?? res?.success));
      setTestResult((prev) => ({ ...prev, [channelType]: { success: ok, message } }));
      if (ok) {
        setChannels((prev) =>
          prev.map((c) => (c.type === channelType ? { ...c, connected: true, enabled: true } : c))
        );
      }
    } catch (err) {
      const data = (err as any)?.response?.data;
      setTestResult((prev) => ({
        ...prev,
        [channelType]: { success: false, message: data?.message || data?.error || '连接失败，请检查配置' },
      }));
    } finally {
      setTestingChannel(null);
    }
  };

  /** 保存渠道配置到后端 */
  const handleSaveConfig = async (channelType: string, values: Record<string, string>) => {
    try {
      await saveChannelConfig(channelType, values, { enabled: true });
      setChannels((prev) =>
        prev.map((c) => (c.type === channelType ? { ...c, config: { ...c.config, ...values } } : c))
      );
      setTestResult((prev) => ({ ...prev, [channelType]: { success: true, message: '已保存配置' } }));
    } catch (err) {
      setTestResult((prev) => ({
        ...prev,
        [channelType]: { success: false, message: `保存失败: ${(err as Error)?.message ?? '未知错误'}` },
      }));
      throw err;
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-gray-400" /><span className="ml-2 text-sm text-gray-400">加载中...</span></div>;
  }

  if (error) {
    return <div className="flex items-center justify-center py-20"><AlertCircle className="h-5 w-5 text-red-400" /><span className="ml-2 text-sm text-red-500">{error}</span></div>;
  }

  /** API 返回空时，用 DEFAULT_PLATFORMS 作兜底展示（让用户能看见所有支持的渠道并点配置） */
  const displayChannels: Channel[] = channels.length > 0
    ? channels
    : DEFAULT_PLATFORMS.map((t, i) => makeDisconnectedChannel(t, i));
  // 按 type → channel 建索引，方便合并 connected + default
  const channelsByType = new Map(displayChannels.map((c) => [c.type, c]));

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
                  <p className="font-medium text-gray-900">{channelNameMap[channel.type] ?? channel.name}</p>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    {channel.connected ? (
                      <>
                        <span className="h-2 w-2 rounded-full bg-green-500" />
                        <span className="text-xs text-green-600">已连接</span>
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

              {/* 操作按钮 */}
              <div className="mt-4 flex items-center gap-2">
                {channelAuthModeMap[channel.type] &&
                 channelAuthModeMap[channel.type] !== 'none' && (
                  <button
                    onClick={() => openConfig(channel)}
                    aria-label={`配置 ${channelNameMap[channel.type] ?? channel.name}`}
                    data-tour="settings-channel-config-btn"
                    className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 transition hover:bg-gray-50"
                  >
                    {channelAuthModeMap[channel.type] === 'scan' ? '扫码授权' : '配置'}
                  </button>
                )}
                <button
                  onClick={() => handleTest(channel.type)}
                  disabled={testingChannel === channel.type}
                  aria-label={`测试 ${channelNameMap[channel.type] ?? channel.name} 连接`}
                  className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
                >
                  {testingChannel === channel.type ? '测试中...' : '测试连接'}
                </button>
              </div>

              {/* 测试结果 */}
              {result && (
                <div className={clsx('mt-3 flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs', result.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700')}>
                  {result.success ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
                  {result.message}
                </div>
              )}
                  </div>
                );
              })}
            </div>
          </section>
        );
      })}

      {/* 配置弹窗 - 根据认证方式路由到不同弹窗 */}
      {configChannel && channelAuthModeMap[configChannel.type] === 'scan' && (
        <ChannelScanModal
          channel={configChannel}
          onClose={() => setConfigChannel(null)}
          onSuccess={() => {
            // 扫码成功：标记渠道为已连接
            setChannels((prev) =>
              prev.map((c) =>
                c.type === configChannel.type ? { ...c, connected: true, enabled: true } : c
              )
            );
            setTestResult((prev) => ({
              ...prev,
              [configChannel.type]: { success: true, message: '扫码授权成功' },
            }));
            setConfigChannel(null);
          }}
        />
      )}
      {configChannel && channelAuthModeMap[configChannel.type] !== 'scan' && (
        <ChannelConfigModal
          channel={configChannel}
          values={configValues}
          onChange={setConfigValues}
          onClose={() => setConfigChannel(null)}
          onSave={handleSaveConfig}
        />
      )}
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

/* ========== 扫码授权弹窗 ========== */

/** 扫码状态机 */
type ScanStatus = 'waiting' | 'scanned' | 'success' | 'expired';

/** 用 channel.type 作 seed 生成一个看起来像 QR 码的 21×21 二值矩阵（仅占位演示用） */
function generateFakeQrMatrix(seed: string): boolean[][] {
  const N = 21;
  // 简易 deterministic hash → 0/1
  const hash = (i: number, j: number): number => {
    const s = `${seed}:${i}:${j}`;
    let h = 2166136261;
    for (let k = 0; k < s.length; k++) {
      h ^= s.charCodeAt(k);
      h = Math.imul(h, 16777619);
    }
    return ((h >>> 0) % 2);
  };
  const grid: boolean[][] = Array.from({ length: N }, () => Array(N).fill(false));

  // 三个角的"定位方框" 7x7（左上、右上、左下）
  const drawFinder = (cx: number, cy: number) => {
    for (let i = -3; i <= 3; i++) {
      for (let j = -3; j <= 3; j++) {
        const x = cx + i;
        const y = cy + j;
        if (x < 0 || y < 0 || x >= N || y >= N) continue;
        const onEdge = Math.max(Math.abs(i), Math.abs(j)) === 3;
        const inner = Math.max(Math.abs(i), Math.abs(j)) <= 1;
        grid[y][x] = onEdge || inner;
      }
    }
  };
  drawFinder(3, 3);
  drawFinder(N - 4, 3);
  drawFinder(3, N - 4);

  // 定位方框之间的"时序图案"和"暗模块"
  for (let i = 8; i < N - 8; i++) {
    grid[6][i] = i % 2 === 0;
    grid[i][6] = i % 2 === 0;
  }
  // 中间的数据区（避开三个定位框 + 时序条 + 中心 logo 区域）
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      // 跳过定位框 7x7 范围
      if ((x < 8 && y < 8) || (x > N - 9 && y < 8) || (x < 8 && y > N - 9)) continue;
      // 跳过第 6 行/列（时序图案）
      if (x === 6 || y === 6) continue;
      // 跳过中心 logo 区域 5x5（用白色覆盖）
      const cx = N / 2 - 0.5;
      if (Math.abs(x - cx) <= 2.5 && Math.abs(y - cx) <= 2.5) continue;
      grid[y][x] = hash(x, y) === 1;
    }
  }
  return grid;
}

/** 把矩阵渲染成 SVG（白底 + 黑块 + 中心 logo 槽位） */
function QrCodeImage({ matrix, accentColor }: { matrix: boolean[][]; accentColor: string }) {
  const N = matrix.length;
  const cell = 10; // 每个模块 10px
  const size = N * cell;
  // 计算一个 cell 的 path：把所有"黑模块"合并成一个大 path
  let rects: JSX.Element[] = [];
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      if (matrix[y][x]) {
        rects.push(
          <rect key={`${x}-${y}`} x={x * cell} y={y * cell} width={cell} height={cell} fill="#0f172a" />
        );
      }
    }
  }
  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      width="208"
      height="208"
      xmlns="http://www.w3.org/2000/svg"
      className="rounded-lg"
      style={{ background: '#fff' }}
    >
      {/* 外圈白底 */}
      <rect x="0" y="0" width={size} height={size} fill="#fff" />
      {rects}
      {/* 中心 logo 占位（彩色小方块代表 App 图标） */}
      <rect
        x={size / 2 - 22}
        y={size / 2 - 22}
        width="44"
        height="44"
        rx="10"
        fill={accentColor}
        stroke="#fff"
        strokeWidth="4"
      />
      <text
        x={size / 2}
        y={size / 2 + 6}
        textAnchor="middle"
        fontSize="22"
        fontWeight="700"
        fill="#fff"
        fontFamily="system-ui, -apple-system, sans-serif"
      >
        K
      </text>
    </svg>
  );
}

/** 渠道扫码授权弹窗 */
function ChannelScanModal({
  channel,
  onClose,
  onSuccess,
}: {
  channel: Channel;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const tip = channelScanTips[channel.type] ?? { app: '对应 App', description: '使用对应 App 扫描二维码' };
  // 不同渠道的强调色（与 channelIconMap / 现实品牌色对齐）
  const accentByType: Record<string, string> = {
    wework: '#2B7CE9',
    douyin: '#161823',
    miniprogram: '#07C160',
    pdd: '#E02E24',
    taobao: '#FF6F00',
    jd: '#E1251B',
    alibaba: '#FF6A00',
  };
  const accent = accentByType[channel.type] ?? '#3b82f6';

  // 状态机 + 二维码刷新 tick
  const [status, setStatus] = useState<ScanStatus>('waiting');
  const [qrSeed, setQrSeed] = useState<string>(`${channel.type}-${Date.now()}`);
  const [countdown, setCountdown] = useState(120); // 120s 过期
  const [, setScanTime] = useState(0);

  // 倒计时
  useEffect(() => {
    if (status !== 'waiting') return;
    if (countdown <= 0) {
      setStatus('expired');
      return;
    }
    const t = window.setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => window.clearTimeout(t);
  }, [countdown, status]);

  // 等待扫码 → 已扫 → 授权成功（模拟真实授权时序）
  useEffect(() => {
    if (status !== 'waiting') return;
    const t1 = window.setTimeout(() => {
      setStatus('scanned');
      setScanTime(Date.now());
    }, 3500);
    return () => window.clearTimeout(t1);
  }, [qrSeed, status]);

  useEffect(() => {
    if (status !== 'scanned') return;
    const t2 = window.setTimeout(() => setStatus('success'), 2000);
    return () => window.clearTimeout(t2);
  }, [status]);

  // 成功后等 1.2s 再回调 onSuccess，让用户看到成功态
  useEffect(() => {
    if (status !== 'success') return;
    const t3 = window.setTimeout(() => onSuccess(), 1200);
    return () => window.clearTimeout(t3);
  }, [status, onSuccess]);

  /** 刷新二维码 */
  const refresh = () => {
    setStatus('waiting');
    setQrSeed(`${channel.type}-${Date.now()}`);
    setCountdown(120);
  };

  const channelLabel = channelNameMap[channel.type] ?? channel.name;

  return (
    <div data-tour="channel-config-modal" className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div
        data-tour="channel-config-modal-body"
        className="relative w-full max-w-sm overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 顶部条：accent 色细条作为视觉锚点 */}
        <div className="h-1.5 w-full" style={{ background: accent }} />

        {/* 关闭按钮 */}
        <button
          onClick={onClose}
          aria-label="关闭配置"
          data-tour="channel-config-cancel"
          className="absolute right-3 top-5 z-10 rounded-md p-1 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600"
        >
          <X className="h-5 w-5" />
        </button>

        <div className="p-7">
          {/* 标题 */}
          <div className="flex items-center gap-3">
            <div
              className="flex h-10 w-10 items-center justify-center rounded-lg"
              style={{ background: `${accent}1a` }}
            >
              <QrCode className="h-5 w-5" style={{ color: accent }} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900">
                {tip.app} 扫码授权
              </h3>
              <p className="mt-0.5 text-xs text-gray-500">连接 {channelLabel}</p>
            </div>
          </div>

          {/* QR 码主体（动画切换） */}
          <div className="mt-6 flex flex-col items-center">
            <div
              data-tour="channel-qrcode"
              className={clsx(
                'relative rounded-2xl border p-3 transition-all duration-500',
                status === 'success' ? 'border-green-200 bg-green-50/40' : 'border-gray-200 bg-white'
              )}
            >
              {/* 状态遮罩（已扫、成功） */}
              {status !== 'waiting' && status !== 'expired' && (
                <div
                  className={clsx(
                    'absolute inset-0 z-10 flex flex-col items-center justify-center rounded-xl bg-white/95 transition-all duration-500',
                    status === 'scanned' ? 'opacity-100' : 'opacity-0 pointer-events-none'
                  )}
                >
                  <div className="flex h-16 w-16 animate-pulse items-center justify-center rounded-full bg-blue-100">
                    <ScanLine className="h-8 w-8 text-blue-600" />
                  </div>
                  <p className="mt-3 text-sm font-semibold text-gray-900">已扫描，请在手机上确认</p>
                  <p className="mt-1 text-xs text-gray-500">等待 {tip.app} 授权…</p>
                </div>
              )}

              {status === 'success' && (
                <div className="absolute inset-0 z-20 flex flex-col items-center justify-center rounded-xl bg-white/95">
                  <div className="flex h-16 w-16 animate-[ping_1.2s_ease-out] items-center justify-center rounded-full bg-green-100">
                    <ShieldCheck className="h-9 w-9 text-green-600" />
                  </div>
                  <p className="mt-3 text-sm font-semibold text-green-700">授权成功</p>
                  <p className="mt-1 text-xs text-gray-500">{channelLabel} 已连接</p>
                </div>
              )}

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

              {/* 实际 QR 码（过期时降低 opacity） */}
              <div
                className={clsx(
                  'transition-opacity duration-300',
                  status === 'expired' ? 'opacity-20' : 'opacity-100'
                )}
              >
                <QrCodeImage matrix={generateFakeQrMatrix(qrSeed)} accentColor={accent} />
              </div>
            </div>

            {/* 倒计时 / 状态行 */}
            <div className="mt-4 flex items-center gap-2 text-xs text-gray-500">
              {status === 'waiting' && (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" style={{ color: accent }} />
                  <span>
                    二维码 <b className="text-gray-700 tabular-nums">{countdown}s</b> 后失效
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

          {/* 说明 */}
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
  const [config, setConfig] = useState<LLMConfig>({
    model: 'xcauto',
    apiKey: '',
    connected: false,
    autoReplyEnabled: false,
    autoReplyStages: [],
    confirmScenarios: [],
  });
  const [showApiKey, setShowApiKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');

  useEffect(() => {
    getLlmStatus()
      .then((res) => {
        const data = (res as any)?.data ?? res;
        if (data && typeof data === 'object') {
          setConfig((prev) => ({
            ...prev,
            model: data.model ?? prev.model,
            connected: data.connected ?? prev.connected,
            autoReplyEnabled: data.autoReplyEnabled ?? prev.autoReplyEnabled,
            autoReplyStages: data.autoReplyStages ?? prev.autoReplyStages,
            confirmScenarios: data.confirmScenarios ?? prev.confirmScenarios,
          }));
        }
      })
      .catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaveMessage('');
    // 模拟保存
    await new Promise((r) => setTimeout(r, 800));
    setSaving(false);
    setSaveMessage('配置已保存');
    setTimeout(() => setSaveMessage(''), 3000);
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
                  onChange={(e) => setConfig({ ...config, model: e.target.value })}
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
            </div>
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

            {/* 适用阶段 */}
            <div>
              <p className="mb-2 text-sm font-medium text-gray-700">适用阶段</p>
              <MultiSelectTags
                options={AUTO_REPLY_STAGES}
                selected={config.autoReplyStages}
                onChange={(v) => setConfig({ ...config, autoReplyStages: v })}
              />
            </div>

            {/* 需确认场景 */}
            <div>
              <p className="mb-2 text-sm font-medium text-gray-700">需确认场景</p>
              <p className="mb-2 text-xs text-gray-400">以下场景 AI 回复前需人工确认</p>
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
            disabled={saving}
            aria-label="保存配置"
            data-tour="ai-save-config"
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? '保存中...' : '保存配置'}
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
  // Mock 数据开关
  const [mockOn, setMockOn] = useState<boolean>(() => {
    try {
      return localStorage.getItem('kellai:useMock') === '1';
    } catch {
      return false;
    }
  });
  const toggleMock = (v: boolean) => {
    setMockOn(v);
    try {
      if (v) localStorage.setItem('kellai:useMock', '1');
      else localStorage.removeItem('kellai:useMock');
    } catch {
      // ignore
    }
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
              onClick={() => {
                resetOnboarding();
                setOnboardingActive(true);
              }}
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

        {/* Mock 数据开关（仅 dev 提示） */}
        <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-amber-800">🧪 Mock 测试数据</h3>
          <p className="mt-1 text-xs text-amber-700">
            后端没起 / 想测 UI 时打开。开启后所有 <code className="rounded bg-amber-100 px-1">/api/kellai/*</code> 会用本地 12 个测试客户响应。
            关闭后刷新即可恢复真实后端。
          </p>
          <div className="mt-3 flex items-center gap-3">
            <Toggle
              checked={mockOn}
              onChange={toggleMock}
              ariaLabel="使用 Mock 数据"
            />
            <span className="text-xs text-amber-700">
              {mockOn ? '当前：Mock 模式已开启' : '当前：Mock 模式关闭'}
            </span>
            <button
              onClick={() => window.location.reload()}
              className="ml-auto rounded-md border border-amber-300 bg-white px-3 py-1 text-xs text-amber-700 hover:bg-amber-100"
            >
              刷新页面生效
            </button>
          </div>
        </div>

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

const TAB_KEYS: TabKey[] = ['channels', 'ai', 'followup', 'team', 'profile'];

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
