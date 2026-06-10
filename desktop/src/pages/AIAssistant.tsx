import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bot,
  Clock,
  Send,
  Sparkles,
  RefreshCw,
  Search,
  ChevronRight,
  AlertTriangle,
  UserCircle,
  Target,
  DollarSign,
  Zap,
  Tag,
  BarChart3,
  MessageSquare,
  Wand2,
  Lightbulb,
  CheckCircle2,
} from 'lucide-react';
import {
  analyzeIntent,
  suggestReply,
  generateAutoReply,
  getCustomerProfile,
  getReminders,
  updateAiScore,
} from '../api/ai';
import { queryPipelines } from '../api/funnel';
import type { CustomerProfile, Reminder, ChatMessage, ClientSummary } from '../types';
import { formatTimeAgo, formatStage } from '../utils/format';

/* ========== 常量 & 工具 ========== */

/** 超时时间筛选选项 */
const hourOptions = [
  { label: '24h', value: 24 },
  { label: '48h', value: 48 },
  { label: '72h', value: 72 },
  { label: '7天', value: 168 },
];

/** 阶段标签颜色 */
const stageColorMap: Record<string, string> = {
  lead: 'bg-gray-100 text-gray-700',
  new: 'bg-blue-50 text-blue-700',
  qualified: 'bg-indigo-50 text-indigo-700',
  contacted: 'bg-cyan-50 text-cyan-700',
  interested: 'bg-amber-50 text-amber-700',
  intention: 'bg-orange-50 text-orange-700',
  proposal: 'bg-purple-50 text-purple-700',
  negotiation: 'bg-rose-50 text-rose-700',
  closed_won: 'bg-green-50 text-green-700',
  deal: 'bg-green-50 text-green-700',
  closed_lost: 'bg-red-50 text-red-700',
};

function getStageColor(stage: string): string {
  return stageColorMap[stage] ?? 'bg-gray-100 text-gray-700';
}

/** 紧迫度颜色 */
const urgencyColorMap: Record<string, { bg: string; text: string; label: string }> = {
  high: { bg: 'bg-red-50', text: 'text-red-600', label: '紧急' },
  medium: { bg: 'bg-amber-50', text: 'text-amber-600', label: '一般' },
  low: { bg: 'bg-green-50', text: 'text-green-600', label: '宽松' },
};

