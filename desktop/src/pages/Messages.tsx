import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Search,
  Send,
  MessageCircle,
  Sparkles,
  Bot,
  X,
  Loader2,
  ChevronRight,
} from 'lucide-react';
import { clsx } from 'clsx';
import ChannelLogo, { CHANNEL_BRAND_COLOR } from '../components/ChannelLogo';
import { getMessages, sendMessage, suggestReply, getChannels } from '../api/messages';
import { getScriptHint } from '../api/sales';
import { useApiQuery, useApiMutation, useQueryClient } from '../hooks/useApiQuery';
import { useMessageStore } from '../stores/message';
import { useSalesStore } from '../stores/salesStore';
import ScriptHintToast from '../components/ScriptHintToast';
import { unwrapApiResponse } from '../utils/format';
import type { SalesScriptHint } from '../types';

/** 消息项（API 返回） */
interface MessageItem {
  id: string;
  customer_id: number;
  customer_name: string;
  contact_id: string;
  channel_type: string;
  direction: 'inbound' | 'outbound';
  content: string;
  ai_intent?: string;
  read: boolean;
  created_at: string;
}

/** 联系人分组（按客户聚合） */
interface ContactGroup {
  customerId: number;
  customerName: string;
  channelTypes: string[];
  lastMessage: string;
  lastTime: string;
  /** 最后一条消息的发送方向：inbound=客户发，outbound=我发 */
  lastMessageDirection: 'inbound' | 'outbound';
  /** 最后一条消息所属渠道（用于列表角标） */
  lastMessageChannel: string;
  unreadCount: number;
  messages: MessageItem[];
}

/** 渠道信息 */
interface ChannelItem {
  id: string;
  name: string;
  type: string;
}

/** 阶段标签颜色映射（与 Dashboard/Format 统一） */
const STAGE_COLORS: Record<string, string> = {
  lead: 'bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-slate-300',
  new: 'bg-blue-50 text-blue-600 dark:bg-blue-500/20 dark:text-blue-300',
  qualified: 'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-300',
  contacted: 'bg-cyan-50 text-cyan-600 dark:bg-cyan-500/20 dark:text-cyan-300',
  interested: 'bg-amber-50 text-amber-600 dark:bg-amber-500/20 dark:text-amber-300',
  intention: 'bg-orange-50 text-orange-600 dark:bg-orange-500/20 dark:text-orange-300',
  proposal: 'bg-purple-50 text-purple-600 dark:bg-purple-500/20 dark:text-purple-300',
  negotiation: 'bg-rose-50 text-rose-600 dark:bg-rose-500/20 dark:text-rose-300',
  closed_won: 'bg-green-50 text-green-600 dark:bg-green-500/20 dark:text-green-300',
  closed_lost: 'bg-red-50 text-red-600 dark:bg-red-500/20 dark:text-red-300',
  deal: 'bg-green-50 text-green-600 dark:bg-green-500/20 dark:text-green-300',
  no_contact: 'bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-slate-300',
  connected: 'bg-cyan-50 text-cyan-600 dark:bg-cyan-500/20 dark:text-cyan-300',
  requirement: 'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-300',
  submitted: 'bg-purple-50 text-purple-600 dark:bg-purple-500/20 dark:text-purple-300',
  quoted: 'bg-amber-50 text-amber-600 dark:bg-amber-500/20 dark:text-amber-300',
  negotiating: 'bg-rose-50 text-rose-600 dark:bg-rose-500/20 dark:text-rose-300',
  pending_sign: 'bg-pink-50 text-pink-600 dark:bg-pink-500/20 dark:text-pink-300',
  signed: 'bg-green-50 text-green-600 dark:bg-green-500/20 dark:text-green-300',
  delivering: 'bg-blue-50 text-blue-600 dark:bg-blue-500/20 dark:text-blue-300',
  delivered: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300',
};

/** 阶段 ID 转中文标签 */
const STAGE_LABELS: Record<string, string> = {
  lead: '线索', new: '新线索', qualified: '合格线索', contacted: '已联系',
  connected: '已建联', interested: '有意向', intention: '意向客户',
  requirement: '需求采集', submitted: '已提交', quoted: '已报价',
  negotiation: '商务谈判', negotiating: '议价', closed_won: '成交',
  closed_lost: '流失', deal: '成交', pending_sign: '待签', signed: '已签',
  delivering: '交付中', delivered: '已交付',
};

function getStageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

