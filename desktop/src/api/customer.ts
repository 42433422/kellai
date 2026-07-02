import api, { request } from './client';
import type {
  CustomerListResponse,
  CustomerProfileInput,
  CustomerQueryParams,
  CustomerBatchInput,
  CustomerPipeline,
} from '../types';

/** 获取客户 Pipeline 信息 */
export const getCustomerPipeline = (customerId: number) =>
  api.get(`/api/kellai/pipeline`, { params: { customer_id: customerId, auto_advance: true } });

/** 获取客户 CRM 数据 */
export const getCustomerCrm = (customerId: number) =>
  api.get(`/api/kellai/crm`, { params: { customer_id: customerId } });

/** 获取客户消息列表 */
export const getCustomerMessages = async (customerId: number, limit = 50) => {
  await api.post('/api/kellai/channels/sync-inbox', { limit }, { skipErrorToast: true }).catch(() => undefined);
  return api.get(`/api/kellai/messages`, { params: { customer_id: customerId, limit }, skipErrorToast: true });
};

/** 获取客户 AI 画像 */
export const getCustomerAiProfile = (customerId: number) =>
  api.get(`/api/kellai/ai/profile/${customerId}`, { skipErrorToast: true });

/** 获取客户跨渠道运营洞察 */
export const getCustomerOperatingInsight = (customerId: number) =>
  api.get(`/api/kellai/ai/operating-insight/${customerId}`, { skipErrorToast: true });

/** 获取客户客服质检报告 */
export const getCustomerQualityInspection = (customerId: number) =>
  api.get(`/api/kellai/ai/quality-inspection/${customerId}`, { skipErrorToast: true });

/** 获取客户转人工/主管工单 */
export const getCustomerServiceTickets = (customerId: number) =>
  api.get(`/api/kellai/ai/service-tickets/${customerId}`, { skipErrorToast: true });

/** 从质检或手动创建客户工单 */
export const createCustomerServiceTicket = (
  customerId: number,
  body: Partial<{ title: string; reason: string; assignee: string; priority: string; source: string; sla_minutes: number; from_quality: boolean }> = {},
) =>
  api.post('/api/kellai/ai/service-tickets', { customer_id: customerId, from_quality: true, ...body });

/** 指派客户工单 */
export const assignCustomerServiceTicket = (ticketId: string, assignee: string) =>
  api.post(`/api/kellai/ai/service-tickets/${ticketId}/assign`, { assignee, actor: 'desktop' });

/** 解决客户工单并回托 AI */
export const resolveCustomerServiceTicket = (ticketId: string, resolution: string) =>
  api.post(`/api/kellai/ai/service-tickets/${ticketId}/resolve`, {
    resolution,
    actor: 'desktop',
    rehost_to_ai: true,
  });

/** 获取客户服务自学习结果 */
export const getCustomerServiceLearning = (customerId: number) =>
  api.get(`/api/kellai/ai/service-learning/${customerId}`, { skipErrorToast: true });

/** 将质检/工单处理结果沉淀为知识和优化指标 */
export const runCustomerServiceLearning = (customerId: number) =>
  api.post(`/api/kellai/ai/service-learning/${customerId}`, { persist: true }, { skipErrorToast: true });

/** 获取客户 AI 自助解决记录 */
export const getCustomerSelfService = (customerId: number) =>
  api.get(`/api/kellai/ai/self-service/${customerId}`, { skipErrorToast: true });

/** 获取坐席助手自动填单、知识推荐和风险提醒 */
export const getCustomerAgentAssist = (customerId: number) =>
  api.get(`/api/kellai/ai/agent-assist/${customerId}`, { skipErrorToast: true });

/** 执行坐席助手：生成并可应用自动填单结果 */
export const runCustomerAgentAssist = (
  customerId: number,
  body: Partial<{ persist: boolean; actor: string }> = {},
) =>
  api.post(`/api/kellai/ai/agent-assist/${customerId}`, {
    persist: true,
    actor: 'desktop',
    ...body,
  }, { skipErrorToast: true });

/** 执行 AI 自助解决：命中知识库自动回复，未命中转人工工单 */
export const runCustomerSelfService = (
  customerId: number,
  body: Partial<{ query: string; channel_type: string; fallback_to_ticket: boolean }> = {},
) =>
  api.post(`/api/kellai/ai/self-service/${customerId}`, {
    query: '',
    channel_type: '',
    fallback_to_ticket: true,
    ...body,
  });

/** 获取客户 AI 外呼任务 */
export const getCustomerOutboundCalls = (customerId: number) =>
  api.get(`/api/kellai/ai/outbound-calls/${customerId}`, { skipErrorToast: true });

/** 生成客户 AI 外呼任务 */
export const planCustomerOutboundCall = (
  customerId: number,
  body: Partial<{ purpose: string; assignee: string }> = {},
) =>
  api.post('/api/kellai/ai/outbound-calls', {
    customer_id: customerId,
    purpose: 'follow_up',
    assignee: 'AI外呼助手',
    ...body,
  });

/** 执行本地模拟外呼并推进漏斗 */
export const executeCustomerOutboundCall = (
  callId: string,
  body: Partial<{ outcome: string; note: string; actor: string }> = {},
) =>
  api.post(`/api/kellai/ai/outbound-calls/${callId}/execute`, {
    outcome: 'demo_booked',
    note: '',
    actor: 'desktop',
    ...body,
  });

/** 发送消息 */
export const sendMessage = (customerId: number, channelType: string, contactId: string, content: string) =>
  api.post('/api/kellai/messages/send', { customer_id: customerId, channel_type: channelType, contact_id: contactId, content });

/** AI 推荐回复 */
export const suggestReply = (customerId: number, message: string, intent = '', stage = '') =>
  api.post('/api/kellai/ai/suggest-reply', { customer_id: customerId, message, intent, stage });

/** 更新 Pipeline 阶段 */
export const updatePipelineStage = (customerId: number, stage: string, note = '') =>
  api.post('/api/kellai/pipeline/stage', { customer_id: customerId, stage, note });

/* ===== 客户管理（列表 + CRUD + 批量），返回已解包的数据 ===== */

/** 获取客户列表（支持搜索 / 多维筛选） */
export const getCustomers = (params: CustomerQueryParams = {}) =>
  request<CustomerListResponse>('get', '/api/kellai/customers', params);

/** 新建客户 */
export const createCustomer = (body: CustomerProfileInput) =>
  request<{ customer_id: number; pipeline: CustomerPipeline }>('post', '/api/kellai/customers', body);

/** 更新客户资料（含可选阶段变更） */
export const updateCustomer = (customerId: number, body: CustomerProfileInput) =>
  request<{ customer_id: number; pipeline: CustomerPipeline }>('put', `/api/kellai/customers/${customerId}`, body);

/** 删除客户 */
export const deleteCustomer = (customerId: number) =>
  request<{ customer_id: number; deleted: boolean }>('delete', `/api/kellai/customers/${customerId}`);

/** 客户批量操作（删除 / 改阶段 / 增删标签） */
export const batchCustomers = (body: CustomerBatchInput) =>
  request<{ affected: number; action: string }>('post', '/api/kellai/customers/batch', body);
