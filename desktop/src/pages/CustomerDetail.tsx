import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Send,
  Sparkles,
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
  CalendarClock,
  SlidersHorizontal,
  CheckCircle2,
  ShieldCheck,
  BookOpen,
  BarChart3,
  PhoneCall,
  Bot,
  ClipboardCheck,
} from 'lucide-react';
import { clsx } from 'clsx';
import ChannelLogo from '../components/ChannelLogo';
import FollowUpModal from '../components/customers/FollowUpModal';
import { useCrmEnhanceStore, followUpUrgency } from '../stores/crmEnhance';
import type {
  CustomerPipeline,
  CustomerMessage,
  CustomerAiProfile,
  IntakeForm,
  CrmBundle,
  CustomerRecord,
} from '../types';
import {
  getCustomerPipeline,
  getCustomerCrm,
  getCustomerMessages,
  getCustomerAiProfile,
  getCustomerOperatingInsight,
  getCustomerQualityInspection,
  getCustomerServiceTickets,
  getCustomerServiceLearning,
  getCustomerSelfService,
  getCustomerAgentAssist,
  getCustomerOutboundCalls,
  createCustomerServiceTicket,
  assignCustomerServiceTicket,
  resolveCustomerServiceTicket,
  runCustomerServiceLearning,
  runCustomerSelfService,
  runCustomerAgentAssist,
  planCustomerOutboundCall,
  executeCustomerOutboundCall,
  sendMessage,
  suggestReply,
  updatePipelineStage,
} from '../api/customer';
import { getLTVForecast, generateQuote, startAutoFlow } from '../api/sales';
import type { LTVForecast, Quote, SalesFlow } from '../types';
import { formatTimeAgo, getChannelColor, unwrapApiResponse } from '../utils/format';

/* ========== 常量 ========== */

/** 漏斗阶段选项 */
const STAGE_OPTIONS = [
  { id: 'idle', label: '未接触' },
  { id: 'connected', label: '已建联' },
  { id: 'intake', label: '需求采集' },
  { id: 'intake_done', label: '已提交' },
  { id: 'quoted', label: '已报价' },
  { id: 'negotiating', label: '议价' },
  { id: 'contract_pending', label: '待签' },
  { id: 'signed', label: '已签' },
  { id: 'delivering', label: '交付中' },
  { id: 'delivered', label: '已交付' },
];

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
  { id: 'sales', label: '销售' },
  { id: 'timeline', label: '时间轴' },
  { id: 'intake', label: '需求表单' },
  { id: 'crm', label: 'CRM' },
  { id: 'logs', label: '操作日志' },
] as const;

type TabId = (typeof TABS)[number]['id'];

type OperatingInsight = {
  memory_summary?: string;
  channel_sources?: string[];
  last_inbound_preview?: string;
  risk_signals?: Array<{ key: string; label: string; matched?: string }>;
  management_insights?: Array<{ key: string; label: string; value?: string }>;
  active_task?: string;
  pending_follow_up?: boolean;
  ai_score?: number;
  message_count?: number;
};

type QualityInspection = {
  score?: number;
  grade?: string;
  review_required?: boolean;
  risk_level?: string;
  message_count?: number;
  inbound_count?: number;
  outbound_count?: number;
  response_coverage?: number;
  unanswered_inbound?: boolean;
  failed_rules?: Array<{ key: string; label: string; severity?: string; matched?: string; evidence?: string }>;
  recommendations?: string[];
  manager_report?: { summary?: string; suggested_action?: string; risk_level?: string; coaching_points?: string[] };
};

type ServiceTicket = {
  id: string;
  customer_id?: number;
  title?: string;
  status?: string;
  priority?: string;
  risk_level?: string;
  assignee?: string;
  reason?: string;
  due_at?: string;
  resolved_at?: string;
  resolution?: string;
  ai_rehost_action?: string;
  recommendations?: string[];
  events?: Array<{ action: string; actor?: string; note?: string; at?: string }>;
};

type ServiceTicketSummary = {
  total?: number;
  open?: number;
  resolved?: number;
  latest?: ServiceTicket | null;
  tickets?: ServiceTicket[];
};

type ServiceLearningSummary = {
  persisted?: boolean;
  passed?: boolean;
  metrics?: {
    inspected_conversations?: number;
    inbound_count?: number;
    outbound_count?: number;
    quality_score?: number;
    high_risk_cases?: number;
    ticket_resolved?: number;
    ai_rehosted?: number;
    kb_articles_created?: number;
    top_risk_rules?: string[];
  };
  recommendations?: string[];
  article?: { id?: string; title?: string; tags?: string[]; updated_at?: string } | null;
  article_preview?: { id?: string; title?: string; content?: string; tags?: string[] };
  search_hits?: Array<{ id?: string; title?: string; score?: number }>;
};

type SelfServiceSession = {
  id: string;
  query?: string;
  channel_type?: string;
  status?: string;
  matched?: boolean;
  confidence?: number;
  answer?: string;
  sources?: Array<{ id?: string; title?: string; score?: number }>;
  message_ids?: string[];
  ticket_id?: string;
  next_action?: string;
  created_at?: string;
  updated_at?: string;
};

type SelfServiceSummary = {
  total?: number;
  resolved?: number;
  handoff?: number;
  resolution_rate?: number;
  latest?: SelfServiceSession | null;
  sessions?: SelfServiceSession[];
};

type OutboundCall = {
  id: string;
  customer_id?: number;
  purpose?: string;
  status?: string;
  assignee?: string;
  stage_label?: string;
  pipeline_stage_label?: string;
  outcome?: string;
  outcome_label?: string;
  summary?: string;
  next_action?: string;
  duration_sec?: number;
  created_at?: string;
  executed_at?: string;
  script?: {
    opening?: string;
    context?: string;
    key_points?: string[];
    close_next_action?: string;
  };
  transcript?: Array<{ role?: string; content?: string; at?: string }>;
};

