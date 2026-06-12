import type { FlowDefinition, FlowTemplate, FlowExecution, Anomaly, Webhook } from '../types';

const flows: FlowDefinition[] = [];
const executions: FlowExecution[] = [];
const webhooks: Webhook[] = [];

export const FLOW_TEMPLATES: FlowTemplate[] = [
  {
    id: 'tpl_edu',
    name: '教育培训获客',
    industry: 'education',
    description: '线索获取 → 试听课 → 签约 → 续费',
    automation_rate: 78,
    nodes: [
      { id: 'n1', type: 'acquire', label: '抖音评论巡检', config: {}, position: { x: 0, y: 0 } },
      { id: 'n2', type: 'communicate', label: 'AI 自动回复', config: {}, position: { x: 200, y: 0 } },
      { id: 'n3', type: 'sales', label: '试听课预约', config: {}, position: { x: 400, y: 0 } },
      { id: 'n4', type: 'sales', label: '促单签约', config: {}, position: { x: 600, y: 0 } },
      { id: 'n5', type: 'after_sales', label: '续费提醒', config: {}, position: { x: 800, y: 0 } },
    ],
    edges: [
      { id: 'e1', source: 'n1', target: 'n2' },
      { id: 'e2', source: 'n2', target: 'n3' },
      { id: 'e3', source: 'n3', target: 'n4' },
      { id: 'e4', source: 'n4', target: 'n5' },
    ],
  },
  {
    id: 'tpl_local',
    name: '本地生活获客',
    industry: 'local',
    description: '小红书种草 → 私信 → 到店 → 复购',
    automation_rate: 72,
    nodes: [
      { id: 'n1', type: 'acquire', label: '小红书巡检', config: {}, position: { x: 0, y: 0 } },
      { id: 'n2', type: 'communicate', label: '私信触达', config: {}, position: { x: 200, y: 0 } },
      { id: 'n3', type: 'sales', label: '优惠券发放', config: {}, position: { x: 400, y: 0 } },
      { id: 'n4', type: 'after_sales', label: '复购提醒', config: {}, position: { x: 600, y: 0 } },
    ],
    edges: [
      { id: 'e1', source: 'n1', target: 'n2' },
      { id: 'e2', source: 'n2', target: 'n3' },
      { id: 'e3', source: 'n3', target: 'n4' },
    ],
  },
  {
    id: 'tpl_saas',
    name: 'SaaS 订阅',
    industry: 'saas',
    description: '官网线索 → 演示 → 试用 → 付费',
    automation_rate: 85,
    nodes: [
      { id: 'n1', type: 'acquire', label: '官网表单', config: {}, position: { x: 0, y: 0 } },
      { id: 'n2', type: 'communicate', label: 'AI 需求确认', config: {}, position: { x: 200, y: 0 } },
      { id: 'n3', type: 'sales', label: '产品演示', config: {}, position: { x: 400, y: 0 } },
      { id: 'n4', type: 'sales', label: '试用转化', config: {}, position: { x: 600, y: 0 } },
      { id: 'n5', type: 'webhook', label: 'CRM 同步', config: {}, position: { x: 800, y: 0 } },
    ],
    edges: [
      { id: 'e1', source: 'n1', target: 'n2' },
      { id: 'e2', source: 'n2', target: 'n3' },
      { id: 'e3', source: 'n3', target: 'n4' },
      { id: 'e4', source: 'n4', target: 'n5' },
    ],
  },
];

export function createFlow(name: string, nodes: FlowDefinition['nodes'], edges: FlowDefinition['edges']): FlowDefinition {
  const flow: FlowDefinition = {
    id: `flow_${Date.now()}`,
    name,
    nodes,
    edges,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  flows.push(flow);
  return flow;
}

export function updateFlow(id: string, data: Partial<FlowDefinition>): FlowDefinition | null {
  const idx = flows.findIndex((f) => f.id === id);
  if (idx < 0) return null;
  flows[idx] = { ...flows[idx], ...data, updated_at: new Date().toISOString() };
  return flows[idx];
}

export function listFlows(): FlowDefinition[] {
  return flows.length ? flows : [createFlow('默认获客流程', FLOW_TEMPLATES[0].nodes, FLOW_TEMPLATES[0].edges)];
}

export function executeFlow(flowId: string): FlowExecution {
  const flow = flows.find((f) => f.id === flowId) ?? listFlows()[0];
  const exec: FlowExecution = {
    id: `exec_${Date.now()}`,
    flow_id: flow.id,
    flow_name: flow.name,
    status: 'running',
    started_at: new Date().toISOString(),
    logs: flow.nodes.map((n) => ({
      node_id: n.id,
      message: `执行节点: ${n.label}`,
      timestamp: new Date().toISOString(),
    })),
  };
  exec.status = 'completed';
  exec.completed_at = new Date().toISOString();
  executions.unshift(exec);
  return exec;
}

export function getAnomalies(): Anomaly[] {
  return [
    { id: 'a1', flow_id: 'flow_1', node_id: 'n3', severity: 'warning', message: '促单节点转化率低于阈值', suggestion: '建议调整话术模板或增加优惠策略', detected_at: new Date().toISOString() },
  ];
}

export function getTemplates(): FlowTemplate[] {
  return FLOW_TEMPLATES;
}

export function getAutomationRate(): { rate: number; breakdown: { stage: string; rate: number }[] } {
  return {
    rate: 72,
    breakdown: [
      { stage: '获客', rate: 85 },
      { stage: '沟通', rate: 90 },
      { stage: '销售', rate: 55 },
      { stage: '售后', rate: 60 },
    ],
  };
}

export function registerWebhook(url: string, events: string[]): Webhook {
  const wh: Webhook = {
    id: `wh_${Date.now()}`,
    url,
    events,
    enabled: true,
    created_at: new Date().toISOString(),
  };
  webhooks.push(wh);
  return wh;
}

export function getExecutions(): FlowExecution[] {
  return executions;
}

export function getWebhooks(): Webhook[] {
  return webhooks;
}
