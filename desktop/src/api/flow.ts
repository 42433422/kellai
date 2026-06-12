import { request } from './client';
import type { FlowDefinition, FlowTemplate, FlowExecution, Anomaly, Webhook } from '../types';

export const createFlow = (name: string, nodes: FlowDefinition['nodes'], edges: FlowDefinition['edges']) =>
  request<FlowDefinition>('post', '/api/kellai/flow/create', { name, nodes, edges });

export const updateFlow = (id: string, data: Partial<FlowDefinition>) =>
  request<FlowDefinition>('put', '/api/kellai/flow/update', { id, ...data });

export const listFlows = () =>
  request<FlowDefinition[]>('get', '/api/kellai/flow/list');

export const executeFlow = (flowId: string) =>
  request<FlowExecution>('post', '/api/kellai/flow/execute', { flow_id: flowId });

export const getAnomalies = () =>
  request<Anomaly[]>('get', '/api/kellai/flow/anomalies');

export const getFlowTemplates = () =>
  request<FlowTemplate[]>('get', '/api/kellai/flow/templates');

export const getAutomationRate = () =>
  request<{ rate: number; breakdown: { stage: string; rate: number }[] }>('get', '/api/kellai/flow/automation-rate');

export const registerFlowWebhook = (url: string, events: string[]) =>
  request<Webhook>('post', '/api/kellai/flow/webhook', { url, events });