/** AI 意图标签颜色 */
const INTENT_STYLES: Record<string, string> = {
  询价: 'bg-blue-50 text-blue-600 dark:bg-blue-500/20 dark:text-blue-300',
  催促: 'bg-red-50 text-red-600 dark:bg-red-500/20 dark:text-red-300',
  投诉: 'bg-red-50 text-red-600 dark:bg-red-500/20 dark:text-red-300',
  预约: 'bg-green-50 text-green-600 dark:bg-green-500/20 dark:text-green-300',
  咨询: 'bg-yellow-50 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-300',
  确认: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300',
};

/** 跟进建议生成器（基于客户实际数据） */
interface FollowUpSuggestion {
  text: string;
  type: 'urgent' | 'info' | 'normal';
}

function generateFollowUpSuggestions(contact: ContactGroup): FollowUpSuggestion[] {
  const suggestions: FollowUpSuggestion[] = [];
  const msgCount = contact.messages.length;
  const lastMsg = contact.messages[msgCount - 1];
  const hasInbound = contact.messages.some((m) => m.direction === 'inbound');
  const hasOutbound = contact.messages.some((m) => m.direction === 'outbound');

  // 如果有未回复的入站消息
  if (hasInbound && (!hasOutbound || (lastMsg && lastMsg.direction === 'inbound'))) {
    suggestions.push({
      text: `客户有未回复消息，建议尽快回复${contact.customerName}`,
      type: 'urgent',
    });
  }

  // 根据消息数量给出建议
  if (msgCount < 3) {
    suggestions.push({
      text: `与${contact.customerName}沟通较少，建议主动了解需求`,
      type: 'info',
    });
  } else if (msgCount < 10) {
    suggestions.push({
      text: `沟通进行中，建议推进到下一阶段`,
      type: 'normal',
    });
  } else {
    suggestions.push({
      text: `与${contact.customerName}沟通充分，建议及时推动成交`,
      type: 'info',
    });
  }

  // 根据最后一条消息的 AI 意图给出建议
  if (lastMsg?.ai_intent) {
    const intentSuggestions: Record<string, string> = {
      '询价': '客户询价中，建议提供详细报价方案',
      '催促': '客户有催促行为，建议优先处理',
      '投诉': '客户可能不满，建议及时安抚',
      '预约': '客户有预约意向，建议尽快确认时间',
      '咨询': '客户正在了解，建议详细介绍产品',
      '确认': '客户在确认细节，建议快速响应',
    };
    suggestions.push({
      text: intentSuggestions[lastMsg.ai_intent] ?? `关注客户"${lastMsg.ai_intent}"意图`,
      type: 'urgent',
    });
  }

  // 默认建议
  if (suggestions.length < 2) {
    suggestions.push({
      text: '保持定期沟通，避免客户流失',
      type: 'normal',
    });
  }

  return suggestions.slice(0, 3);
}

