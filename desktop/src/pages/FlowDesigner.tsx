import { useCallback } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Node,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Play, Save, Loader2 } from 'lucide-react';
import { useApiQuery, useApiMutation } from '../hooks/useApiQuery';
import { listFlows, updateFlow, executeFlow } from '../api/flow';
import { useFlowStore } from '../stores/flowStore';
import { toastStore } from '../stores/toast';
import type { FlowDefinition } from '../types';

const NODE_TYPES = ['acquire', 'communicate', 'sales', 'after_sales', 'webhook'] as const;
const NODE_LABELS: Record<string, string> = {
  acquire: '获客',
  communicate: '沟通',
  sales: '销售',
  after_sales: '售后',
  webhook: 'Webhook',
};

function toFlowNodes(flow: FlowDefinition): Node[] {
  return flow.nodes.map((n) => ({
    id: n.id,
    type: 'default',
    position: n.position,
    data: { label: `${NODE_LABELS[n.type] ?? n.type}: ${n.label}` },
  }));
}

function toFlowEdges(flow: FlowDefinition): Edge[] {
  return flow.edges.map((e) => ({ id: e.id, source: e.source, target: e.target }));
}

export default function FlowDesigner() {
  const { setCurrentFlow, setLastExecution } = useFlowStore();

  const flowsQuery = useApiQuery<FlowDefinition[]>(['flow', 'list'], () => listFlows());

  const initialFlow = flowsQuery.data?.[0];
  const [nodes, , onNodesChange] = useNodesState(initialFlow ? toFlowNodes(initialFlow) : []);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialFlow ? toFlowEdges(initialFlow) : []);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  const saveMutation = useApiMutation(
    () => {
      const id = initialFlow?.id ?? '';
      const flowNodes = nodes.map((n, i) => ({
        id: n.id,
        type: (NODE_TYPES[i % NODE_TYPES.length]) as FlowDefinition['nodes'][0]['type'],
        label: String(n.data.label ?? n.id),
        config: {},
        position: n.position,
      }));
      const flowEdges = edges.map((e) => ({ id: e.id, source: e.source, target: e.target }));
      return updateFlow(id, { nodes: flowNodes, edges: flowEdges });
    },
    { onSuccess: (f) => { if (f) { setCurrentFlow(f); toastStore.success('流程已保存'); } } }
  );

  const execMutation = useApiMutation(
    () => executeFlow(initialFlow?.id ?? ''),
    {
      onSuccess: (exec) => {
        setLastExecution(exec);
        toastStore.success('流程执行完成');
      },
    }
  );

  if (flowsQuery.isLoading) {
    return <div className="flex h-full items-center justify-center"><Loader2 className="h-8 w-8 animate-spin" /></div>;
  }

  return (
    <div className="flex h-full flex-col space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">流程设计器</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400">拖拽设计获客→沟通→销售→售后全流程</p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
            className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-gray-50 dark:border-slate-600 dark:hover:bg-slate-700"
          >
            <Save className="h-4 w-4" /> 保存
          </button>
          <button
            type="button"
            onClick={() => execMutation.mutate()}
            disabled={execMutation.isPending}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700"
          >
            <Play className="h-4 w-4" /> 执行
          </button>
        </div>
      </div>
      <div className="flex-1 rounded-xl border border-gray-200 dark:border-slate-700" style={{ minHeight: 400 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
    </div>
  );
}
