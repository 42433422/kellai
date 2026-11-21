import api, { currentAccountKey } from './client';
import { invoke } from '@tauri-apps/api/core';
import { clearPendingDelivery, readPendingDelivery } from './deliveryState';

/** 消息未读汇总响应 */
export interface UnreadSummary {
  total: number;
  by_customer: Record<string, number>;
  team_id?: number | null;
}

export interface AutoReplyJob {
  inbound_message_id: string;
  lease_token: string;
  delivery_key: string;
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
export const syncInboxMessages = (channelType = '', limit = 50, accountKey = currentAccountKey()) =>
  api.post(
    '/api/kellai/channels/sync-inbox',
    { channel_type: channelType, limit },
    { expectedAccount: accountKey, skipErrorToast: true, skipLoading: true },
  );

export interface DeliveryReceipt {
  request_id: string;
  message_id: string;
  provider_message_id?: string;
  status: 'sending' | 'unknown' | 'accepted' | 'failed';
  provider_state?: string;
  success?: boolean;
  persisted: boolean;
  error?: string;
  dispatch_allowed?: boolean;
  delivery_token?: string;
}

export class MessageSendError extends Error {
  name = 'MessageSendError';
  constructor(message: string, public receipt?: DeliveryReceipt) { super(message); }
}

export const deliveryLabel = (receipt: DeliveryReceipt) => {
  if (receipt.status === 'accepted') {
    if (receipt.provider_state === 'read') return '渠道回执：已读';
    if (receipt.provider_state === 'delivered') return '渠道回执：已送达';
    if (receipt.provider_state === 'sent') return '渠道回执：已发送，送达待确认';
    if (receipt.provider_state === 'failed') return '渠道回执：发送失败';
    return '渠道已受理，送达待确认';
  }
  if (receipt.status === 'failed') return '发送失败，请查看失败原因';
  return '发送结果待确认，请查询原请求回执';
};

export const getDeliveryReceipt = async (requestId: string, accountKey = currentAccountKey()): Promise<DeliveryReceipt> => {
  const response = await api.get(`/api/kellai/messages/requests/${encodeURIComponent(requestId)}`,
    { expectedAccount: accountKey, skipErrorToast: true, skipLoading: true });
  return response.data.data;
};

// Only request IDs and hashes survive a refresh. No message text, credentials
// or single-use native execution tokens are written to browser storage.
const nativeCompletions = new Map<string, Record<string, unknown>>();

/** Restore a known native result after an interrupted HTTP response or login switch.
 * This submits only the original receipt; it never executes a native send.
 */
export const flushNativeCompletions = async (accountKey = currentAccountKey()): Promise<void> => {
  if (!accountKey || currentAccountKey() !== accountKey) return;
  for (const [nativeKey, body] of nativeCompletions) {
    if (!nativeKey.startsWith(`${accountKey}:`)) continue;
    if (currentAccountKey() !== accountKey) return;
    try {
      const response = await api.post('/api/kellai/messages/send', body, {
        expectedAccount: accountKey, timeout: 45_000, skipErrorToast: true, skipLoading: true,
        headers: { 'X-Kellai-Desktop-Delivery': '1' },
      });
      const receipt = response.data.data as DeliveryReceipt;
      if (receipt.request_id !== body.client_request_id || receipt.status === 'sending') continue;
      // The ledger now owns this result, including an explicit unknown result.
      nativeCompletions.delete(nativeKey);
      if (receipt.status === 'failed' || (receipt.status === 'accepted' && receipt.persisted)) {
        const storageKey = `kellai:delivery:${accountKey}:${body.customer_id}:${body.channel_type}:${body.contact_id}`;
        clearPendingDelivery(localStorage, storageKey, receipt.request_id);
      }
    } catch { /* Keep the original in-memory receipt for this account's next poll. */ }
  }
};

/** Reserve a stable request before either HTTP or native execution. */
export const sendMessage = async (
  customerId: number,
  channelType: string,
  contactId: string,
  content: string,
  contactName = '',
  options?: { autoReplyInboundId?: string; leaseToken?: string; clientRequestId?: string; expectedAccount?: string },
): Promise<DeliveryReceipt> => {
  const accountKey = options?.expectedAccount || currentAccountKey();
  if (!accountKey) throw new MessageSendError('请先登录');
  if (currentAccountKey() !== accountKey) throw new MessageSendError('账号已切换，旧账号操作已停止');
  const storageKey = `kellai:delivery:${accountKey}:${customerId}:${channelType}:${contactId}`;
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(content))))
    .map((b) => b.toString(16).padStart(2, '0')).join('');
  let requestId = options?.clientRequestId || '';
  if (!requestId) {
    const previous = readPendingDelivery(localStorage, storageKey);
    if (previous?.requestId && previous.hash !== hash) {
      const old = await getDeliveryReceipt(previous.requestId, accountKey).catch(() => null);
      if (!old || !['accepted', 'failed'].includes(old.status) || (old.status === 'accepted' && !old.persisted)) {
        throw new MessageSendError('该联系人上一条发送尚未确认，请保留原内容并查询回执', old || undefined);
      }
      if (!clearPendingDelivery(localStorage, storageKey, previous.requestId)) {
        throw new MessageSendError('本地发送记录已变化，请先查询当前请求回执');
      }
    } else if (previous?.requestId) {
      requestId = previous.requestId;
    }
    requestId ||= crypto.randomUUID();
    localStorage.setItem(storageKey, JSON.stringify({ requestId, hash }));
  }
  const body: Record<string, unknown> = {
    customer_id: customerId, channel_type: channelType, contact_id: contactId, content,
    client_request_id: requestId,
    ...(options?.autoReplyInboundId ? { auto_reply_inbound_id: options.autoReplyInboundId,
      auto_reply_lease_token: options.leaseToken || '' } : {}),
  };
  const config = { timeout: 45_000, expectedAccount: accountKey, skipErrorToast: true,
    skipLoading: Boolean(options?.autoReplyInboundId) };
  const nativeKey = `${accountKey}:${requestId}`;
  const finish = (receipt: DeliveryReceipt): DeliveryReceipt => {
    if (receipt.status === 'accepted' && receipt.persisted) {
      if (!options?.clientRequestId) clearPendingDelivery(localStorage, storageKey, requestId);
      nativeCompletions.delete(nativeKey);
      return receipt;
    }
    if (receipt.status === 'failed' && !options?.clientRequestId) clearPendingDelivery(localStorage, storageKey, requestId);
    throw new MessageSendError(receipt.error || (receipt.status === 'accepted'
      ? '渠道已受理，本地记录正在恢复，请查询原请求回执' : deliveryLabel(receipt)), receipt);
  };
  try {
    const isNative = channelType === 'douyin' && typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
    if (isNative) {
      const nativeConfig = { ...config, headers: { 'X-Kellai-Desktop-Delivery': '1' } };
      let completedBody = nativeCompletions.get(nativeKey);
      if (!completedBody) {
        const prepared = await api.post('/api/kellai/messages/prepare', body, nativeConfig);
        const reservation = prepared.data.data as DeliveryReceipt;
        if (!reservation.dispatch_allowed) return finish(reservation);
        if (currentAccountKey() !== accountKey) throw new MessageSendError('账号已切换，本次桌面发送已停止');
        let result: Record<string, unknown>;
        try {
          result = await invoke<Record<string, unknown>>('douyin_desktop_send', { contactName, contactId, content });
        } catch (reason) {
          result = { success: false, source: 'douyin_desktop_automation', contact_id: contactId,
            delivery_state: 'unknown', error: reason instanceof Error ? reason.message : '桌面执行结果未知' };
        }
        completedBody = { ...body, delivery_token: reservation.delivery_token, desktop_result: result };
        nativeCompletions.set(nativeKey, completedBody);
      }
      const response = await api.post('/api/kellai/messages/send', completedBody, nativeConfig);
      return finish(response.data.data as DeliveryReceipt);
    }
    const response = await api.post('/api/kellai/messages/send', body, config);
    return finish(response.data.data as DeliveryReceipt);
  } catch (reason: any) {
    if (reason instanceof MessageSendError) throw reason;
    if (currentAccountKey() !== accountKey) throw new MessageSendError('账号已切换，请回到原账号查询发送回执');
    const receipt = await getDeliveryReceipt(requestId, accountKey).catch(() => null);
    if (receipt) return finish(receipt);
    const status = reason?.response?.status;
    if ([400, 401, 403, 404, 422].includes(status) && !options?.clientRequestId) clearPendingDelivery(localStorage, storageKey, requestId);
    throw new MessageSendError(reason?.response?.data?.error || '发送结果未确认。再次提交将沿用原请求，避免重复发送',
      { request_id: requestId, message_id: '', status: 'unknown', persisted: false });
  }
};

/** 领取需要由已签名桌面端真实发送的自动回复任务 */
export const claimAutoReplyJobs = (limit = 3, accountKey = currentAccountKey()) =>
  api.post('/api/kellai/ai/auto-reply/jobs/claim', { limit }, { expectedAccount: accountKey });

/** 回报自动回复发送结果（成功发送也会由统一发送接口幂等落账） */
export const reportAutoReplyResult = (payload: {
  inbound_message_id: string;
  lease_token: string;
  delivery_key: string;
  success: boolean;
  error?: string;
  outbound_message_id?: string;
}, accountKey = currentAccountKey()) => api.post('/api/kellai/ai/auto-reply/jobs/result', payload,
  { expectedAccount: accountKey, skipErrorToast: true, skipLoading: true });

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