/** 格式化时间 */
function formatTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const oneDay = 86400000;

  if (diff < 60000) return '刚刚';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`;
  if (diff < oneDay) return `${Math.floor(diff / 3600000)}小时前`;
  if (diff < oneDay * 2) return '昨天';
  if (diff < oneDay * 7) return `${Math.floor(diff / oneDay)}天前`;
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

/** 渠道名称映射 */
const CHANNEL_LABEL: Record<string, string> = {
  wework: '企微', sms: '短信', email: '邮件', phone: '电话',
  douyin: '抖音', miniprogram: '小程序', pdd: '拼多多', taobao: '淘宝',
  jd: '京东', alibaba: '1688', whatsapp: 'WhatsApp', telegram: 'Telegram', line: 'LINE',
};

/** 消息按客户聚合成分组列表 */
function groupMessagesByCustomer(messages: MessageItem[]): ContactGroup[] {
  const groupMap = new Map<number, ContactGroup>();
  for (const msg of messages) {
    const existing = groupMap.get(msg.customer_id);
    if (existing) {
      existing.messages.push(msg);
      existing.channelTypes = [...new Set([...existing.channelTypes, msg.channel_type])];
      // 更新最新消息（按时间比较）
      if (new Date(msg.created_at) > new Date(existing.lastTime)) {
        existing.lastMessage = msg.content;
        existing.lastTime = msg.created_at;
        existing.lastMessageDirection = msg.direction;
        existing.lastMessageChannel = msg.channel_type;
      }
      if (!msg.read && msg.direction === 'inbound') {
        existing.unreadCount += 1;
      }
    } else {
      groupMap.set(msg.customer_id, {
        customerId: msg.customer_id,
        customerName: msg.customer_name,
        channelTypes: [msg.channel_type],
        lastMessage: msg.content,
        lastTime: msg.created_at,
        lastMessageDirection: msg.direction,
        lastMessageChannel: msg.channel_type,
        unreadCount: !msg.read && msg.direction === 'inbound' ? 1 : 0,
        messages: [msg],
      });
    }
  }

  // 按最近消息时间排序
  const sorted = Array.from(groupMap.values()).sort(
    (a, b) => new Date(b.lastTime).getTime() - new Date(a.lastTime).getTime()
  );
  // 对每个联系人的消息按时间排序
  for (const group of sorted) {
    group.messages.sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
  }
  return sorted;
}

/** 统一消息中心主页面 */
export default function Messages() {
  const queryClient = useQueryClient();
  const [selectedContactId, setSelectedContactId] = useState<number | null>(null);
  const [searchText, setSearchText] = useState('');

  // 输入区状态
  const [inputText, setInputText] = useState('');
  const [selectedChannel, setSelectedChannel] = useState('wework');

  // AI 助手侧边栏
  const [aiSidebarOpen, setAiSidebarOpen] = useState(true);
  const [aiSuggestions, setAiSuggestions] = useState<string[]>([]);

  // 推荐话术浮层
  const [showQuickReplies, setShowQuickReplies] = useState(false);
  const [scriptHint, setScriptHint] = useState<SalesScriptHint | null>(null);
  const scriptHintsEnabled = useSalesStore((s) => s.scriptHintsEnabled);

  const SALES_STAGES = ['quoted', 'negotiating', 'pending_sign', 'proposal'];

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 进入消息中心即标记全部已读；同时主动同步一次未读汇总（不等下一轮 poll）
  const markAllRead = useMessageStore((s) => s.markAllRead);
  const markCustomerRead = useMessageStore((s) => s.markCustomerRead);
  const fetchUnread = useMessageStore((s) => s.fetchUnread);
  // 用 store 的未读分桶作为联系人列表红点的单一数据源。
  // markCustomerRead / markAllRead 会同步更新它，红点就能立刻消失。
  const unreadByCustomer = useMessageStore((s) => s.unreadByCustomer);
  useEffect(() => {
    void markAllRead();
    void fetchUnread();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---- React Query：5 秒自动轮询模拟实时 ---- */
  const {
    data: messagesRaw = [],
    isLoading: loading,
  } = useApiQuery<MessageItem[]>(
    ['messages', 'list'],
    async () => {
      const res = await getMessages({ limit: 50 });
      const data = unwrapApiResponse<MessageItem[] | { messages: MessageItem[] }>(res);
      if (Array.isArray(data)) return data;
      if (data && Array.isArray((data as { messages: MessageItem[] }).messages)) {
        return (data as { messages: MessageItem[] }).messages;
      }
      return [];
    },
    {
      // 5s 轮询：模拟实时消息
      refetchInterval: 5 * 1000,
      refetchIntervalInBackground: false,
    }
  );

  // 渠道列表（一次性拉取，无需轮询）
  const { data: channelsRaw = [] } = useApiQuery<ChannelItem[]>(
    ['messages', 'channels'],
    async () => {
      const res = await getChannels();
      const data = unwrapApiResponse<ChannelItem[] | { channels: ChannelItem[] }>(res);
      if (Array.isArray(data)) return data;
      if (data && Array.isArray((data as { channels: ChannelItem[] }).channels)) {
        return (data as { channels: ChannelItem[] }).channels;
      }
      return [];
    },
    { staleTime: 5 * 60 * 1000 }
  );

  // 按客户聚合
  const contacts = groupMessagesByCustomer(messagesRaw);
  const selectedContact = contacts.find((c) => c.customerId === selectedContactId) ?? null;

  /* ---- 发送消息 Mutation ---- */
  const sendMutation = useApiMutation<
    unknown,
    { customerId: number; channel: string; contactId: string; content: string }
  >(
    (vars) => sendMessage(vars.customerId, vars.channel, vars.contactId, vars.content),
    {
      onSuccess: () => {
        setInputText('');
        setShowQuickReplies(false);
        // 立即拉取最新消息
        queryClient.invalidateQueries({ queryKey: ['messages', 'list'] });
      },
      onError: () => {
        // 错误 toast 由 axios 拦截器自动处理
      },
    }
  );

  /* ---- AI 推荐回复 Mutation ---- */
  const suggestMutation = useApiMutation<{ suggestions: string[] }, { customerId: number; message: string }>(
    async (vars) => {
      const res = await suggestReply(vars.customerId, vars.message);
      const data = unwrapApiResponse<{ suggestions?: string[]; replies?: string[] }>(res);
      return { suggestions: data?.suggestions ?? data?.replies ?? [] };
    },
    {
      onSuccess: (data) => {
        const list = data.suggestions.length > 0
          ? data.suggestions
          : [
              '您好，感谢您的咨询，我来为您详细解答。',
              '好的，我马上帮您确认一下。',
              '这个问题我需要和同事确认后回复您，请稍等。',
            ];
        setAiSuggestions(list);
        setShowQuickReplies(true);
      },
      onError: () => {
        // 失败时使用兜底话术
        setAiSuggestions(['您好，感谢您的咨询，我来为您详细解答。', '好的，我马上帮您确认一下。', '这个问题我需要和同事确认后回复您，请稍等。']);
        setShowQuickReplies(true);
      },
    }
  );

  /** 选中联系人后滚动到底部 */
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [selectedContactId]);

  /** 销售关键节点话术提示 */
  useEffect(() => {
    if (!scriptHintsEnabled || !selectedContact) return;
    const lastMsg = selectedContact.messages[selectedContact.messages.length - 1];
    if (!lastMsg || lastMsg.direction !== 'inbound') return;
    const stage = lastMsg.ai_intent ?? 'quoted';
    if (!SALES_STAGES.includes(stage)) return;
    getScriptHint(selectedContact.customerId, stage).then(setScriptHint).catch(() => {});
  }, [selectedContact, scriptHintsEnabled]);

  /** 发送消息 */
  const handleSend = useCallback(() => {
    if (!selectedContact || !inputText.trim()) return;
    sendMutation.mutate({
      customerId: selectedContact.customerId,
      channel: selectedChannel,
      contactId: selectedContact.messages[0]?.contact_id ?? '',
      content: inputText.trim(),
    });
  }, [selectedContact, inputText, selectedChannel, sendMutation]);

  /** 键盘事件：Enter 发送，Shift+Enter 换行 */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  /** 获取 AI 推荐回复 */
  const handleAiSuggest = useCallback(() => {
    if (!selectedContact) return;
    const lastMsg = selectedContact.messages[selectedContact.messages.length - 1];
    suggestMutation.mutate({
      customerId: selectedContact.customerId,
      message: lastMsg?.content ?? '',
    });
  }, [selectedContact, suggestMutation]);

  /** 快速推荐话术（AI 推荐按钮） */
  const handleQuickSuggest = useCallback(() => {
    if (!selectedContact) return;
    const lastMsg = selectedContact.messages[selectedContact.messages.length - 1];
    suggestMutation.mutate(
      {
        customerId: selectedContact.customerId,
        message: lastMsg?.content ?? '',
      },
      {
        onSuccess: (data) => {
          // 快速话术使用短一些的兜底
          if (data.suggestions.length === 0) {
            setAiSuggestions(['好的，收到！', '我来帮您查一下。', '稍等，马上回复您。']);
          }
        },
      }
    );
  }, [selectedContact, suggestMutation]);

  /** 一键填入推荐话术 */
  const handleFillSuggestion = (text: string) => {
    setInputText(text);
    setShowQuickReplies(false);
    textareaRef.current?.focus();
  };

  /** 搜索过滤联系人 */
  const filteredContacts = contacts.filter((c) => {
    if (!searchText) return true;
    return c.customerName.toLowerCase().includes(searchText.toLowerCase());
  });

  /** 选中联系人：切换会话 + 同步清除该客户的未读徽标 */
  const handleSelectContact = useCallback(
    (customerId: number) => {
      setSelectedContactId(customerId);
      void markCustomerRead(customerId);
    },
    [markCustomerRead]
  );

  const sending = sendMutation.isPending;
  const aiLoading = suggestMutation.isPending;

  return (
    <div className="flex h-full overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800">
      {/* ===== 左栏：联系人列表（新手教程锚点） ===== */}
      <div data-tour="messages-contact-list" className="flex w-[280px] shrink-0 flex-col border-r border-gray-200 bg-gray-50/50 dark:border-slate-700 dark:bg-slate-800/50">
        {/* 搜索框 */}
        <div className="border-b border-gray-200 p-3 dark:border-slate-700">
          <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900">
            <Search className="h-4 w-4 text-gray-400 dark:text-slate-500" />
            <input
              type="text"
              placeholder="搜索联系人..."
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              aria-label="搜索联系人"
              className="flex-1 bg-transparent text-sm text-gray-700 outline-none placeholder:text-gray-400 dark:text-slate-200 dark:placeholder:text-slate-500"
            />
          </div>
        </div>

        {/* 联系人列表 */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            // 骨架屏
            Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3 px-4 py-3">
                <div className="h-10 w-10 animate-pulse rounded-full bg-gray-200 dark:bg-slate-700" />
                <div className="flex-1">
                  <div className="h-3.5 w-20 animate-pulse rounded bg-gray-200 dark:bg-slate-700" />
                  <div className="mt-1.5 h-2.5 w-full animate-pulse rounded bg-gray-100 dark:bg-slate-700/60" />
                </div>
              </div>
            ))
          ) : filteredContacts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-gray-400 dark:text-slate-500">
              <MessageCircle className="mb-2 h-8 w-8" />
              <span className="text-sm">暂无联系人</span>
            </div>
          ) : (
            filteredContacts.map((contact) => {
              // 以 store 的未读分桶为准：markCustomerRead 之后立即归零
              const storeUnread = unreadByCustomer[String(contact.customerId)] ?? 0;
              const isUnread = storeUnread > 0;
              const isOutbound = contact.lastMessageDirection === 'outbound';
              const previewText = isOutbound
                ? `我: ${contact.lastMessage}`
                : contact.lastMessage;
              const cornerChannel = contact.lastMessageChannel || contact.channelTypes[0];
              return (
                <button
                  key={contact.customerId}
                  data-contact-id={contact.customerId}
                  onClick={() => handleSelectContact(contact.customerId)}
                  aria-label={`选择与 ${contact.customerName} 的对话${isUnread ? `，有 ${storeUnread} 条未读` : ''}`}
                  className={clsx(
                    'flex w-full items-center gap-3 px-4 py-3 text-left transition-colors',
                    selectedContactId === contact.customerId
                      ? 'bg-blue-50 border-r-2 border-blue-500 dark:bg-blue-500/20 dark:border-blue-400'
                      : 'hover:bg-gray-100 dark:hover:bg-slate-700/50'
                  )}
                >
                  {/* 头像（渠道 Logo） */}
                  <div className="relative shrink-0">
                    <div
                      className={clsx(
                        'flex h-10 w-10 items-center justify-center rounded-full',
                        selectedContactId === contact.customerId
                          ? 'bg-blue-50 dark:bg-blue-500/20'
                          : 'bg-gray-50 dark:bg-slate-700'
                      )}
                    >
                      <ChannelLogo type={cornerChannel ?? 'wework'} size={28} />
                    </div>
                    {/* 渠道名称角标 */}
                    {cornerChannel && (
                      <div className="absolute -bottom-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full border border-white bg-white px-1 dark:border-slate-800 dark:bg-slate-800" style={{ fontSize: 9, fontWeight: 600, color: CHANNEL_BRAND_COLOR[cornerChannel] ?? '#6B7280' }}>
                        {CHANNEL_LABEL[cornerChannel] ?? cornerChannel}
                      </div>
                    )}
                  </div>

                  {/* 名称 + 摘要 */}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between">
                      <span
                        className={clsx(
                          'truncate text-sm',
                          isUnread
                            ? 'font-semibold text-gray-900 dark:text-slate-100'
                            : 'font-medium text-gray-900 dark:text-slate-100'
                        )}
                      >
                        {contact.customerName}
                      </span>
                      <span
                        className={clsx(
                          'ml-1 shrink-0 text-[10px]',
                          isUnread
                            ? 'text-blue-500 dark:text-blue-400'
                            : 'text-gray-400 dark:text-slate-500'
                        )}
                      >
                        {formatTime(contact.lastTime)}
                      </span>
                    </div>
                    <p
                      className={clsx(
                        'mt-0.5 truncate text-xs',
                        isUnread
                          ? 'font-medium text-gray-700 dark:text-slate-200'
                          : 'text-gray-500 dark:text-slate-400'
                      )}
                    >
                      {previewText}
                    </p>
                  </div>

                  {/* 未读徽标 */}
                  {storeUnread > 0 && (
                    <span className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-medium text-white">
                      {storeUnread > 99 ? '99+' : storeUnread}
                    </span>
                  )}
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* ===== 中栏：对话详情 ===== */}
      <div className="flex flex-1 flex-col">
        {selectedContact ? (
          <>
            {/* 顶部：客户信息 */}
            <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3 dark:border-slate-700">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-indigo-400 to-blue-500 text-sm font-medium text-white">
                  {(selectedContact.customerName || '?').charAt(0)}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-900 dark:text-slate-100">
                      {selectedContact.customerName}
                    </span>
                    {/* 阶段标签 */}
                    <span className={clsx('rounded px-1.5 py-0.5 text-[10px] font-medium', STAGE_COLORS.connected)}>
                      {getStageLabel('connected')}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    {selectedContact.channelTypes.map((ch) => {
                      const config = CHANNEL_LABEL[ch];
                      return (
                        <span key={ch} className="flex items-center gap-0.5 text-[10px] text-gray-400 dark:text-slate-500">
                          <ChannelLogo type={ch} size={12} />
                          {config ?? ch}
                        </span>
                      );
                    })}
                  </div>
                </div>
              </div>
              {/* AI 助手开关 */}
              <button
                onClick={() => setAiSidebarOpen(!aiSidebarOpen)}
                aria-label={aiSidebarOpen ? '关闭 AI 助手' : '打开 AI 助手'}
                className={clsx(
                  'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
                  aiSidebarOpen
                    ? 'bg-blue-50 text-blue-600 hover:bg-blue-100 dark:bg-blue-500/20 dark:text-blue-300 dark:hover:bg-blue-500/30'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200 dark:bg-slate-700 dark:text-slate-400 dark:hover:bg-slate-600'
                )}
              >
                <Sparkles className="h-3.5 w-3.5" />
                AI 助手
              </button>
            </div>

            {/* 消息列表 */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {selectedContact.messages.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center text-gray-400 dark:text-slate-500">
                  <MessageCircle className="mb-2 h-10 w-10" />
                  <span className="text-sm">暂无消息</span>
                </div>
              ) : (
                <div className="space-y-4">
                  {selectedContact.messages.map((msg) => {
                    const isInbound = msg.direction === 'inbound';
                    return (
                      <div
                        key={msg.id}
                        className={clsx('flex', isInbound ? 'justify-start' : 'justify-end')}
                      >
                        {/* 入站消息：左侧头像 */}
                        {isInbound && (
                          <div className="mr-2 mt-1 shrink-0">
                            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-200 text-xs font-medium text-gray-600 dark:bg-slate-700 dark:text-slate-200">
                              {(selectedContact.customerName || '?').charAt(0)}
                            </div>
                          </div>
                        )}

                        <div className={clsx('max-w-[65%]')}>
                          {/* 消息气泡 */}
                          <div
                            className={clsx(
                              'rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
                              isInbound
                                ? 'rounded-tl-sm bg-gray-100 text-gray-800 dark:bg-slate-700 dark:text-slate-100'
                                : 'rounded-tr-sm bg-blue-500 text-white'
                            )}
                          >
                            {msg.content}
                          </div>

                          {/* 底部：渠道图标 + AI 意图标签 + 时间 */}
                          <div
                            className={clsx(
                              'mt-1 flex items-center gap-2',
                              isInbound ? 'justify-start' : 'justify-end'
                            )}
                          >
                            <ChannelLogo type={msg.channel_type} size={12} />
                            {msg.ai_intent && (
                              <span
                                className={clsx(
                                  'rounded px-1.5 py-0.5 text-[10px] font-medium',
                                  INTENT_STYLES[msg.ai_intent] ?? 'bg-gray-100 text-gray-500 dark:bg-slate-700 dark:text-slate-300'
                                )}
                              >
                                {msg.ai_intent}
                              </span>
                            )}
                            <span className="text-[10px] text-gray-400 dark:text-slate-500">
                              {formatTime(msg.created_at)}
                            </span>
                          </div>
                        </div>

                        {/* 出站消息：右侧头像 */}
                        {!isInbound && (
                          <div className="ml-2 mt-1 shrink-0">
                            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-500 text-xs font-medium text-white">
                              我
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                  <div ref={messagesEndRef} />
                </div>
              )}
            </div>

            {/* 底部输入区 */}
            <div className="border-t border-gray-200 bg-white px-5 py-3 dark:border-slate-700 dark:bg-slate-800">
              {/* 推荐话术浮层 */}
              {showQuickReplies && aiSuggestions.length > 0 && (
                <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50/50 p-3 dark:border-blue-500/30 dark:bg-blue-500/10">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="flex items-center gap-1.5 text-xs font-medium text-blue-600 dark:text-blue-300">
                      <Sparkles className="h-3.5 w-3.5" />
                      AI 推荐话术
                    </div>
                    <button onClick={() => setShowQuickReplies(false)} aria-label="关闭推荐话术" className="text-gray-400 hover:text-gray-600 dark:text-slate-500 dark:hover:text-slate-300">
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="space-y-1.5">
                    {aiSuggestions.map((s, i) => (
                      <button
                        key={i}
                        onClick={() => handleFillSuggestion(s)}
                        className="block w-full rounded-md bg-white px-3 py-2 text-left text-xs text-gray-700 shadow-sm transition-colors hover:bg-blue-50 hover:text-blue-700 dark:bg-slate-700 dark:text-slate-200 dark:shadow-none dark:hover:bg-blue-500/20 dark:hover:text-blue-300"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex items-end gap-3">
                {/* 渠道选择 */}
                <select
                  value={selectedChannel}
                  onChange={(e) => setSelectedChannel(e.target.value)}
                  className="shrink-0 rounded-lg border border-gray-200 bg-gray-50 px-2 py-2 text-xs text-gray-700 outline-none focus:border-blue-400 dark:border-slate-700 dark:bg-slate-700 dark:text-slate-200"
                  aria-label="选择发送渠道"
                >
                  {channelsRaw.length > 0
                    ? channelsRaw.filter((ch) => ch.type !== 'douyin' && ch.type !== 'web' && ch.type !== 'miniprogram').map((ch) => (
                        <option key={ch.id} value={ch.type}>{CHANNEL_LABEL[ch.type] ?? ch.name}</option>
                      ))
                    : (
                        <>
                          <option value="wework">企微</option>
                          <option value="sms">短信</option>
                          <option value="email">邮件</option>
                        </>
                      )}
                </select>

                {/* 消息输入框 */}
                <div className="flex-1">
                  <textarea
                    ref={textareaRef}
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="输入消息，Enter 发送，Shift+Enter 换行..."
                    aria-label="消息输入框"
                    rows={2}
                    className="w-full resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none placeholder:text-gray-400 focus:border-blue-400 dark:border-slate-700 dark:bg-slate-700 dark:text-slate-200 dark:placeholder:text-slate-500"
                  />
                </div>

                {/* 操作按钮 */}
                <div className="flex shrink-0 flex-col gap-1.5">
                  {/* AI 推荐按钮（新手教程锚点） */}
                  <button
                    onClick={handleQuickSuggest}
                    disabled={aiLoading || !selectedContact}
                    aria-label="AI 推荐回复"
                    data-tour="messages-ai-suggest"
                    className={clsx(
                      'flex items-center gap-1 rounded-lg px-3 py-2 text-xs font-medium transition-colors',
                      aiLoading
                        ? 'cursor-wait bg-gray-100 text-gray-400 dark:bg-slate-700 dark:text-slate-500'
                        : 'bg-amber-50 text-amber-600 hover:bg-amber-100 dark:bg-amber-500/20 dark:text-amber-300 dark:hover:bg-amber-500/30'
                    )}
                  >
                    {aiLoading ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" />
                    )}
                    AI 推荐
                  </button>

                  {/* 发送按钮 */}
                  <button
                    onClick={handleSend}
                    disabled={sending || !inputText.trim()}
                    aria-label="发送消息"
                    className={clsx(
                      'flex items-center gap-1 rounded-lg px-3 py-2 text-xs font-medium transition-colors',
                      sending || !inputText.trim()
                        ? 'cursor-not-allowed bg-gray-100 text-gray-400 dark:bg-slate-700 dark:text-slate-500'
                        : 'bg-blue-500 text-white hover:bg-blue-600'
                    )}
                  >
                    {sending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Send className="h-3.5 w-3.5" />
                    )}
                    发送
                  </button>
                </div>
              </div>
            </div>
          </>
        ) : (
          /* 空状态：未选择联系人 */
          <div className="flex h-full flex-col items-center justify-center text-gray-400 dark:text-slate-500">
            <div className="mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-gray-100 dark:bg-slate-700">
              <MessageCircle className="h-8 w-8" />
            </div>
            <p className="text-sm font-medium text-gray-500 dark:text-slate-400">选择一个对话开始</p>
            <p className="mt-1 text-xs text-gray-400 dark:text-slate-500">从左侧联系人列表中选择</p>
          </div>
        )}
      </div>

      {/* ===== 右栏：AI 助手侧边栏 ===== */}
      {aiSidebarOpen && selectedContact && (
        <div className="flex w-[300px] shrink-0 flex-col border-l border-gray-200 bg-gray-50/50 dark:border-slate-700 dark:bg-slate-800/50">
          {/* 标题栏 */}
          <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-slate-700">
            <div className="flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-slate-200">
              <Bot className="h-4 w-4 text-blue-500" />
              AI 助手
            </div>
            <button
              onClick={() => setAiSidebarOpen(false)}
              aria-label="关闭 AI 助手侧栏"
              className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-200 hover:text-gray-600 dark:text-slate-500 dark:hover:bg-slate-700 dark:hover:text-slate-300"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
            {/* 客户画像摘要 */}
            <div className="rounded-lg bg-white p-3 shadow-sm dark:bg-slate-800 dark:shadow-none">
              <h4 className="mb-2 text-xs font-semibold text-gray-500 dark:text-slate-400">客户画像</h4>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-indigo-400 to-blue-500 text-xs font-medium text-white">
                    {(selectedContact.customerName || '?').charAt(0)}
                  </div>
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-slate-100">{selectedContact.customerName}</p>
                    <p className="text-[10px] text-gray-400 dark:text-slate-500">ID: {selectedContact.customerId}</p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1">
                  {selectedContact.channelTypes.map((ch) => {
                    const config = CHANNEL_LABEL[ch];
                    return (
                      <span
                        key={ch}
                        className="flex items-center gap-0.5 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600 dark:bg-slate-700 dark:text-slate-300"
                      >
                        <ChannelLogo type={ch} size={10} />
                        {config ?? ch}
                      </span>
                    );
                  })}
                </div>
                <div className="text-xs text-gray-500 dark:text-slate-400">
                  共 {selectedContact.messages.length} 条消息
                </div>
              </div>
            </div>

            {/* 推荐话术卡片 */}
            <div className="rounded-lg bg-white p-3 shadow-sm dark:bg-slate-800 dark:shadow-none">
              <div className="mb-2 flex items-center justify-between">
                <h4 className="text-xs font-semibold text-gray-500 dark:text-slate-400">推荐话术</h4>
                <button
                  onClick={handleAiSuggest}
                  disabled={aiLoading}
                  aria-label="刷新推荐话术"
                  className="flex items-center gap-1 text-[10px] font-medium text-blue-500 hover:text-blue-600 disabled:text-gray-400 dark:text-blue-400 dark:hover:text-blue-300 dark:disabled:text-slate-500"
                >
                  {aiLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
                  刷新
                </button>
              </div>
              {aiSuggestions.length > 0 ? (
                <div className="space-y-2">
                  {aiSuggestions.map((s, i) => (
                    <button
                      key={i}
                      onClick={() => handleFillSuggestion(s)}
                      aria-label={`使用推荐话术：${s.slice(0, 10)}`}
                      data-suggestion-fill={i}
                      data-tour="messages-suggestion-fill"
                      className="block w-full rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-left text-xs text-blue-700 transition-colors hover:bg-blue-100 dark:border-blue-500/40 dark:bg-blue-500/10 dark:text-blue-300 dark:hover:bg-blue-500/20"
                    >
                      <span className="mr-1 font-medium text-blue-500 dark:text-blue-400">#{i + 1}</span>
                      {s}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="py-4 text-center text-xs text-gray-400 dark:text-slate-500">
                  <button
                    onClick={handleAiSuggest}
                    disabled={aiLoading}
                    className="mx-auto flex items-center gap-1 text-blue-500 hover:text-blue-600 dark:text-blue-400"
                  >
                    {aiLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                    点击生成推荐话术
                  </button>
                </div>
              )}
            </div>

            {/* 跟进建议 */}
            <div className="rounded-lg bg-white p-3 shadow-sm dark:bg-slate-800 dark:shadow-none">
              <h4 className="mb-2 text-xs font-semibold text-gray-500 dark:text-slate-400">跟进建议</h4>
              <div className="space-y-2">
                {generateFollowUpSuggestions(selectedContact).map((suggestion, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <div className={clsx(
                      'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[8px] font-bold',
                      suggestion.type === 'urgent' ? 'bg-red-100 text-red-600 dark:bg-red-500/20 dark:text-red-300'
                        : suggestion.type === 'info' ? 'bg-blue-100 text-blue-600 dark:bg-blue-500/20 dark:text-blue-300'
                        : 'bg-green-100 text-green-600 dark:bg-green-500/20 dark:text-green-300'
                    )}>
                      {i + 1}
                    </div>
                    <p className="text-xs text-gray-600 dark:text-slate-300">{suggestion.text}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <ScriptHintToast
        hint={scriptHint}
        onDismiss={() => setScriptHint(null)}
        onUse={(text) => {
          setInputText(text);
          setScriptHint(null);
        }}
      />
    </div>
  );
}
