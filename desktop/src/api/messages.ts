import api from './client';
import { invoke } from '@tauri-apps/api/core';

/** 消息未读汇总响应 */
export interface UnreadSummary {
  total: number;
  by_customer: Record<string, number>;
  team_id?: number | null;
}

export interface AutoReplyJob {
  inbound_message_id: string;
  customer_id: number;
  channel_type: string;
  contact_id: string;
  contact_name: string;
  inbound_content: string;
  reply_content: string;
  policy_reason?: string;
  attempt?: number;
}

export interface AutoReplyRuntimeStatus {
  enabled: boolean;
  stages: string[];
  counts: Record<string, number>;
  latest?: {
    contact_name?: string;
    channel_type?: string;
    status?: string;
    last_error?: string;
    updated_at?: string;
    sent_at?: string;
    policy_reason?: string;
  };
}

/** 获取消息列表 */
export const getMessages = async (params: { customer_id?: number; channel_type?: string; limit?: number; since?: string }) => {
  await syncInboxMessages(params.channel_type).catch(() => undefined);
  return api.get('/api/kellai/messages', { params });
};

/** 同步渠道收件箱到消息/客户/漏斗闭环 */
export const syncInboxMessages = (channelType = '', limit = 50) =>
  api.post(
    '/api/kellai/channels/sync-inbox',
    { channel_type: channelType, limit },
    { skipErrorToast: true, skipLoading: true },
  );

/** 发送消息 */
export const sendMessage = async (
  customerId: number,
  channelType: string,
  contactId: string,
  content: string,
  contactName = '',
  options?: { autoReplyInboundId?: string },
) => {
  let desktopResult: Record<string, unknown> | undefined;
  const isTauriRuntime =
    typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
  if (channelType === 'douyin' && isTauriRuntime) {
    try {
      desktopResult = await invoke<Record<string, unknown>>('douyin_desktop_send', {
        contactName,
        contactId,
        content,
      });
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason || '抖音桌面发送失败');
      if (message.includes('辅助功能权限')) {
        await invoke('open_accessibility_settings').catch(() => undefined);
      }
      const error = new Error(message);
      error.name = 'MessageSendError';
      throw error;
    }
  }
  const response = await api.post(
    '/api/kellai/messages/send',
    {
      customer_id: customerId,
      channel_type: channelType,
      contact_id: contactId,
      content,
      ...(options?.autoReplyInboundId
        ? { auto_reply_inbound_id: options.autoReplyInboundId }
        : {}),
      ...(desktopResult ? { desktop_result: desktopResult } : {}),
    },
    {
      timeout: 45_000,
      ...(desktopResult ? { headers: { 'X-Kellai-Desktop-Delivery': '1' } } : {}),
    },
  );
  const payload = response.data as {
    success?: boolean;
    error?: string;
    message?: string;
    data?: unknown;
  };
  if (payload?.success === false) {
    const error = new Error(payload.error || payload.message || '渠道发送失败');
    error.name = 'MessageSendError';
    throw error;
  }
  return payload?.data ?? payload;
};

/** 领取需要由已签名桌面端真实发送的自动回复任务 */
export const claimAutoReplyJobs = (limit = 3) =>
  api.post('/api/kellai/ai/auto-reply/jobs/claim', { limit });

/** 回报自动回复发送结果（成功发送也会由统一发送接口幂等落账） */
export const reportAutoReplyResult = (payload: {
  inbound_message_id: string;
  success: boolean;
  error?: string;
  outbound_message_id?: string;
}) => api.post('/api/kellai/ai/auto-reply/jobs/result', payload);

/** 自动回复真实运行状态 */
export const getAutoReplyRuntimeStatus = () =>
  api.get('/api/kellai/ai/auto-reply/runtime-status');

/** AI 推荐回复 */
export const suggestReply = (customerId: number, message: string) =>
  api.post('/api/kellai/ai/suggest-reply', { customer_id: customerId, message });

/** 获取渠道列表 */
export const getChannels = () =>
  api.get('/api/kellai/channels');

/** 获取未读消息汇总（不传 customer_id 走团队级；带则单客户） */
export const getUnreadSummary = async (customerId?: number): Promise<UnreadSummary> => {
  const res = await api.get('/api/kellai/messages/unread-count', {
    params: customerId !== undefined ? { customer_id: customerId } : {},
  });
  const body = res.data as { success?: boolean; data?: UnreadSummary } | UnreadSummary;
  if (body && typeof body === 'object' && 'data' in body && body.data) {
    return body.data;
  }
  return (body as UnreadSummary) ?? { total: 0, by_customer: {} };
};

/** 标记消息已读 */
export const markMessagesRead = async (params: {
  messageIds?: string[];
  customerId?: number;
  all?: boolean;
}): Promise<{ updated: number }> => {
  const body: Record<string, unknown> = {};
  if (params.messageIds && params.messageIds.length > 0) body.message_ids = params.messageIds;
  if (params.customerId !== undefined) body.customer_id = params.customerId;
  if (params.all) body.all = true;
  const res = await api.post('/api/kellai/messages/mark-read', body);
  const data = (res.data as { success?: boolean; data?: { updated: number } } | { updated: number });
  if (data && typeof data === 'object' && 'data' in data && data.data) {
    return data.data;
  }
  return (data as { updated: number }) ?? { updated: 0 };
};
