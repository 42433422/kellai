import api from './client';

/** 获取漏斗看板数据 */
export const getFunnelData = (maxClients = 50) =>
  api.get('/api/kellai/pipeline/funnel', { params: { max_clients_per_stage: maxClients } });

/** 更新客户阶段 */
export const updatePipelineStage = (customerId: number, stage: string, note = '') =>
  api.post('/api/kellai/pipeline/stage', { customer_id: customerId, stage, note });

/** 查询 pipeline 列表 */
export const queryPipelines = (params: { stage?: string; channel?: string; min_ai_score?: number; limit?: number }) =>
  api.get('/api/kellai/pipeline/query', { params });