type OutboundCallSummary = {
  total?: number;
  planned?: number;
  completed?: number;
  phone_message_count?: number;
  latest?: OutboundCall | null;
  calls?: OutboundCall[];
};

type AgentAssistSummary = {
  status?: string;
  persisted?: boolean;
  draft?: IntakeForm & {
    autofill_source?: string;
    field_confidence?: Record<string, number>;
    source_message_ids?: string[];
  };
  missing_fields?: string[];
  knowledge_recommendations?: Array<{ id?: string; title?: string; score?: number }>;
  risk_alerts?: Array<{ key?: string; label?: string; severity?: string; evidence?: string }>;
  next_actions?: string[];
  quality_score?: number;
  message_count?: number;
  pipeline_stage?: string;
  applied_at?: string;
  passed?: boolean;
};

/* ========== 工具函数 ========== */

/** 渠道 Logo 渲染 */
function ChannelIconSmall({ type }: { type: string }) {
  return <ChannelLogo type={type} size={16} />;
}

/** AI 评分颜色 */
function getScoreColor(score: number): string {
  if (score < 0.4) return 'text-red-500';
  if (score < 0.7) return 'text-yellow-500';
  return 'text-green-500';
}

function getQualityTone(score: number): string {
  if (score < 60) return 'text-red-600 dark:text-red-400';
  if (score < 80) return 'text-amber-600 dark:text-amber-400';
  return 'text-emerald-600 dark:text-emerald-400';
}

function getQualityBar(score: number): string {
  if (score < 60) return 'bg-red-500';
  if (score < 80) return 'bg-amber-500';
  return 'bg-emerald-500';
}

