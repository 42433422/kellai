import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Send,
  Sparkles,
  Phone,
  Briefcase,
  Mail,
  Smartphone,
  Globe,
  Music,
  MessageSquare,
  ChevronDown,
  Clock,
  Tag,
  User,
  FileText,
  Building2,
  Receipt,
  Truck,
  RefreshCw,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import { clsx } from 'clsx';
import type {
  CustomerPipeline,
  CustomerMessage,
  CustomerAiProfile,
  IntakeForm,
  CrmBundle,
} from '../types';
import {
  getCustomerPipeline,
  getCustomerCrm,
  getCustomerMessages,
  getCustomerAiProfile,
  sendMessage,
  suggestReply,
  updatePipelineStage,
} from '../api/customer';
import { formatTimeAgo, getChannelColor, unwrapApiResponse } from '../utils/format';

/* ========== 常量 ========== */

/** 漏斗阶段选项 */
const STAGE_OPTIONS = [
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

/** 渠道图标映射 */
const CHANNEL_ICON_MAP: Record<string, React.ElementType> = {
  wework: Briefcase,
  phone: Phone,
  douyin: Music,
  email: Mail,
  sms: Smartphone,
  web: Globe,
  whatsapp: MessageSquare,
};

/** 渠道中文名映射 */
const CHANNEL_LABEL_MAP: Record<string, string> = {
  wework: '企微',
  phone: '电话',
  douyin: '抖音',
  email: '邮件',
  sms: '短信',
  web: '网页',
  whatsapp: 'WhatsApp',
};

/** 消息发送渠道选项 */
const SEND_CHANNELS = [
  { value: 'wework', label: '企微' },
  { value: 'sms', label: '短信' },
  { value: 'email', label: '邮件' },
];

/** 紧迫度颜色 */
const URGENCY_STYLE: Record<string, string> = {
  high: 'bg-red-50 text-red-700 border border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20',
  medium: 'bg-yellow-50 text-yellow-700 border border-yellow-200 dark:bg-yellow-500/10 dark:text-yellow-400 dark:border-yellow-500/20',
  low: 'bg-green-50 text-green-700 border border-green-200 dark:bg-green-500/10 dark:text-green-400 dark:border-green-500/20',
};

const URGENCY_LABEL: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
};

/** Tab 定义 */
const TABS = [
  { id: 'overview', label: '概览' },
  { id: 'timeline', label: '时间轴' },
  { id: 'intake', label: '需求表单' },
  { id: 'crm', label: 'CRM' },
  { id: 'logs', label: '操作日志' },
] as const;

type TabId = (typeof TABS)[number]['id'];

/* ========== 工具函数 ========== */

/** 获取渠道图标组件 */
function getChannelIcon(type: string): React.ElementType {
  return CHANNEL_ICON_MAP[type] ?? MessageSquare;
}

/** AI 评分颜色 */
function getScoreColor(score: number): string {
  if (score < 0.4) return 'text-red-500';
  if (score < 0.7) return 'text-yellow-500';
  return 'text-green-500';
}

