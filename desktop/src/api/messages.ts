import api from './client';

/** 消息未读汇总响应 */
export interface UnreadSummary {
  total: number;
  by_customer: Record<string, number>;
  team_id?: number | null;
}

/** 获取消息列表 */
export const getMessages = (params: { customer_id?: number; channel_type?: string; limit?: number; since?: string }) =>
  api.get('/api/kellai/messages', { params });

/** 发送消息 */
export const sendMessage = (customerId: number, channelType: string, contactId: string, content: string) =>
  api.post('/api/kellai/messages/send', { customer_id: customerId, channel_type: channelType, contact_id: contactId, content });

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