function getSeverityStyle(severity?: string): string {
  if (severity === 'high') return 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300';
  if (severity === 'medium') return 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300';
  return 'bg-gray-100 text-gray-600 dark:bg-slate-800 dark:text-slate-300';
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
  const [operatingInsight, setOperatingInsight] = useState<OperatingInsight | null>(null);
  const [qualityInspection, setQualityInspection] = useState<QualityInspection | null>(null);
  const [serviceTickets, setServiceTickets] = useState<ServiceTicketSummary | null>(null);
  const [serviceLearning, setServiceLearning] = useState<ServiceLearningSummary | null>(null);
  const [selfService, setSelfService] = useState<SelfServiceSummary | null>(null);
  const [agentAssist, setAgentAssist] = useState<AgentAssistSummary | null>(null);
  const [outboundCalls, setOutboundCalls] = useState<OutboundCallSummary | null>(null);
  const [intakeForm, setIntakeForm] = useState<IntakeForm | null>(null);
  const [crmData, setCrmData] = useState<CrmBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [ticketBusy, setTicketBusy] = useState(false);
  const [learningBusy, setLearningBusy] = useState(false);
  const [selfServiceBusy, setSelfServiceBusy] = useState(false);
  const [assistBusy, setAssistBusy] = useState(false);
  const [callBusy, setCallBusy] = useState(false);

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

  // 销售 Tab 数据
  const [ltvData, setLtvData] = useState<LTVForecast | null>(null);
  const [salesQuote, setSalesQuote] = useState<Quote | null>(null);
  const [salesFlow, setSalesFlow] = useState<SalesFlow | null>(null);

  // Toast
  const [toast, setToast] = useState({ message: '', visible: false });

  // CRM 增强：自定义字段 + 跟进
  const customFields = useCrmEnhanceStore((s) => s.customFields);
  const customValues = useCrmEnhanceStore((s) => s.customValues[customerId]);
  const followUp = useCrmEnhanceStore((s) => s.followUps[customerId]);
  const toggleFollowUpDone = useCrmEnhanceStore((s) => s.toggleFollowUpDone);
  const [followUpOpen, setFollowUpOpen] = useState(false);
  const fallbackMessagePreview = !messages.length ? (operatingInsight?.last_inbound_preview || '') : '';

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
      const [pipelineRes, messagesRes, aiRes, insightRes, qualityRes, ticketRes, learningRes, selfServiceRes, agentAssistRes, outboundRes, intakeRes, crmRes] = await Promise.allSettled([
        getCustomerPipeline(customerId),
        getCustomerMessages(customerId),
        getCustomerAiProfile(customerId),
        getCustomerOperatingInsight(customerId),
        getCustomerQualityInspection(customerId),
        getCustomerServiceTickets(customerId),
        getCustomerServiceLearning(customerId),
        getCustomerSelfService(customerId),
        getCustomerAgentAssist(customerId),
        getCustomerOutboundCalls(customerId),
        getCustomerPipeline(customerId).then((r) => {
          const data = unwrapApiResponse(r);
          return (data as any)?.pipeline?.intake_form ?? (data as any)?.intake_form ?? null;
        }),
        getCustomerCrm(customerId),
      ]);

      if (pipelineRes.status === 'fulfilled') {
        const data = unwrapApiResponse<CustomerPipeline | { pipeline?: CustomerPipeline }>(pipelineRes.value);
        const nextPipeline = data && typeof data === 'object' && 'pipeline' in data
          ? data.pipeline ?? null
          : data;
        setPipeline(nextPipeline && 'customer_id' in nextPipeline ? nextPipeline : null);
      }
      if (messagesRes.status === 'fulfilled') {
        const msgData = unwrapApiResponse(messagesRes.value);
        setMessages(Array.isArray(msgData) ? msgData : []);
      }
      if (aiRes.status === 'fulfilled') {
        setAiProfile(unwrapApiResponse(aiRes.value));
      }
      if (insightRes.status === 'fulfilled') {
        setOperatingInsight(unwrapApiResponse(insightRes.value));
      }
      if (qualityRes.status === 'fulfilled') {
        setQualityInspection(unwrapApiResponse(qualityRes.value));
      }
      if (ticketRes.status === 'fulfilled') {
        setServiceTickets(unwrapApiResponse(ticketRes.value));
      }
      if (learningRes.status === 'fulfilled') {
        setServiceLearning(unwrapApiResponse(learningRes.value));
      }
      if (selfServiceRes.status === 'fulfilled') {
        setSelfService(unwrapApiResponse(selfServiceRes.value));
      }
      if (agentAssistRes.status === 'fulfilled') {
        setAgentAssist(unwrapApiResponse(agentAssistRes.value));
      }
      if (outboundRes.status === 'fulfilled') {
        setOutboundCalls(unwrapApiResponse(outboundRes.value));
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

  const handleCreateTicket = useCallback(async () => {
    if (!customerId || ticketBusy) return;
    setTicketBusy(true);
    try {
      const created = unwrapApiResponse(await createCustomerServiceTicket(customerId, { assignee: '质检主管', sla_minutes: 30 })) as ServiceTicket;
      if (created?.id) {
        await assignCustomerServiceTicket(created.id, '质检主管').catch(() => undefined);
      }
      showToast('主管工单已生成');
      await loadCustomerData();
    } catch (err) {
      console.error('Failed to create service ticket:', err);
      showToast('工单生成失败');
    } finally {
      setTicketBusy(false);
    }
  }, [customerId, ticketBusy, loadCustomerData, showToast]);

  const handleResolveTicket = useCallback(async () => {
    const ticket = serviceTickets?.latest;
    if (!ticket?.id || ticketBusy) return;
    setTicketBusy(true);
    try {
      await resolveCustomerServiceTicket(ticket.id, '已复核风险话术，完成客户安抚，后续由 AI 按合规口径继续跟进。');
      await runCustomerServiceLearning(customerId).catch(() => undefined);
      showToast('工单已解决并沉淀知识');
      await loadCustomerData();
    } catch (err) {
      console.error('Failed to resolve service ticket:', err);
      showToast('工单解决失败');
    } finally {
      setTicketBusy(false);
    }
  }, [customerId, serviceTickets, ticketBusy, loadCustomerData, showToast]);

  const handleRunServiceLearning = useCallback(async () => {
    if (!customerId || learningBusy) return;
    setLearningBusy(true);
    try {
      const result = unwrapApiResponse(await runCustomerServiceLearning(customerId)) as ServiceLearningSummary;
      setServiceLearning(result);
      showToast('服务复盘已沉淀到知识库');
    } catch (err) {
      console.error('Failed to run service learning:', err);
      showToast('服务复盘沉淀失败');
    } finally {
      setLearningBusy(false);
    }
  }, [customerId, learningBusy, showToast]);

  const handleRunSelfService = useCallback(async () => {
    if (!customerId || selfServiceBusy) return;
    setSelfServiceBusy(true);
    try {
      const latestInbound = [...messages].reverse().find((msg) => msg.direction === 'inbound');
      const result = unwrapApiResponse(await runCustomerSelfService(customerId, {
        query: latestInbound?.content || pipeline?.last_message_preview || '',
        channel_type: latestInbound?.channel_type || pipeline?.channel_sources?.[0] || '',
        fallback_to_ticket: true,
      })) as SelfServiceSession;
      showToast(result.status === 'resolved' ? 'AI 自助解答已发送' : '未命中知识库，已转人工工单');
      await loadCustomerData();
    } catch (err) {
      console.error('Failed to run self-service resolution:', err);
      showToast('AI 自助解决失败');
    } finally {
      setSelfServiceBusy(false);
    }
  }, [customerId, selfServiceBusy, messages, pipeline, loadCustomerData, showToast]);

  const handleRunAgentAssist = useCallback(async () => {
    if (!customerId || assistBusy) return;
    setAssistBusy(true);
    try {
      const result = unwrapApiResponse(await runCustomerAgentAssist(customerId, {
        persist: true,
        actor: 'desktop',
      })) as AgentAssistSummary;
      setAgentAssist(result);
      if (result.draft) setIntakeForm(result.draft);
      showToast('坐席助手已自动填单');
      await loadCustomerData();
    } catch (err) {
      console.error('Failed to run agent assist:', err);
      showToast('坐席助手自动填单失败');
    } finally {
      setAssistBusy(false);
    }
  }, [customerId, assistBusy, loadCustomerData, showToast]);

  const handlePlanOutboundCall = useCallback(async () => {
    if (!customerId || callBusy) return;
    setCallBusy(true);
    try {
      await planCustomerOutboundCall(customerId, {
        purpose: 'quote_follow_up',
        assignee: 'AI外呼助手',
      });
      showToast('AI 外呼任务已生成');
      await loadCustomerData();
    } catch (err) {
      console.error('Failed to plan outbound call:', err);
      showToast('外呼任务生成失败');
    } finally {
      setCallBusy(false);
    }
  }, [customerId, callBusy, loadCustomerData, showToast]);

  const handleExecuteOutboundCall = useCallback(async () => {
    if (!customerId || callBusy) return;
    setCallBusy(true);
    try {
      let callId = outboundCalls?.latest?.status === 'planned' ? outboundCalls.latest.id : '';
      if (!callId) {
        const planned = unwrapApiResponse(await planCustomerOutboundCall(customerId, {
          purpose: 'quote_follow_up',
          assignee: 'AI外呼助手',
        })) as OutboundCall;
        callId = planned.id;
      }
      await executeCustomerOutboundCall(callId, {
        outcome: 'demo_booked',
        note: '客户详情页一键模拟外呼',
      });
      showToast('AI 外呼已完成，电话纪要已入库');
      await loadCustomerData();
    } catch (err) {
      console.error('Failed to execute outbound call:', err);
      showToast('模拟外呼失败');
    } finally {
      setCallBusy(false);
    }
  }, [customerId, outboundCalls, callBusy, loadCustomerData, showToast]);

  useEffect(() => {
    if (!customerId || activeTab !== 'sales') return;
    getLTVForecast(customerId).then(setLtvData).catch(() => {});
  }, [customerId, activeTab]);

  const handleStartSalesFlow = async () => {
    try {
      const flow = await startAutoFlow(customerId);
      setSalesFlow(flow);
      showToast('自动销售流程已启动');
    } catch {
      showToast('启动失败');
    }
  };

  const handleGenerateQuote = async () => {
    try {
      const quote = await generateQuote(customerId);
      setSalesQuote(quote);
      showToast('报价已生成');
    } catch {
      showToast('生成失败');
    }
  };

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
  const latestTicket = serviceTickets?.latest ?? null;
  const ticketResolved = latestTicket?.status === 'resolved';
  const canCreateTicket = Boolean(qualityInspection?.review_required && (!latestTicket || ticketResolved));
  const canResolveTicket = Boolean(latestTicket?.id && !ticketResolved);
  const learningMetrics = serviceLearning?.metrics ?? {};
  const learningArticle = serviceLearning?.article ?? null;
  const latestSelfService = selfService?.latest ?? null;
  const selfServiceResolved = latestSelfService?.status === 'resolved';
  const assistDraft = agentAssist?.draft ?? intakeForm ?? null;
  const assistApplied = agentAssist?.status === 'applied' || agentAssist?.persisted;
  const latestCall = outboundCalls?.latest ?? null;
  const callCompleted = latestCall?.status === 'completed';

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
      <div className="flex flex-1 gap-6 overflow-hidden min-h-0">
        {/* 左侧主内容 */}
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto min-h-0">
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

              {/* Agent 运营洞察 */}
              <div className="rounded-xl border border-gray-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-3 flex items-center gap-2">
                  <SlidersHorizontal className="h-4 w-4 text-emerald-500" />
                  <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">Agent 运营洞察</h3>
                </div>
                {operatingInsight ? (
                  <div className="space-y-3 text-sm">
                    {operatingInsight.memory_summary && (
                      <p className="text-gray-600 dark:text-slate-400">{operatingInsight.memory_summary}</p>
                    )}
                    {operatingInsight.active_task && (
                      <div className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
                        <span className="font-medium">主动任务：</span>{operatingInsight.active_task}
                      </div>
                    )}
                    {!!operatingInsight.risk_signals?.length && (
                      <div className="space-y-1">
                        {operatingInsight.risk_signals.slice(0, 3).map((risk) => (
                          <div key={risk.key} className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
                            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                            <span>{risk.label}{risk.matched ? `：${risk.matched}` : ''}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {!!operatingInsight.management_insights?.length && (
                      <div className="flex flex-wrap gap-1.5">
                        {operatingInsight.management_insights.slice(0, 4).map((item) => (
                          <span key={item.key} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-slate-800 dark:text-slate-300">
                            {item.label}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400">暂无运营洞察</p>
                )}
              </div>

              {/* 坐席助手 / 自动填单 */}
              <div className="rounded-xl border border-gray-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <ClipboardCheck className="h-4 w-4 text-blue-500" />
                    <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">坐席助手 / 自动填单</h3>
                  </div>
                  <span className={clsx('rounded-full px-2 py-0.5 text-xs font-medium', assistApplied ? 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300' : 'bg-gray-100 text-gray-600 dark:bg-slate-800 dark:text-slate-300')}>
                    {assistApplied ? '已应用' : '待应用'}
                  </span>
                </div>
                <div className="space-y-3 text-sm">
                  {assistDraft ? (
                    <div className="space-y-2">
                      <div className="rounded-lg bg-blue-50 px-3 py-2 text-blue-800 dark:bg-blue-500/10 dark:text-blue-200">
                        <p className="font-medium">{assistDraft.company_name || pipeline.display_name || '客户需求表单'}</p>
                        <p className="mt-1 text-xs opacity-85">{assistDraft.requirement_desc || '已生成需求草稿，等待补齐字段。'}</p>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                          <p className="text-gray-400">联系人</p>
                          <p className="mt-1 truncate text-gray-700 dark:text-slate-200">{assistDraft.contact_name || '-'}</p>
                        </div>
                        <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                          <p className="text-gray-400">电话</p>
                          <p className="mt-1 truncate text-gray-700 dark:text-slate-200">{assistDraft.contact_phone || '-'}</p>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <p className="text-gray-500 dark:text-slate-400">
                      从最近会话抽取联系人、公司、需求和移动端需求，同时给出知识推荐与风险提醒。
                    </p>
                  )}

                  <div className="grid grid-cols-3 gap-2">
                    <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                      <p className="text-[11px] text-gray-400">推荐知识</p>
                      <p className="mt-1 font-semibold text-gray-800 dark:text-slate-100">{agentAssist?.knowledge_recommendations?.length ?? 0}</p>
                    </div>
                    <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                      <p className="text-[11px] text-gray-400">风险提醒</p>
                      <p className="mt-1 font-semibold text-gray-800 dark:text-slate-100">{agentAssist?.risk_alerts?.length ?? 0}</p>
                    </div>
                    <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                      <p className="text-[11px] text-gray-400">缺失字段</p>
                      <p className="mt-1 font-semibold text-gray-800 dark:text-slate-100">{agentAssist?.missing_fields?.length ?? 0}</p>
                    </div>
                  </div>

                  {!!agentAssist?.next_actions?.length && (
                    <div className="space-y-1">
                      {agentAssist.next_actions.slice(0, 2).map((item) => (
                        <div key={item} className="flex items-start gap-2 text-xs text-gray-600 dark:text-slate-400">
                          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-500" />
                          <span>{item}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={handleRunAgentAssist}
                    disabled={assistBusy}
                    className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-wait disabled:bg-blue-300"
                  >
                    {assistBusy ? '生成中...' : assistApplied ? '重新生成并应用' : '生成并应用表单'}
                  </button>
                </div>
              </div>

              {/* 客服质检 */}
              <div className="rounded-xl border border-gray-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4 text-sky-500" />
                    <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">客服质检</h3>
                  </div>
                  {qualityInspection && (
                    <span className={clsx('rounded-full px-2 py-0.5 text-xs font-medium', qualityInspection.review_required ? 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300' : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300')}>
                      {qualityInspection.review_required ? '需复核' : '通过'}
                    </span>
                  )}
                </div>
                {qualityInspection ? (
                  <div className="space-y-3 text-sm">
                    <div className="flex items-end justify-between">
                      <div>
                        <div className={clsx('text-2xl font-semibold', getQualityTone(Number(qualityInspection.score ?? 0)))}>
                          {qualityInspection.score ?? 0}
                          <span className="ml-1 text-xs text-gray-400">分</span>
                        </div>
                        <p className="text-xs text-gray-400">
                          等级 {qualityInspection.grade || '-'} · {qualityInspection.inbound_count ?? 0} 入站 / {qualityInspection.outbound_count ?? 0} 出站
                        </p>
                      </div>
                      <div className="text-right text-xs text-gray-400">
                        响应覆盖 {Math.round(Number(qualityInspection.response_coverage ?? 0) * 100)}%
                      </div>
                    </div>
                    <div className="h-2 rounded-full bg-gray-100 dark:bg-slate-800">
                      <div
                        className={clsx('h-full rounded-full', getQualityBar(Number(qualityInspection.score ?? 0)))}
                        style={{ width: `${Math.max(4, Math.min(100, Number(qualityInspection.score ?? 0)))}%` }}
                      />
                    </div>
                    {qualityInspection.manager_report?.summary && (
                      <p className="text-gray-600 dark:text-slate-400">{qualityInspection.manager_report.summary}</p>
                    )}
                    {!!qualityInspection.failed_rules?.length && (
                      <div className="space-y-1">
                        {qualityInspection.failed_rules.slice(0, 3).map((rule) => (
                          <div key={rule.key} className={clsx('rounded-lg px-3 py-2 text-xs', getSeverityStyle(rule.severity))}>
                            <span className="font-medium">{rule.label}</span>
                            {rule.matched ? <span>：{rule.matched}</span> : null}
                          </div>
                        ))}
                      </div>
                    )}
                    {!!qualityInspection.recommendations?.length && (
                      <div className="space-y-1">
                        {qualityInspection.recommendations.slice(0, 2).map((item) => (
                          <div key={item} className="flex items-start gap-2 text-xs text-gray-600 dark:text-slate-400">
                            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                            <span>{item}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400">暂无质检报告</p>
                )}
              </div>

              {/* 人机协同工单 */}
              <div className="rounded-xl border border-gray-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-indigo-500" />
                    <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">人机协同工单</h3>
                  </div>
                  {latestTicket && (
                    <span className={clsx('rounded-full px-2 py-0.5 text-xs font-medium', ticketResolved ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300')}>
                      {ticketResolved ? '已回托 AI' : latestTicket.status === 'assigned' ? '已指派' : '待处理'}
                    </span>
                  )}
                </div>
                {latestTicket ? (
                  <div className="space-y-3 text-sm">
                    <div>
                      <p className="font-medium text-gray-800 dark:text-slate-100">{latestTicket.title || '高风险会话转人工'}</p>
                      <p className="mt-1 text-xs text-gray-400">
                        #{latestTicket.id} · {latestTicket.assignee || '未指派'} · SLA {latestTicket.due_at ? formatDateTime(latestTicket.due_at) : '-'}
                      </p>
                    </div>
                    {latestTicket.reason && (
                      <p className="text-gray-600 dark:text-slate-400">{latestTicket.reason}</p>
                    )}
                    {latestTicket.ai_rehost_action && (
                      <div className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
                        {latestTicket.ai_rehost_action}
                      </div>
                    )}
                    {!!latestTicket.recommendations?.length && !latestTicket.ai_rehost_action && (
                      <div className="space-y-1">
                        {latestTicket.recommendations.slice(0, 2).map((item) => (
                          <div key={item} className="flex items-start gap-2 text-xs text-gray-600 dark:text-slate-400">
                            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-500" />
                            <span>{item}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {canResolveTicket && (
                      <button
                        type="button"
                        onClick={handleResolveTicket}
                        disabled={ticketBusy}
                        className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-indigo-500 disabled:cursor-wait disabled:bg-indigo-300"
                      >
                        {ticketBusy ? '处理中...' : '解决并回托 AI'}
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="space-y-3 text-sm">
                    <p className="text-gray-500 dark:text-slate-400">
                      {qualityInspection?.review_required ? '质检要求主管复核，可生成转人工工单。' : '暂无需要人工介入的工单。'}
                    </p>
                    {canCreateTicket && (
                      <button
                        type="button"
                        onClick={handleCreateTicket}
                        disabled={ticketBusy}
                        className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-slate-800 disabled:cursor-wait disabled:bg-slate-400 dark:bg-blue-600 dark:hover:bg-blue-500"
                      >
                        {ticketBusy ? '生成中...' : '生成主管工单'}
                      </button>
                    )}
                  </div>
                )}
              </div>

              {/* 服务自学习 */}
              <div className="rounded-xl border border-gray-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <BookOpen className="h-4 w-4 text-emerald-500" />
                    <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">服务自学习</h3>
                  </div>
                  <span className={clsx('rounded-full px-2 py-0.5 text-xs font-medium', learningArticle ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-gray-100 text-gray-600 dark:bg-slate-800 dark:text-slate-300')}>
                    {learningArticle ? '已沉淀' : '待沉淀'}
                  </span>
                </div>
                <div className="space-y-3 text-sm">
                  {learningArticle ? (
                    <div className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-200">
                      <p className="font-medium">{learningArticle.title || '服务复盘知识'}</p>
                      <p className="mt-1 text-xs opacity-80">#{learningArticle.id} · 可被客服知识库检索</p>
                    </div>
                  ) : (
                    <p className="text-gray-500 dark:text-slate-400">
                      解决工单后可把风险规则、处理结论和回托口径沉淀成知识库 SOP。
                    </p>
                  )}

                  <div className="grid grid-cols-3 gap-2">
                    <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                      <p className="text-[11px] text-gray-400">质检消息</p>
                      <p className="mt-1 font-semibold text-gray-800 dark:text-slate-100">{learningMetrics.inspected_conversations ?? qualityInspection?.message_count ?? 0}</p>
                    </div>
                    <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                      <p className="text-[11px] text-gray-400">已解决</p>
                      <p className="mt-1 font-semibold text-gray-800 dark:text-slate-100">{learningMetrics.ticket_resolved ?? serviceTickets?.resolved ?? 0}</p>
                    </div>
                    <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                      <p className="text-[11px] text-gray-400">回托 AI</p>
                      <p className="mt-1 font-semibold text-gray-800 dark:text-slate-100">{learningMetrics.ai_rehosted ?? (latestTicket?.ai_rehost_action ? 1 : 0)}</p>
                    </div>
                  </div>

                  {!!serviceLearning?.recommendations?.length && (
                    <div className="space-y-1">
                      {serviceLearning.recommendations.slice(0, 2).map((item) => (
                        <div key={item} className="flex items-start gap-2 text-xs text-gray-600 dark:text-slate-400">
                          <BarChart3 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                          <span>{item}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={handleRunServiceLearning}
                    disabled={learningBusy}
                    className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-wait disabled:bg-emerald-300"
                  >
                    {learningBusy ? '沉淀中...' : learningArticle ? '刷新复盘知识' : '沉淀复盘知识'}
                  </button>
                </div>
              </div>

              {/* AI 自助解决 */}
              <div className="rounded-xl border border-gray-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Bot className="h-4 w-4 text-violet-500" />
                    <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">AI 自助解决</h3>
                  </div>
                  <span className={clsx('rounded-full px-2 py-0.5 text-xs font-medium', selfServiceResolved ? 'bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300' : latestSelfService ? 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300' : 'bg-gray-100 text-gray-600 dark:bg-slate-800 dark:text-slate-300')}>
                    {selfServiceResolved ? '已自助解决' : latestSelfService ? '已转人工' : '未运行'}
                  </span>
                </div>
                <div className="space-y-3 text-sm">
                  {latestSelfService ? (
                    <>
                      <div>
                        <p className="font-medium text-gray-800 dark:text-slate-100">
                          {selfServiceResolved ? '知识库命中并自动回复' : '知识库未命中，已生成工单'}
                        </p>
                        <p className="mt-1 text-xs text-gray-400">
                          #{latestSelfService.id} · 置信度 {Math.round(Number(latestSelfService.confidence ?? 0) * 100)}%
                          {latestSelfService.ticket_id ? ` · 工单 ${latestSelfService.ticket_id}` : ''}
                        </p>
                      </div>
                      <div className={clsx('rounded-lg px-3 py-2', selfServiceResolved ? 'bg-violet-50 text-violet-800 dark:bg-violet-500/10 dark:text-violet-200' : 'bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-200')}>
                        {(latestSelfService.answer || latestSelfService.next_action || '').slice(0, 180)}
                      </div>
                      {!!latestSelfService.sources?.length && (
                        <div className="flex flex-wrap gap-1.5">
                          {latestSelfService.sources.slice(0, 3).map((source) => (
                            <span key={source.id || source.title} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-slate-800 dark:text-slate-300">
                              {source.title || source.id}
                            </span>
                          ))}
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="text-gray-500 dark:text-slate-400">
                      用最近客户问题检索知识库，命中后自动回复；未命中时生成转人工工单并补充知识。
                    </p>
                  )}

                  <div className="grid grid-cols-3 gap-2">
                    <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                      <p className="text-[11px] text-gray-400">自助次数</p>
                      <p className="mt-1 font-semibold text-gray-800 dark:text-slate-100">{selfService?.total ?? 0}</p>
                    </div>
                    <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                      <p className="text-[11px] text-gray-400">已解决</p>
                      <p className="mt-1 font-semibold text-gray-800 dark:text-slate-100">{selfService?.resolved ?? 0}</p>
                    </div>
                    <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                      <p className="text-[11px] text-gray-400">转人工</p>
                      <p className="mt-1 font-semibold text-gray-800 dark:text-slate-100">{selfService?.handoff ?? 0}</p>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={handleRunSelfService}
                    disabled={selfServiceBusy}
                    className="rounded-lg bg-violet-600 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-violet-500 disabled:cursor-wait disabled:bg-violet-300"
                  >
                    {selfServiceBusy ? '处理中...' : '运行自助解决'}
                  </button>
                </div>
              </div>

              {/* AI 外呼跟进 */}
              <div className="rounded-xl border border-gray-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <PhoneCall className="h-4 w-4 text-cyan-500" />
                    <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">AI 外呼跟进</h3>
                  </div>
                  <span className={clsx('rounded-full px-2 py-0.5 text-xs font-medium', callCompleted ? 'bg-cyan-50 text-cyan-700 dark:bg-cyan-500/10 dark:text-cyan-300' : latestCall ? 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300' : 'bg-gray-100 text-gray-600 dark:bg-slate-800 dark:text-slate-300')}>
                    {callCompleted ? '已完成' : latestCall ? '待拨打' : '未生成'}
                  </span>
                </div>
                <div className="space-y-3 text-sm">
                  {latestCall ? (
                    <>
                      <div>
                        <p className="font-medium text-gray-800 dark:text-slate-100">
                          {latestCall.outcome_label || latestCall.script?.close_next_action || '电话跟进任务'}
                        </p>
                        <p className="mt-1 text-xs text-gray-400">
                          #{latestCall.id} · {latestCall.assignee || 'AI外呼助手'} · {latestCall.pipeline_stage_label || latestCall.stage_label || pipeline.stage_label}
                        </p>
                      </div>
                      <div className="rounded-lg bg-cyan-50 px-3 py-2 text-cyan-800 dark:bg-cyan-500/10 dark:text-cyan-200">
                        {latestCall.summary || latestCall.script?.opening || '已生成电话脚本，等待执行模拟外呼。'}
                      </div>
                      {latestCall.next_action && (
                        <p className="text-xs text-gray-600 dark:text-slate-400">
                          <span className="font-medium text-gray-700 dark:text-slate-300">下一步：</span>
                          {latestCall.next_action}
                        </p>
                      )}
                      {!!latestCall.transcript?.length && (
                        <div className="space-y-1">
                          {latestCall.transcript.slice(0, 2).map((line, index) => (
                            <div key={`${latestCall.id}-${index}`} className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600 dark:bg-slate-800 dark:text-slate-300">
                              <span className="font-medium">{line.role === 'customer' ? '客户' : 'AI'}：</span>
                              {line.content}
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="text-gray-500 dark:text-slate-400">
                      可基于客户阶段、历史消息、工单和服务复盘生成电话脚本，并把通话纪要写回客户消息。
                    </p>
                  )}

                  <div className="grid grid-cols-3 gap-2">
                    <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                      <p className="text-[11px] text-gray-400">任务数</p>
                      <p className="mt-1 font-semibold text-gray-800 dark:text-slate-100">{outboundCalls?.total ?? 0}</p>
                    </div>
                    <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                      <p className="text-[11px] text-gray-400">已完成</p>
                      <p className="mt-1 font-semibold text-gray-800 dark:text-slate-100">{outboundCalls?.completed ?? 0}</p>
                    </div>
                    <div className="rounded-lg bg-gray-50 px-2 py-2 dark:bg-slate-800">
                      <p className="text-[11px] text-gray-400">电话消息</p>
                      <p className="mt-1 font-semibold text-gray-800 dark:text-slate-100">{outboundCalls?.phone_message_count ?? 0}</p>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={handlePlanOutboundCall}
                      disabled={callBusy}
                      className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-wait disabled:text-gray-400 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                    >
                      {callBusy ? '处理中...' : '生成外呼任务'}
                    </button>
                    <button
                      type="button"
                      onClick={handleExecuteOutboundCall}
                      disabled={callBusy}
                      className="rounded-lg bg-cyan-600 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-cyan-500 disabled:cursor-wait disabled:bg-cyan-300"
                    >
                      {callBusy ? '执行中...' : callCompleted ? '再次模拟外呼' : '执行模拟外呼'}
                    </button>
                  </div>
                </div>
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
                ) : fallbackMessagePreview ? (
                  <div className="text-sm">
                    <div className="flex items-center gap-2">
                      <span className="inline-block h-2 w-2 rounded-full bg-blue-500" />
                      <span className="text-gray-600 dark:text-slate-400">{fallbackMessagePreview}</span>
                    </div>
                    <span className="ml-4 text-xs text-gray-400">来自 Agent 运营洞察</span>
                  </div>
                ) : (
                  <p className="text-sm text-gray-400">暂无消息记录</p>
                )}
              </div>

              {/* 自定义字段 */}
              <div className="rounded-xl border border-gray-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-3 flex items-center gap-2">
                  <SlidersHorizontal className="h-4 w-4 text-blue-500" />
                  <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">自定义字段</h3>
                </div>
                {customFields.length === 0 ? (
                  <p className="text-sm text-gray-400">未配置自定义字段，可在客户列表页「字段」中添加</p>
                ) : (
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                    {customFields.map((f) => (
                      <div key={f.key}>
                        <dt className="text-xs text-gray-400">{f.label}</dt>
                        <dd className="text-gray-700 dark:text-slate-200">{customValues?.[f.key] || '—'}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </div>

              {/* 跟进计划 */}
              <div className="rounded-xl border border-gray-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <CalendarClock className="h-4 w-4 text-blue-500" />
                    <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">跟进计划</h3>
                  </div>
                  <button
                    onClick={() => setFollowUpOpen(true)}
                    className="rounded-lg border border-gray-200 px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                  >
                    {followUp ? '修改' : '设置跟进'}
                  </button>
                </div>
                {followUp ? (
                  <div className="space-y-2 text-sm">
                    <div className="flex items-center gap-2">
                      <span
                        className={clsx(
                          'rounded-full px-2 py-0.5 text-xs font-medium',
                          followUp.done
                            ? 'bg-green-50 text-green-600 dark:bg-green-500/10 dark:text-green-400'
                            : followUpUrgency(followUp) === 'overdue'
                              ? 'bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-400'
                              : followUpUrgency(followUp) === 'today'
                                ? 'bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400'
                                : 'bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400',
                        )}
                      >
                        {followUp.done ? '已完成' : '待跟进'} · {followUp.due_date}
                      </span>
                      <button
                        onClick={() => toggleFollowUpDone(customerId)}
                        className="ml-auto inline-flex items-center gap-1 text-xs text-gray-500 hover:text-green-600 dark:text-slate-400"
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        {followUp.done ? '重新激活' : '标记完成'}
                      </button>
                    </div>
                    {followUp.note && <p className="text-gray-600 dark:text-slate-400">{followUp.note}</p>}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400">暂无跟进计划，点击右上角设置下次跟进时间</p>
                )}
              </div>
            </div>
          )}

          {activeTab === 'sales' && (
            <div className="space-y-4">
              <div className="rounded-xl border border-gray-100 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
                <h3 className="mb-4 text-sm font-semibold text-gray-700 dark:text-slate-200">LTV 预测</h3>
                {ltvData ? (
                  <>
                    <p className="text-2xl font-bold text-green-600">¥{ltvData.predicted_ltv.toLocaleString()}</p>
                    <p className="mt-2 text-sm text-gray-500">{ltvData.recommendation}</p>
                  </>
                ) : (
                  <p className="text-sm text-gray-400">加载中...</p>
                )}
              </div>
              {salesQuote && (
                <div className="rounded-xl border border-gray-100 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
                  <h3 className="mb-2 text-sm font-semibold">最近报价</h3>
                  <p className="text-xl font-bold">¥{salesQuote.total.toLocaleString()}</p>
                </div>
              )}
              {salesFlow && (
                <div className="rounded-xl border border-gray-100 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
                  <h3 className="mb-2 text-sm font-semibold">流程状态</h3>
                  <p className="text-sm">当前步骤：{salesFlow.current_step} · {salesFlow.status}</p>
                </div>
              )}
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={handleStartSalesFlow}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
                >
                  启动自动销售
                </button>
                <button
                  type="button"
                  onClick={handleGenerateQuote}
                  className="rounded-lg border px-4 py-2 text-sm hover:bg-gray-50 dark:border-slate-600 dark:hover:bg-slate-800"
                >
                  生成报价
                </button>
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
              {(() => {
                type LogType = 'stage' | 'inbound' | 'outbound' | 'system';
                const logs: { id: string; type: LogType; title: string; desc?: string; time: string }[] = [];
                (pipeline.timeline || []).forEach((e, i) => {
                  const t = e.timestamp || (e as unknown as { at?: string }).at || '';
                  logs.push({
                    id: `tl-${i}`,
                    type: 'stage',
                    title: `阶段推进至「${e.stage_label || e.stage}」`,
                    desc: e.note,
                    time: t,
                  });
                });
                messages.forEach((mm) => {
                  logs.push({
                    id: `msg-${mm.id}`,
                    type: mm.direction === 'inbound' ? 'inbound' : 'outbound',
                    title: mm.direction === 'inbound' ? '收到客户消息' : '发出消息',
                    desc: mm.content,
                    time: mm.created_at,
                  });
                });
                if (pipeline.created_at) {
                  logs.push({ id: 'created', type: 'system', title: '创建客户档案', time: pipeline.created_at });
                }
                logs.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());
                if (!logs.length) return <p className="text-sm text-gray-400">暂无操作日志</p>;
                const ICONS: Record<LogType, typeof RefreshCw> = {
                  stage: RefreshCw,
                  inbound: MessageSquare,
                  outbound: Send,
                  system: User,
                };
                const TONES: Record<LogType, string> = {
                  stage: 'bg-blue-50 text-blue-500 dark:bg-blue-500/10',
                  inbound: 'bg-green-50 text-green-500 dark:bg-green-500/10',
                  outbound: 'bg-indigo-50 text-indigo-500 dark:bg-indigo-500/10',
                  system: 'bg-gray-100 text-gray-400 dark:bg-slate-700',
                };
                return (
                  <div className="space-y-1">
                    {logs.map((log) => {
                      const Icon = ICONS[log.type];
                      return (
                        <div key={log.id} className="flex gap-3">
                          <div className={clsx('mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full', TONES[log.type])}>
                            <Icon className="h-3.5 w-3.5" />
                          </div>
                          <div className="flex-1 border-b border-gray-50 pb-3 dark:border-slate-800/60">
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-sm font-medium text-gray-700 dark:text-slate-200">{log.title}</p>
                              <span className="shrink-0 text-xs text-gray-400">{formatTimeAgo(log.time)}</span>
                            </div>
                            {log.desc && <p className="mt-0.5 truncate text-xs text-gray-500 dark:text-slate-400">{log.desc}</p>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
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
            ) : fallbackMessagePreview ? (
              <div className="space-y-3">
                <div className="flex justify-start">
                  <div className="max-w-[85%] rounded-lg bg-gray-100 px-3 py-2 text-sm text-gray-800 dark:bg-slate-800 dark:text-slate-200">
                    <p className="break-words">{fallbackMessagePreview}</p>
                    <p className="mt-1 text-xs text-gray-400">来自 Agent 运营洞察</p>
                  </div>
                </div>
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
                  <ChannelIconSmall type={selectedChannel} />
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
                      <ChannelIconSmall type={channel.value} />
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

      {/* 跟进设置 */}
      {followUpOpen && (
        <FollowUpModal
          customer={{ customer_id: customerId, display_name: pipeline.display_name } as CustomerRecord}
          onClose={() => setFollowUpOpen(false)}
        />
      )}
    </div>
  );
}
