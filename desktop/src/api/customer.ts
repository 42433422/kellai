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
export const getCustomerMessages = (customerId: number, limit = 50) =>
  api.get(`/api/kellai/messages`, { params: { customer_id: customerId, limit }, skipErrorToast: true });

/** 获取客户 AI 画像 */
export const getCustomerAiProfile = (customerId: number) =>
  api.get(`/api/kellai/ai/profile/${customerId}`, { skipErrorToast: true });

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
