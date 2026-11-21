import { request } from './client';
import type { FlowDefinition, FlowTemplate, FlowExecution, Anomaly, Webhook } from '../types';

export const createFlow = (name: string, nodes: FlowDefinition['nodes'], edges: FlowDefinition['edges']) =>
  request<FlowDefinition>('post', '/api/kellai/flow/create', { name, nodes, edges });

export const updateFlow = (id: string, data: Partial<Pick<FlowDefinition, 'name' | 'nodes' | 'edges'>>) =>
  request<FlowDefinition>('put', '/api/kellai/flow/update', { id, ...data });

export const listFlows = () =>
  request<FlowDefinition[]>('get', '/api/kellai/flow/list');

export const getFlow = (id: string) =>
  request<FlowDefinition>('get', '/api/kellai/flow/definitions/' + encodeURIComponent(id));

export const deleteFlow = (id: string) =>
  request<{ id: string; deleted: boolean }>('delete', '/api/kellai/flow/definitions/' + encodeURIComponent(id));

export const executeFlow = (flowId: string) =>
  request<FlowExecution>('post', '/api/kellai/flow/execute', { flow_id: flowId });

export const getAnomalies = () =>
  request<Anomaly[]>('get', '/api/kellai/flow/anomalies');

export const getFlowTemplates = () =>
  request<FlowTemplate[]>('get', '/api/kellai/flow/templates');

export const getAutomationRate = () =>
  request<{ rate: number | null; breakdown: { stage: string; rate: number | null }[]; measurement_status: 'unmeasured'; reason: string }>('get', '/api/kellai/flow/automation-rate');

export const registerFlowWebhook = (url: string, events: string[]) =>
  request<Webhook>('post', '/api/kellai/flow/webhook', { url, events });
