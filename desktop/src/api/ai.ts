import api, { request } from './client';

/** 分析客户意图 */
export const analyzeIntent = (message: string, context = '') =>
  api.post('/api/kellai/ai/intent', { message, context });

/** 推荐话术 */
export const suggestReply = (customerId: number, message: string, intent = '', stage = '') =>
  api.post('/api/kellai/ai/suggest-reply', { customer_id: customerId, message, intent, stage });

/** 生成自动回复草稿 */
export const generateAutoReply = (customerId: number, message: string, intent = '', stage = '') =>
  api.post('/api/kellai/ai/auto-reply', { customer_id: customerId, message, intent, stage });

/** 获取客户画像 */
export const getCustomerProfile = (customerId: number) =>
  api.get(`/api/kellai/ai/profile/${customerId}`);

export interface KnowledgeArticle {
  id: string;
  title: string;
  content: string;
  tags?: string[];
  source?: string;
  updated_at?: string;
}

export interface KnowledgeSuggestion {
  answer: string;
  matched: boolean;
  sources: Array<{ id: string; title: string; score: number }>;
  confidence: number;
}

export const listKnowledgeArticles = async (): Promise<KnowledgeArticle[]> => {
  const body = await request<{ articles: KnowledgeArticle[] }>('get', '/api/kellai/ai/knowledge-base');
  return Array.isArray(body?.articles) ? body.articles : [];
};

export const saveKnowledgeArticle = (article: Partial<KnowledgeArticle> & { title: string; content: string }) =>
  request<KnowledgeArticle>('post', '/api/kellai/ai/knowledge-base', article);

export const suggestKnowledgeAnswer = (query: string, customerId?: number | null, limit = 3) =>
  request<KnowledgeSuggestion>('post', '/api/kellai/ai/knowledge-base/suggest', {
    query,
    customer_id: customerId || undefined,
    limit,
  });

/** 跟进提醒单条结构（与后端 get_follow_up_reminders 对齐） */
export interface FollowUpReminder {
  customer_id: number;
  display_name: string;
  stage: string;
  hours_since_last_contact: number;
  suggested_action: string;
}

/**
 * 获取跟进提醒列表
 * 后端响应: { success: true, data: { reminders: FollowUpReminder[] } }
 * 这里用 request<T> 自动解包到 data 字段，再取 reminders
 */
export const getReminders = async (hours = 48, limit = 20): Promise<FollowUpReminder[]> => {
  const body = await request<{ reminders: FollowUpReminder[] }>(
    'get',
    '/api/kellai/ai/reminders',
    { hours, limit }
  );
  return Array.isArray(body?.reminders) ? body.reminders : [];
};

/** 更新 AI 评分 */
export const updateAiScore = (customerId: number) =>
  api.post(`/api/kellai/ai/score/${customerId}`);