/** 生成唯一 ID */
function uid(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

/** 判断是否超时（超过筛选时间） */
function isOverdue(lastFollowUpAt: string, hours: number): boolean {
  const diff = Date.now() - new Date(lastFollowUpAt).getTime();
  return diff > hours * 3600 * 1000;
}

/* ========== 左栏：跟进提醒 ========== */

function ReminderPanel() {
  const navigate = useNavigate();
  const [hours, setHours] = useState(48);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  /** 加载提醒数据
   *  字段映射：后端 FollowUpReminder → 前端 Reminder
   *    display_name           -> customerName
   *    hours_since_last_contact (数字) -> lastFollowUpAt (ISO 时间)
   *    保留 stage / suggested_action
   */
  const loadReminders = useCallback(() => {
    setLoading(true);
    setError('');
    getReminders(hours)
      .then((res) => {
        const data = (res as unknown) ?? null;
        // 兼容两种返回：直接的数组 / 包装在 data 里
        const list: Array<{
          customer_id: number;
          display_name?: string;
          stage?: string;
          hours_since_last_contact?: number;
          last_follow_up_at?: string;
          suggested_action?: string;
        }> = Array.isArray(data)
          ? (data as any)
          : Array.isArray((data as any)?.reminders)
          ? ((data as any).reminders as any)
          : [];
        const mapped: Reminder[] = list.map((it, idx) => {
          // 优先用后端给的 last_follow_up_at；否则按 hours_since_last_contact 推算一个过去时间
          const lastFollowUpAt =
            it.last_follow_up_at ??
            (typeof it.hours_since_last_contact === 'number'
              ? new Date(Date.now() - it.hours_since_last_contact * 3600 * 1000).toISOString()
              : new Date().toISOString());
          return {
            id: `reminder-${it.customer_id ?? idx}`,
            customerId: it.customer_id ?? idx,
            customerName: it.display_name || `客户${it.customer_id ?? idx}`,
            stage: it.stage || 'new',
            lastFollowUpAt,
            suggestedAction: it.suggested_action || '建议尽快跟进',
          };
        });
        setReminders(mapped);
      })
      .catch(() => setError('加载提醒失败，请稍后重试'))
      .finally(() => setLoading(false));
  }, [hours]);

  useEffect(() => {
    loadReminders();
  }, [loadReminders]);

  return (
    <div className="flex h-full w-[400px] shrink-0 flex-col border-r border-gray-200 bg-white dark:border-slate-700 dark:bg-slate-800">
      {/* 标题栏 */}
      <div className="border-b border-gray-100 px-5 py-4 dark:border-slate-700">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="h-5 w-5 text-amber-500" />
            <h2 className="text-base font-semibold text-gray-900 dark:text-slate-100">跟进提醒</h2>
            {reminders.length > 0 && (
              <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1.5 text-xs font-medium text-white">
                {reminders.length}
              </span>
            )}
          </div>
          <button
            onClick={loadReminders}
            aria-label="刷新提醒"
            className="rounded-md p-1.5 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
        {/* 筛选标签 */}
        <div className="mt-3 flex gap-1.5">
          {hourOptions.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setHours(opt.value)}
              aria-label={`筛选${opt.label}内的提醒`}
              className={`rounded-md px-3 py-1 text-xs font-medium transition ${
                hours === opt.value
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* 提醒列表 */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading && (
          <div className="flex items-center justify-center py-12">
            <RefreshCw className="h-5 w-5 animate-spin text-gray-400 dark:text-slate-500" />
            <span className="ml-2 text-sm text-gray-400 dark:text-slate-400">加载中...</span>
          </div>
        )}
        {error && (
          <div className="flex flex-col items-center justify-center py-12">
            <AlertTriangle className="mb-2 h-8 w-8 text-red-400" />
            <p className="text-sm text-red-500">{error}</p>
            <button
              onClick={loadReminders}
              aria-label="重试加载提醒"
              className="mt-2 text-xs text-blue-600 hover:underline"
            >
              重试
            </button>
          </div>
        )}
        {!loading && !error && reminders.length === 0 && (
          <div className="flex flex-col items-center justify-center py-12">
            <CheckCircle2 className="mb-2 h-10 w-10 text-green-400" />
            <p className="text-sm text-gray-500 dark:text-slate-400">所有客户都已及时跟进！</p>
          </div>
        )}
        {!loading && !error && reminders.length > 0 && (
          <div className="space-y-3">
            {reminders.map((item) => {
              const overdue = isOverdue(item.lastFollowUpAt, hours);
              return (
                <div
                  key={item.id}
                  className="rounded-lg border border-gray-100 p-3.5 transition hover:border-blue-200 hover:bg-blue-50/20 dark:border-slate-700 dark:hover:border-blue-700/50 dark:hover:bg-blue-500/10"
                >
                  {/* 客户名称 + 阶段标签 */}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => navigate(`/customers`)}
                      aria-label={`查看客户 ${item.customerName}`}
                      className="font-medium text-gray-900 hover:text-blue-600 hover:underline dark:text-slate-100 dark:hover:text-blue-400"
                    >
                      {item.customerName}
                    </button>
                    <span
                      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium ${getStageColor(item.stage)}`}
                    >
                      {formatStage(item.stage)}
                    </span>
                  </div>
                  {/* 距上次跟进时间 */}
                  <p className={`mt-1.5 text-xs ${overdue ? 'font-medium text-red-500' : 'text-gray-400 dark:text-slate-500'}`}>
                    {overdue && <AlertTriangle className="mr-0.5 inline h-3 w-3" />}
                    距上次跟进 {formatTimeAgo(item.lastFollowUpAt)}
                  </p>
                  {/* AI 建议 */}
                  <p className="mt-1.5 text-xs text-gray-500 dark:text-slate-400">
                    <Sparkles className="mr-0.5 inline h-3 w-3 text-amber-400" />
                    {item.suggestedAction}
                  </p>
                  {/* 去跟进按钮 */}
                  <button
                    onClick={() => navigate('/messages')}
                    aria-label={`去跟进 ${item.customerName}`}
                    className="mt-2.5 flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-blue-700"
                  >
                    去跟进
                    <ChevronRight className="h-3 w-3" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/* ========== 右栏上半部分：AI 对话 ========== */

function AIChatPanel({ selectedCustomerId, selectedCustomerName }: { selectedCustomerId: number | null; selectedCustomerName: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  /** 自动滚动到底部 */
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  /** 添加消息到对话列表 */
  const addMessage = (role: ChatMessage['role'], content: string, type?: ChatMessage['type']) => {
    setMessages((prev) => [
      ...prev,
      { id: uid(), role, content, timestamp: new Date().toISOString(), type },
    ]);
  };

  /** 发送普通消息 */
  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput('');
    addMessage('user', text);

    setSending(true);
    try {
      // 带上下文调用意图分析
      const res = await analyzeIntent(text, selectedCustomerName ? `当前客户：${selectedCustomerName}` : '');
      const data = (res as any)?.data ?? res;
      const reply = typeof data === 'string' ? data : data?.reply ?? data?.suggestion ?? data?.intent ?? JSON.stringify(data);
      addMessage('assistant', reply, 'text');
    } catch {
      addMessage('assistant', '抱歉，分析失败，请稍后重试。', 'text');
    } finally {
      setSending(false);
    }
  };

  /** 快捷操作：分析意图 */
  const handleAnalyzeIntent = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput('');
    addMessage('user', `分析意图：${text}`);

    setSending(true);
    try {
      const res = await analyzeIntent(text, selectedCustomerName ? `当前客户：${selectedCustomerName}` : '');
      const data = (res as any)?.data ?? res;
      const intent = data?.intent ?? '';
      const confidence = data?.confidence ?? '';
      const sentiment = data?.sentiment ?? '';
      const suggestion = data?.suggestion ?? '';
      const keywords = Array.isArray(data?.keywords) ? data.keywords.join('、') : '';

      let reply = `**意图分析结果**\n`;
      if (intent) reply += `意图：${intent}\n`;
      if (confidence) reply += `置信度：${confidence}\n`;
      if (sentiment) reply += `情感倾向：${sentiment}\n`;
      if (keywords) reply += `关键词：${keywords}\n`;
      if (suggestion) reply += `建议：${suggestion}`;

      addMessage('assistant', reply || '分析完成，但未返回有效结果。', 'intent');
    } catch {
      addMessage('assistant', '意图分析失败，请稍后重试。', 'intent');
    } finally {
      setSending(false);
    }
  };

  /** 快捷操作：推荐话术 */
  const handleSuggestReply = async () => {
    if (!selectedCustomerId) {
      addMessage('assistant', '请先在下方客户画像中选择一个客户，才能推荐话术。', 'suggest');
      return;
    }
    const text = input.trim() || '请推荐跟进话术';
    if (sending) return;
    setInput('');
    addMessage('user', `推荐话术：${text}`);

    setSending(true);
    try {
      const res = await suggestReply(selectedCustomerId, text);
      const data = (res as any)?.data ?? res;
      const reply = typeof data === 'string' ? data : data?.reply ?? data?.suggestion ?? JSON.stringify(data);
      addMessage('assistant', reply, 'suggest');
    } catch {
      addMessage('assistant', '推荐话术失败，请稍后重试。', 'suggest');
    } finally {
      setSending(false);
    }
  };

  /** 快捷操作：生成回复 */
  const handleAutoReply = async () => {
    if (!selectedCustomerId) {
      addMessage('assistant', '请先在下方客户画像中选择一个客户，才能生成回复。', 'auto_reply');
      return;
    }
    const text = input.trim() || '请生成自动回复';
    if (sending) return;
    setInput('');
    addMessage('user', `生成回复：${text}`);

    setSending(true);
    try {
      const res = await generateAutoReply(selectedCustomerId, text);
      const data = (res as any)?.data ?? res;
      const reply = typeof data === 'string' ? data : data?.reply ?? data?.suggestion ?? JSON.stringify(data);
      addMessage('assistant', reply, 'auto_reply');
    } catch {
      addMessage('assistant', '生成回复失败，请稍后重试。', 'auto_reply');
    } finally {
      setSending(false);
    }
  };

  /** 键盘回车发送 */
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  /** 消息类型标签 */
  const typeLabelMap: Record<string, { icon: React.ElementType; label: string; color: string }> = {
    intent: { icon: Target, label: '意图分析', color: 'text-indigo-500' },
    suggest: { icon: Lightbulb, label: '推荐话术', color: 'text-amber-500' },
    auto_reply: { icon: Wand2, label: '自动回复', color: 'text-purple-500' },
  };

  return (
    <div className="flex flex-1 flex-col border-b border-gray-200">
      {/* 标题栏 */}
      <div className="flex items-center gap-2 border-b border-gray-100 px-5 py-3.5">
        <Bot className="h-5 w-5 text-blue-500" />
        <h2 className="text-base font-semibold text-gray-900">AI 助手</h2>
        {selectedCustomerName && (
          <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-600">
            当前客户：{selectedCustomerName}
          </span>
        )}
      </div>

      {/* 对话区域 */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-50 to-indigo-100">
              <Bot className="h-7 w-7 text-blue-500" />
            </div>
            <p className="text-sm font-medium text-gray-600">你好，我是 AI 助手</p>
            <p className="mt-1 text-xs text-gray-400">输入消息或使用快捷操作开始对话</p>
          </div>
        )}
        <div className="space-y-4">
          {messages.map((msg) => {
            const typeInfo = msg.type ? typeLabelMap[msg.type] : null;
            const isUser = msg.role === 'user';
            return (
              <div
                key={msg.id}
                className={`flex ${isUser ? 'justify-end' : 'justify-start'} animate-fadeIn`}
              >
                <div className={`max-w-[80%] ${isUser ? 'order-2' : ''}`}>
                  {/* 类型标签 */}
                  {typeInfo && !isUser && (
                    <div className={`mb-1 flex items-center gap-1 text-xs ${typeInfo.color}`}>
                      <typeInfo.icon className="h-3 w-3" />
                      {typeInfo.label}
                    </div>
                  )}
                  {/* 气泡 */}
                  <div
                    className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
                      isUser
                        ? 'bg-blue-600 text-white'
                        : 'bg-gray-100 text-gray-800'
                    }`}
                  >
                    {msg.content}
                  </div>
                  <p className="mt-1 text-[10px] text-gray-400">
                    {new Date(msg.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                  </p>
                </div>
              </div>
            );
          })}
          {/* 加载中提示 */}
          {sending && (
            <div className="flex justify-start animate-fadeIn">
              <div className="rounded-2xl bg-gray-100 px-4 py-2.5">
                <div className="flex items-center gap-1.5 text-sm text-gray-500">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                  AI 正在思考...
                </div>
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>
      </div>

      {/* 快捷操作 + 输入框 */}
      <div className="border-t border-gray-100 px-5 py-3">
        {/* 快捷按钮（新手教程锚点：分析意图） */}
        <div className="mb-2.5 flex gap-2">
          <button
            onClick={handleAnalyzeIntent}
            disabled={sending}
            aria-label="分析客户意图"
            data-tour="ai-analyze"
            className="flex items-center gap-1 rounded-md bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-600 transition hover:bg-indigo-100 disabled:opacity-50"
          >
            <Target className="h-3.5 w-3.5" />
            分析意图
          </button>
          <button
            onClick={handleSuggestReply}
            disabled={sending}
            aria-label="推荐跟进话术"
            className="flex items-center gap-1 rounded-md bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-600 transition hover:bg-amber-100 disabled:opacity-50"
          >
            <Lightbulb className="h-3.5 w-3.5" />
            推荐话术
          </button>
          <button
            onClick={handleAutoReply}
            disabled={sending}
            aria-label="自动生成回复"
            className="flex items-center gap-1 rounded-md bg-purple-50 px-3 py-1.5 text-xs font-medium text-purple-600 transition hover:bg-purple-100 disabled:opacity-50"
          >
            <Wand2 className="h-3.5 w-3.5" />
            生成回复
          </button>
        </div>
        {/* 输入框 */}
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息或问题..."
            aria-label="AI 聊天输入框"
            data-tour="ai-input"
            rows={1}
            className="flex-1 resize-none rounded-lg border border-gray-200 bg-gray-50 px-3.5 py-2.5 text-sm text-gray-800 outline-none transition focus:border-blue-400 focus:bg-white dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:bg-slate-800"
          />
          <button
            onClick={handleSend}
            disabled={sending || !input.trim()}
            aria-label="发送消息"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-white transition hover:bg-blue-700 disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

/* ========== 右栏下半部分：客户画像 ========== */

function CustomerProfilePanel({
  selectedCustomerId,
  onSelectCustomer,
}: {
  selectedCustomerId: number | null;
  onSelectCustomer: (id: number, name: string) => void;
}) {
  const [profile, setProfile] = useState<CustomerProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searchText, setSearchText] = useState('');
  const [customerList, setCustomerList] = useState<ClientSummary[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  /** 加载客户列表（用于搜索下拉） */
  useEffect(() => {
    setLoadingList(true);
    queryPipelines({ limit: 50 })
      .then((res) => {
        const data = (res as any)?.data ?? res;
        const items = Array.isArray(data) ? data : (data as any)?.items ?? [];
        setCustomerList(items);
      })
      .catch(() => setCustomerList([]))
      .finally(() => setLoadingList(false));
  }, []);

  /** 点击外部关闭下拉 */
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  /** 加载客户画像 */
  const loadProfile = useCallback((customerId: number) => {
    setLoading(true);
    setError('');
    getCustomerProfile(customerId)
      .then((res) => {
        const data = (res as any)?.data ?? res;
        setProfile(data);
      })
      .catch(() => {
        setError('加载画像失败');
        setProfile(null);
      })
      .finally(() => setLoading(false));
  }, []);

  /** 选中客户变化时加载画像 */
  useEffect(() => {
    if (selectedCustomerId) {
      loadProfile(selectedCustomerId);
    } else {
      setProfile(null);
    }
  }, [selectedCustomerId, loadProfile]);

  /** 刷新画像 */
  const handleRefresh = async () => {
    if (!selectedCustomerId) return;
    setLoading(true);
    try {
      await updateAiScore(selectedCustomerId);
      loadProfile(selectedCustomerId);
    } catch {
      setError('刷新画像失败');
      setLoading(false);
    }
  };

  /** 筛选客户列表 */
  const filteredCustomers = customerList.filter((c) =>
    c.display_name?.toLowerCase().includes(searchText.toLowerCase()) ||
    c.username?.toLowerCase().includes(searchText.toLowerCase())
  );

  /** 紧迫度信息 */
  const urgencyInfo = profile?.urgency
    ? urgencyColorMap[profile.urgency] ?? urgencyColorMap.medium
    : null;

  /** AI 评分颜色 */
  function getScoreColor(score: number): string {
    if (score >= 80) return 'bg-green-500';
    if (score >= 60) return 'bg-blue-500';
    if (score >= 40) return 'bg-amber-500';
    return 'bg-red-500';
  }

  return (
    <div className="flex h-[320px] shrink-0 flex-col bg-white dark:bg-slate-800">
      {/* 标题栏 */}
      <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3.5">
        <div className="flex items-center gap-2">
          <UserCircle className="h-5 w-5 text-indigo-500" />
          <h2 className="text-base font-semibold text-gray-900">客户画像</h2>
        </div>
        {selectedCustomerId && (
          <button
            onClick={handleRefresh}
            disabled={loading}
            aria-label="刷新客户画像"
            className="flex items-center gap-1 rounded-md bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-600 transition hover:bg-gray-200 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            刷新画像
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {/* 客户搜索选择 */}
        <div className="relative mb-4" ref={dropdownRef}>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={searchText}
              onChange={(e) => {
                setSearchText(e.target.value);
                setShowDropdown(true);
              }}
              onFocus={() => setShowDropdown(true)}
              placeholder="搜索选择客户..."
              aria-label="搜索选择客户"
              className="w-full rounded-lg border border-gray-200 bg-gray-50 py-2 pl-9 pr-3 text-sm outline-none transition focus:border-blue-400 focus:bg-white dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            />
          </div>
          {/* 下拉列表 */}
          {showDropdown && (
            <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-48 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-800">
              {loadingList && (
                <p className="px-4 py-3 text-xs text-gray-400">加载中...</p>
              )}
              {!loadingList && filteredCustomers.length === 0 && (
                <p className="px-4 py-3 text-xs text-gray-400">未找到客户</p>
              )}
              {filteredCustomers.map((c) => (
                <button
                  key={c.customer_id}
                  data-customer-option={c.customer_id}
                  onClick={() => {
                    onSelectCustomer(c.customer_id, c.display_name || c.username);
                    setSearchText(c.display_name || c.username);
                    setShowDropdown(false);
                  }}
                  aria-label={`选择客户 ${c.display_name || c.username}`}
                  className={`flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm transition hover:bg-blue-50 ${
                    selectedCustomerId === c.customer_id ? 'bg-blue-50 text-blue-700' : 'text-gray-700'
                  }`}
                >
                  <span className="font-medium">{c.display_name || c.username}</span>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${getStageColor(c.stage)}`}>
                    {formatStage(c.stage)}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 未选择客户 */}
        {!selectedCustomerId && (
          <div className="flex flex-col items-center justify-center py-6 text-center">
            <UserCircle className="mb-2 h-10 w-10 text-gray-300" />
            <p className="text-sm text-gray-400">请选择客户查看 AI 画像</p>
          </div>
        )}

        {/* 加载中 */}
        {selectedCustomerId && loading && (
          <div className="flex items-center justify-center py-6">
            <RefreshCw className="h-5 w-5 animate-spin text-gray-400" />
            <span className="ml-2 text-sm text-gray-400">加载画像中...</span>
          </div>
        )}

        {/* 加载失败 */}
        {selectedCustomerId && error && !loading && (
          <div className="flex flex-col items-center justify-center py-6">
            <AlertTriangle className="mb-2 h-8 w-8 text-red-400" />
            <p className="text-sm text-red-500">{error}</p>
          </div>
        )}

        {/* 画像卡片 */}
        {selectedCustomerId && !loading && !error && profile && (
          <div className="space-y-3">
            {/* 一句话画像 */}
            {profile.summary && (
              <div className="rounded-lg bg-gradient-to-r from-blue-50 to-indigo-50 p-3.5">
                <p className="text-sm font-medium text-gray-800">{profile.summary}</p>
              </div>
            )}

            {/* 画像详情网格 */}
            <div className="grid grid-cols-2 gap-2.5">
              {/* 需求偏好 */}
              <div className="rounded-lg border border-gray-100 bg-white p-3 shadow-sm dark:border-slate-700 dark:bg-slate-700/50">
                <div className="mb-1.5 flex items-center gap-1.5 text-xs text-gray-400">
                  <Target className="h-3.5 w-3.5" />
                  需求偏好
                </div>
                <p className="text-sm font-medium text-gray-800">
                  {profile.preferences || '暂无'}
                </p>
              </div>
              {/* 决策角色 */}
              <div className="rounded-lg border border-gray-100 bg-white p-3 shadow-sm dark:border-slate-700 dark:bg-slate-700/50">
                <div className="mb-1.5 flex items-center gap-1.5 text-xs text-gray-400">
                  <UserCircle className="h-3.5 w-3.5" />
                  决策角色
                </div>
                <p className="text-sm font-medium text-gray-800">
                  {profile.decisionRole || '暂无'}
                </p>
              </div>
              {/* 预算感知 */}
              <div className="rounded-lg border border-gray-100 bg-white p-3 shadow-sm dark:border-slate-700 dark:bg-slate-700/50">
                <div className="mb-1.5 flex items-center gap-1.5 text-xs text-gray-400">
                  <DollarSign className="h-3.5 w-3.5" />
                  预算感知
                </div>
                <p className="text-sm font-medium text-gray-800">
                  {profile.budgetAwareness || '暂无'}
                </p>
              </div>
              {/* 紧迫度 */}
              <div className="rounded-lg border border-gray-100 bg-white p-3 shadow-sm dark:border-slate-700 dark:bg-slate-700/50">
                <div className="mb-1.5 flex items-center gap-1.5 text-xs text-gray-400">
                  <Zap className="h-3.5 w-3.5" />
                  紧迫度
                </div>
                {urgencyInfo ? (
                  <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${urgencyInfo.bg} ${urgencyInfo.text}`}>
                    {urgencyInfo.label}
                  </span>
                ) : (
                  <p className="text-sm text-gray-400">暂无</p>
                )}
              </div>
            </div>

            {/* AI 标签 */}
            {profile.aiTags && profile.aiTags.length > 0 && (
              <div className="rounded-lg border border-gray-100 bg-white p-3 shadow-sm dark:border-slate-700 dark:bg-slate-700/50">
                <div className="mb-2 flex items-center gap-1.5 text-xs text-gray-400">
                  <Tag className="h-3.5 w-3.5" />
                  AI 标签
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {profile.aiTags.map((tag: string, idx: number) => (
                    <span
                      key={idx}
                      className="rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-600"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* AI 评分 */}
            {profile.aiScore !== undefined && profile.aiScore !== null && (
              <div className="rounded-lg border border-gray-100 bg-white p-3 shadow-sm dark:border-slate-700 dark:bg-slate-700/50">
                <div className="mb-2 flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-xs text-gray-400">
                    <BarChart3 className="h-3.5 w-3.5" />
                    AI 评分
                  </div>
                  <span className="text-sm font-bold text-gray-900">{profile.aiScore}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${getScoreColor(profile.aiScore)}`}
                    style={{ width: `${Math.min(100, Math.max(0, profile.aiScore))}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {/* 选中客户但无画像数据 */}
        {selectedCustomerId && !loading && !error && !profile && (
          <div className="flex flex-col items-center justify-center py-6">
            <MessageSquare className="mb-2 h-8 w-8 text-gray-300" />
            <p className="text-sm text-gray-400">暂无画像数据，点击"刷新画像"获取</p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ========== 主组件 ========== */

export default function AIAssistant() {
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | null>(null);
  const [selectedCustomerName, setSelectedCustomerName] = useState('');

  /** 选择客户回调 */
  const handleSelectCustomer = (id: number, name: string) => {
    setSelectedCustomerId(id);
    setSelectedCustomerName(name);
  };

  return (
    // -m-6 抵消父布局（Layout.tsx 中 <main> 内的 p-6），
    // 让提醒栏 / 对话区 / 画像栏 贴满整块内容区，无外边距。
    // 如果父布局 padding 变更，这里需同步调整。
    <div className="flex h-full -m-6">
      {/* 左栏：跟进提醒 */}
      <ReminderPanel />

      {/* 右栏：AI 对话 + 客户画像 */}
      <div className="flex flex-1 flex-col bg-gray-50 dark:bg-slate-900">
        <AIChatPanel
          selectedCustomerId={selectedCustomerId}
          selectedCustomerName={selectedCustomerName}
        />
        <CustomerProfilePanel
          selectedCustomerId={selectedCustomerId}
          onSelectCustomer={handleSelectCustomer}
        />
      </div>
    </div>
  );
}