/** 格式化日期时间 */
function formatDateTime(dateStr: string): string {
  if (!dateStr) return '-';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '-';
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/* ========== Toast 组件 ========== */

/** 轻量 Toast 提示 */
function Toast({ message, visible }: { message: string; visible: boolean }) {
  return (
    <div
      className={clsx(
        'fixed bottom-6 left-1/2 z-50 -translate-x-1/2 transform rounded-full bg-gray-800 px-4 py-2 text-sm text-white shadow-lg transition-opacity duration-200 dark:bg-slate-700',
        visible ? 'opacity-100' : 'pointer-events-none opacity-0',
      )}
      role="status"
      aria-live="polite"
    >
      {message}
    </div>
  );
}

/* ========== 主组件 ========== */

export default function CustomerDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const customerId = Number(id);

  // Tab 状态
  const [activeTab, setActiveTab] = useState<TabId>('overview');

  // 数据状态
  const [pipeline, setPipeline] = useState<CustomerPipeline | null>(null);
  const [messages, setMessages] = useState<CustomerMessage[]>([]);
  const [aiProfile, setAiProfile] = useState<CustomerAiProfile | null>(null);
  const [intakeForm, setIntakeForm] = useState<IntakeForm | null>(null);
  const [crmData, setCrmData] = useState<CrmBundle | null>(null);
  const [loading, setLoading] = useState(true);

  // 消息发送
  const [messageInput, setMessageInput] = useState('');
  const [selectedChannel, setSelectedChannel] = useState('wework');
  const [showChannelSelect, setShowChannelSelect] = useState(false);
  const [sendingMessage, setSendingMessage] = useState(false);

  // AI 建议回复
  const [suggestedReplies, setSuggestedReplies] = useState<string[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);

  // 阶段更新
  const [updatingStage, setUpdatingStage] = useState(false);
  const [showStageSelect, setShowStageSelect] = useState(false);

  // Toast
  const [toast, setToast] = useState({ message: '', visible: false });

  /** 显示 Toast */
  const showToast = useCallback((message: string) => {
    setToast({ message, visible: true });
    setTimeout(() => setToast({ message: '', visible: false }), 2000);
  }, []);

  /** 加载客户数据 */
  const loadCustomerData = useCallback(async () => {
    if (!customerId) return;
    setLoading(true);
    try {
      const [pipelineRes, messagesRes, aiRes, intakeRes, crmRes] = await Promise.allSettled([
        getCustomerPipeline(customerId),
        getCustomerMessages(customerId),
        getCustomerAiProfile(customerId),
        getCustomerPipeline(customerId).then((r) => {
          const data = unwrapApiResponse(r);
          return (data as any)?.intake_form ?? null;
        }),
        getCustomerCrm(customerId),
      ]);

      if (pipelineRes.status === 'fulfilled') {
        setPipeline(unwrapApiResponse(pipelineRes.value));
      }
      if (messagesRes.status === 'fulfilled') {
        const msgData = unwrapApiResponse(messagesRes.value);
        setMessages(Array.isArray(msgData) ? msgData : []);
      }
      if (aiRes.status === 'fulfilled') {
        setAiProfile(unwrapApiResponse(aiRes.value));
      }
      if (intakeRes.status === 'fulfilled') {
        setIntakeForm(intakeRes.value);
      }
      if (crmRes.status === 'fulfilled') {
        setCrmData(unwrapApiResponse(crmRes.value));
      }
    } catch (err) {
      console.error('Failed to load customer data:', err);
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  useEffect(() => {
    loadCustomerData();
  }, [loadCustomerData]);

  /** 获取 AI 建议回复 */
  const handleGetSuggestions = useCallback(async () => {
    if (!messages.length || loadingSuggestions) return;
    setLoadingSuggestions(true);
    try {
      const lastMessage = messages[messages.length - 1];
      const res = await suggestReply(
        customerId,
        lastMessage?.content ?? '',
        aiProfile?.ai_tags?.join(',') ?? '',
        pipeline?.stage ?? '',
      );
      const data = unwrapApiResponse(res) as any;
      setSuggestedReplies(data?.replies ?? data?.suggestions ?? []);
    } catch (err) {
      console.error('Failed to get suggestions:', err);
    } finally {
      setLoadingSuggestions(false);
    }
  }, [messages, customerId, aiProfile, pipeline, loadingSuggestions]);

  /** 发送消息 */
  const handleSendMessage = useCallback(async () => {
    if (!messageInput.trim() || sendingMessage) return;
    setSendingMessage(true);
    try {
      await sendMessage(customerId, selectedChannel, '', messageInput.trim());
      setMessageInput('');
      setSuggestedReplies([]);
      showToast('消息已发送');
      loadCustomerData();
    } catch (err) {
      console.error('Failed to send message:', err);
      showToast('发送失败，请重试');
    } finally {
      setSendingMessage(false);
    }
  }, [messageInput, customerId, selectedChannel, sendingMessage, loadCustomerData, showToast]);

  /** 更新 Pipeline 阶段 */
  const handleUpdateStage = useCallback(
    async (stage: string) => {
      setUpdatingStage(true);
      try {
        await updatePipelineStage(customerId, stage);
        setPipeline((prev) =>
          prev ? { ...prev, stage, stage_label: STAGE_OPTIONS.find((s) => s.id === stage)?.label ?? stage } : prev,
        );
        showToast('阶段已更新');
      } catch (err) {
        console.error('Failed to update stage:', err);
        showToast('更新失败，请重试');
      } finally {
        setUpdatingStage(false);
        setShowStageSelect(false);
      }
    },
    [customerId, showToast],
  );

  /** 当前阶段标签 */
  const currentStage = STAGE_OPTIONS.find((s) => s.id === pipeline?.stage);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <Loader2 className="mx-auto h-8 w-8 animate-spin text-gray-400" />
          <p className="mt-2 text-sm text-gray-400">加载中...</p>
        </div>
      </div>
    );
  }

  if (!pipeline) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <AlertCircle className="mx-auto h-12 w-12 text-gray-300" />
          <p className="mt-2 text-sm text-gray-400">未找到客户信息</p>
          <button
            onClick={() => navigate(-1)}
            className="mt-4 text-sm text-blue-500 hover:underline"
          >
            返回上一页
          </button>
        </div>
      </div>
    );
  }

  return (
    <div data-tour="customer-detail" className="flex h-full flex-col">
      {/* 顶部导航 */}
      <div className="border-b border-gray-100 bg-white px-6 py-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate(-1)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-slate-800"
            aria-label="返回上一页"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-semibold text-gray-800 dark:text-slate-100">
                {pipeline.display_name}
              </h1>
              <span
                className={clsx(
                  'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
                  currentStage ? getChannelColor(currentStage.id) : 'bg-gray-100 text-gray-600',
                )}
              >
                {currentStage?.label ?? pipeline.stage}
              </span>
              {pipeline.ai_score !== undefined && (
                <span className={clsx('text-xs font-medium', getScoreColor(pipeline.ai_score))}>
                  AI 评分 {Math.round(pipeline.ai_score * 100)}
                </span>
              )}
            </div>
            <div className="mt-1 flex items-center gap-4 text-xs text-gray-400">
              <span className="flex items-center gap-1">
                <User className="h-3 w-3" />
                {pipeline.username}
              </span>
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                更新于 {formatTimeAgo(pipeline.updated_at)}
              </span>
            </div>
          </div>

          {/* 阶段更新按钮 */}
          <div className="relative">
            <button
              onClick={() => setShowStageSelect(!showStageSelect)}
              className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              aria-label="更新阶段"
            >
              <RefreshCw className={clsx('h-3.5 w-3.5', updatingStage && 'animate-spin')} />
              更新阶段
              <ChevronDown className="h-3 w-3" />
            </button>
            {showStageSelect && (
              <div className="absolute right-0 top-full z-50 mt-1 w-40 rounded-lg border border-gray-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-800">
                {STAGE_OPTIONS.map((stage) => (
                  <button
                    key={stage.id}
                    onClick={() => handleUpdateStage(stage.id)}
                    className={clsx(
                      'w-full rounded px-2 py-1.5 text-left text-xs',
                      pipeline.stage === stage.id
                        ? 'bg-blue-50 text-blue-600 dark:bg-blue-500/20 dark:text-blue-300'
                        : 'text-gray-600 hover:bg-gray-50 dark:text-slate-300 dark:hover:bg-slate-700',
                    )}
                  >
                    {stage.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Tab 导航 */}
        <div className="mt-4 flex gap-1 border-b border-gray-100 dark:border-slate-800">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={clsx(
                'border-b-2 px-4 py-2 text-sm font-medium transition-colors',
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-600 dark:border-blue-400 dark:text-blue-300'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-slate-400 dark:hover:text-slate-200',
              )}
              aria-label={tab.label}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* 内容区域 */}
      <div className="flex flex-1 gap-6 overflow-hidden p-6">
        {/* 左侧主内容 */}
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto">
          {activeTab === 'overview' && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {/* AI 画像 */}
              <div data-tour="customer-ai-profile" className="rounded-xl border border-gray-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-3 flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-blue-500" />
                  <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">AI 画像</h3>
                </div>
                {aiProfile ? (
                  <div className="space-y-2 text-sm">
                    {aiProfile.needs_preference && (
                      <p className="text-gray-600 dark:text-slate-400">
                        <span className="font-medium text-gray-700 dark:text-slate-300">需求偏好：</span>
                        {aiProfile.needs_preference}
                      </p>
                    )}
                    {aiProfile.decision_role && (
                      <p className="text-gray-600 dark:text-slate-400">
                        <span className="font-medium text-gray-700 dark:text-slate-300">决策角色：</span>
                        {aiProfile.decision_role}
                      </p>
                    )}
                    {aiProfile.urgency && (
                      <p className="text-gray-600 dark:text-slate-400">
                        <span className="font-medium text-gray-700 dark:text-slate-300">紧迫度：</span>
                        <span className={clsx('rounded-full px-2 py-0.5 text-xs', URGENCY_STYLE[aiProfile.urgency])}>
                          {URGENCY_LABEL[aiProfile.urgency]}
                        </span>
                      </p>
                    )}
                    {aiProfile.ai_tags && aiProfile.ai_tags.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {aiProfile.ai_tags.map((tag) => (
                          <span
                            key={tag}
                            className="flex items-center gap-0.5 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-slate-800 dark:text-slate-400"
                          >
                            <Tag className="h-3 w-3" />
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400">暂无 AI 画像数据</p>
                )}
              </div>

              {/* 消息预览 */}
              <div className="rounded-xl border border-gray-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-3 flex items-center gap-2">
                  <MessageSquare className="h-4 w-4 text-blue-500" />
                  <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">最近消息</h3>
                </div>
                {messages.length > 0 ? (
                  <div className="space-y-2">
                    {messages.slice(-3).map((msg) => (
                      <div key={msg.id} className="text-sm">
                        <div className="flex items-center gap-2">
                          <span
                            className={clsx(
                              'inline-block h-2 w-2 rounded-full',
                              msg.direction === 'inbound' ? 'bg-blue-500' : 'bg-green-500',
                            )}
                          />
                          <span className="text-gray-600 dark:text-slate-400">{msg.content}</span>
                        </div>
                        <span className="ml-4 text-xs text-gray-400">{formatTimeAgo(msg.created_at)}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400">暂无消息记录</p>
                )}
              </div>
            </div>
          )}

          {activeTab === 'timeline' && (
            <div className="rounded-xl border border-gray-100 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
              <h3 className="mb-4 text-sm font-semibold text-gray-700 dark:text-slate-200">Pipeline 时间轴</h3>
              {pipeline.timeline && pipeline.timeline.length > 0 ? (
                <div className="space-y-4">
                  {pipeline.timeline.map((entry, index) => (
                    <div key={index} className="flex gap-4">
                      <div className="flex flex-col items-center">
                        <div className="h-2 w-2 rounded-full bg-blue-500" />
                        {index < pipeline.timeline!.length - 1 && (
                          <div className="w-px flex-1 bg-gray-200 dark:bg-slate-700" />
                        )}
                      </div>
                      <div className="flex-1 pb-4">
                        <p className="text-sm font-medium text-gray-700 dark:text-slate-200">{entry.stage_label}</p>
                        <p className="text-xs text-gray-400">{formatDateTime(entry.timestamp)}</p>
                        {entry.note && <p className="mt-1 text-xs text-gray-500">{entry.note}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-400">暂无时间轴记录</p>
              )}
            </div>
          )}

          {activeTab === 'intake' && (
            <div className="rounded-xl border border-gray-100 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
              <h3 className="mb-4 text-sm font-semibold text-gray-700 dark:text-slate-200">需求表单</h3>
              {intakeForm ? (
                <div className="grid gap-4 text-sm md:grid-cols-2">
                  {intakeForm.contact_name && (
                    <div>
                      <span className="text-gray-400">联系人</span>
                      <p className="text-gray-700 dark:text-slate-200">{intakeForm.contact_name}</p>
                    </div>
                  )}
                  {intakeForm.company_name && (
                    <div>
                      <span className="text-gray-400">公司</span>
                      <p className="text-gray-700 dark:text-slate-200">{intakeForm.company_name}</p>
                    </div>
                  )}
                  {intakeForm.requirement_desc && (
                    <div className="md:col-span-2">
                      <span className="text-gray-400">需求描述</span>
                      <p className="text-gray-700 dark:text-slate-200">{intakeForm.requirement_desc}</p>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-sm text-gray-400">暂无需求表单数据</p>
              )}
            </div>
          )}

          {activeTab === 'crm' && (
            <div className="rounded-xl border border-gray-100 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
              <h3 className="mb-4 text-sm font-semibold text-gray-700 dark:text-slate-200">CRM 信息</h3>
              {crmData ? (
                <div className="space-y-4">
                  {crmData.opportunity && (
                    <div className="flex items-center gap-3">
                      <Building2 className="h-5 w-5 text-gray-400" />
                      <div>
                        <p className="text-sm font-medium text-gray-700 dark:text-slate-200">商机</p>
                        <p className="text-xs text-gray-400">{crmData.opportunity.company}</p>
                      </div>
                    </div>
                  )}
                  {crmData.quote && (
                    <div className="flex items-center gap-3">
                      <Receipt className="h-5 w-5 text-gray-400" />
                      <div>
                        <p className="text-sm font-medium text-gray-700 dark:text-slate-200">报价</p>
                        <p className="text-xs text-gray-400">{crmData.quote.summary}</p>
                      </div>
                    </div>
                  )}
                  {crmData.invoice && (
                    <div className="flex items-center gap-3">
                      <FileText className="h-5 w-5 text-gray-400" />
                      <div>
                        <p className="text-sm font-medium text-gray-700 dark:text-slate-200">发票</p>
                        <p className="text-xs text-gray-400">{crmData.invoice.invoice_no}</p>
                      </div>
                    </div>
                  )}
                  {crmData.delivery && (
                    <div className="flex items-center gap-3">
                      <Truck className="h-5 w-5 text-gray-400" />
                      <div>
                        <p className="text-sm font-medium text-gray-700 dark:text-slate-200">交付</p>
                        <p className="text-xs text-gray-400">{crmData.delivery.details}</p>
                      </div>
                    </div>
                  )}
                  {crmData.synced_at && (
                    <p className="text-xs text-gray-400">同步时间：{formatDateTime(crmData.synced_at)}</p>
                  )}
                </div>
              ) : (
                <p className="text-sm text-gray-400">暂无 CRM 数据</p>
              )}
            </div>
          )}

          {activeTab === 'logs' && (
            <div className="rounded-xl border border-gray-100 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
              <h3 className="mb-4 text-sm font-semibold text-gray-700 dark:text-slate-200">操作日志</h3>
              <p className="text-sm text-gray-400">操作日志功能开发中...</p>
            </div>
          )}
        </div>

        {/* 右侧消息发送区域（窄屏隐藏，避免挤压主内容） */}
        <div className="hidden w-80 shrink-0 flex-col rounded-xl border border-gray-100 bg-white dark:border-slate-800 dark:bg-slate-900 lg:flex">
          {/* 消息列表 */}
          <div className="flex-1 overflow-y-auto p-4">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">对话</h3>
              <button
                onClick={handleGetSuggestions}
                className="inline-flex items-center gap-1 rounded-lg bg-blue-50 px-2 py-1 text-xs text-blue-600 hover:bg-blue-100 dark:bg-blue-500/10 dark:text-blue-400"
                aria-label="获取 AI 建议回复"
              >
                <Sparkles className="h-3 w-3" />
                AI 建议
              </button>
            </div>

            {messages.length > 0 ? (
              <div className="space-y-3">
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={clsx('flex', msg.direction === 'outbound' ? 'justify-end' : 'justify-start')}
                  >
                    <div
                      className={clsx(
                        'max-w-[85%] rounded-lg px-3 py-2 text-sm',
                        msg.direction === 'outbound'
                          ? 'bg-blue-500 text-white'
                          : 'bg-gray-100 text-gray-800 dark:bg-slate-800 dark:text-slate-200',
                      )}
                    >
                      <p className="break-words">{msg.content}</p>
                      <p
                        className={clsx(
                          'mt-1 text-xs',
                          msg.direction === 'outbound' ? 'text-blue-100' : 'text-gray-400',
                        )}
                      >
                        {formatTimeAgo(msg.created_at)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-center text-sm text-gray-400">暂无对话记录</p>
            )}

            {/* AI 建议回复 */}
            {loadingSuggestions && (
              <div className="mt-4 flex items-center justify-center gap-2 text-sm text-gray-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                生成建议中...
              </div>
            )}
            {suggestedReplies.length > 0 && (
              <div className="mt-4 space-y-2">
                <p className="text-xs font-medium text-gray-500">建议回复：</p>
                {suggestedReplies.map((reply, index) => (
                  <button
                    key={index}
                    onClick={() => setMessageInput(reply)}
                    className="w-full rounded-lg border border-gray-200 bg-white p-2 text-left text-xs text-gray-600 hover:bg-gray-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                  >
                    {reply}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 发送区域 */}
          <div className="border-t border-gray-100 p-4 dark:border-slate-800">
            {/* 渠道选择 */}
            <div className="relative mb-3">
              <button
                onClick={() => setShowChannelSelect(!showChannelSelect)}
                className="flex w-full items-center justify-between rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 dark:border-slate-700 dark:text-slate-300"
                aria-label="选择发送渠道"
              >
                <span className="flex items-center gap-2">
                  {(() => {
                    const Icon = getChannelIcon(selectedChannel);
                    return <Icon className="h-4 w-4" />;
                  })()}
                  {CHANNEL_LABEL_MAP[selectedChannel] ?? selectedChannel}
                </span>
                <ChevronDown className="h-4 w-4" />
              </button>
              {showChannelSelect && (
                <div className="absolute bottom-full mb-1 left-0 z-50 w-full rounded-lg border border-gray-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-800">
                  {SEND_CHANNELS.map((channel) => (
                    <button
                      key={channel.value}
                      onClick={() => {
                        setSelectedChannel(channel.value);
                        setShowChannelSelect(false);
                      }}
                      className={clsx(
                        'flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm',
                        selectedChannel === channel.value
                          ? 'bg-blue-50 text-blue-600 dark:bg-blue-500/20 dark:text-blue-300'
                          : 'text-gray-600 hover:bg-gray-50 dark:text-slate-300 dark:hover:bg-slate-700',
                      )}
                    >
                      {(() => {
                        const Icon = getChannelIcon(channel.value);
                        return <Icon className="h-4 w-4" />;
                      })()}
                      {channel.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* 消息输入 */}
            <div className="flex gap-2">
              <input
                type="text"
                value={messageInput}
                onChange={(e) => setMessageInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                placeholder="输入消息..."
                className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:border-blue-500 focus:outline-none dark:border-slate-700 dark:text-slate-200 dark:placeholder-slate-500"
                aria-label="消息输入框"
              />
              <button
                onClick={handleSendMessage}
                disabled={!messageInput.trim() || sendingMessage}
                className="inline-flex items-center justify-center rounded-lg bg-blue-500 px-3 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50"
                aria-label="发送消息"
              >
                {sendingMessage ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Toast */}
      <Toast message={toast.message} visible={toast.visible} />
    </div>
  );
}
