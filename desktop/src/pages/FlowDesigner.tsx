import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  ReactFlow, Background, Controls, MiniMap, addEdge, useNodesState, useEdgesState,
  type Connection, type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Play, Plus, Save, Loader2 } from 'lucide-react';
import { useApiQuery, useApiMutation, useQueryClient } from '../hooks/useApiQuery';
import { listFlows, createFlow, updateFlow } from '../api/flow';
import { fromDraftNodes, toDraftNodes, type DraftNode } from '../api/flowDraft';
import { currentAccountKey } from '../api/client';
import { useAuthStore } from '../stores/auth';
import { toastStore } from '../stores/toast';
import type { FlowDefinition, FlowNodeType } from '../types';

const NODE_TYPES: FlowNodeType[] = ['acquire', 'communicate', 'sales', 'after_sales', 'webhook'];
const NODE_LABELS: Record<FlowNodeType, string> = {
  acquire: '获客', communicate: '沟通', sales: '销售', after_sales: '售后', webhook: 'Webhook',
};

function DraftEditor({ accountKey, canEdit }: { accountKey: string; canEdit: boolean }) {
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();
  const queryKey = ['flow', accountKey, 'list'];
  const flowsQuery = useApiQuery<FlowDefinition[]>(queryKey, () => listFlows());
  const requestedId = params.get('flow');
  const selectedFlow = requestedId === 'new' ? undefined
    : requestedId ? flowsQuery.data?.find((flow) => flow.id === requestedId) : flowsQuery.data?.[0];
  const viewKey = accountKey + ':' + (requestedId || selectedFlow?.id || 'new');
  const initialized = useRef('');
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const activeView = useRef(viewKey);
  activeView.current = viewKey;
  const [name, setName] = useState('新流程');
  const [nodes, setNodes, onNodesChange] = useNodesState<DraftNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    if (!flowsQuery.isSuccess || initialized.current === viewKey) return;
    initialized.current = viewKey;
    setName(selectedFlow?.name || '新流程');
    setNodes(toDraftNodes(selectedFlow?.nodes || []));
    setEdges((selectedFlow?.edges || []).map((edge) => ({ ...edge })));
  }, [flowsQuery.isSuccess, selectedFlow, viewKey, setNodes, setEdges]);

  const saveMutation = useApiMutation(
    (draft: { id?: string; name: string; nodes: FlowDefinition['nodes']; edges: FlowDefinition['edges']; view: string }) =>
      draft.id ? updateFlow(draft.id, { name: draft.name, nodes: draft.nodes, edges: draft.edges })
        : createFlow(draft.name, draft.nodes, draft.edges),
    {
      onSuccess: (saved, draft) => {
        if (!mounted.current || currentAccountKey() !== accountKey || activeView.current !== draft.view) return;
        queryClient.setQueryData<FlowDefinition[]>(queryKey, (old) => [
          saved, ...(old || []).filter((flow) => flow.id !== saved.id),
        ]);
        setParams({ flow: saved.id }, { replace: true });
        toastStore.success('流程草稿已保存');
      },
    }
  );

  const onConnect = useCallback((connection: Connection) => {
    if (canEdit && !saveMutation.isPending) setEdges((current) => addEdge(connection, current));
  }, [canEdit, saveMutation.isPending, setEdges]);

  const addNode = (type: FlowNodeType) => {
    const node = {
      id: 'node_' + crypto.randomUUID(), type, label: NODE_LABELS[type], config: {},
      position: { x: (nodes.length % 3) * 240, y: Math.floor(nodes.length / 3) * 150 },
    };
    setNodes((current) => [...current, ...toDraftNodes([node])]);
  };

  if (flowsQuery.isLoading) {
    return <div className="flex h-full items-center justify-center"><Loader2 className="h-8 w-8 animate-spin" /></div>;
  }
  if (flowsQuery.isError) {
    return <div className="p-6 text-sm">无法加载流程草稿。<button type="button" onClick={() => void flowsQuery.refetch()} className="ml-3 text-blue-600">重试</button></div>;
  }
  const missing = Boolean(requestedId && requestedId !== 'new' && !selectedFlow);
  const editable = canEdit && !saveMutation.isPending && !missing;

  return (
    <div className="flex h-full flex-1 min-h-0 flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">流程草稿</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400">保存节点、配置与连线；图形执行和 Webhook 尚未接入。</p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => setParams({ flow: 'new' })}
            disabled={!canEdit || saveMutation.isPending}
            className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm disabled:opacity-50">
            <Plus className="h-4 w-4" /> 新建草稿
          </button>
          <button type="button" disabled={!editable || !name.trim()}
            onClick={() => saveMutation.mutate({
              id: selectedFlow?.id, name: name.trim(), nodes: fromDraftNodes(nodes),
              edges: edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })), view: viewKey,
            })}
            className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm disabled:opacity-50">
            <Save className="h-4 w-4" /> {saveMutation.isPending ? '保存中…' : '保存草稿'}
          </button>
          <button type="button" disabled title="图形流程尚未接入执行运行时"
            className="flex items-center gap-2 rounded-lg bg-gray-200 px-3 py-2 text-sm text-gray-500 dark:bg-slate-700">
            <Play className="h-4 w-4" /> 执行未接入
          </button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <select aria-label="选择流程草稿" value={requestedId || selectedFlow?.id || 'new'}
          disabled={saveMutation.isPending}
          onChange={(event) => setParams({ flow: event.target.value })}
          className="rounded-lg border bg-white px-3 py-2 text-sm dark:bg-slate-800">
          <option value="new">新流程草稿</option>
          {missing && <option value={requestedId || ''}>草稿不存在</option>}
          {(flowsQuery.data || []).map((flow) => <option key={flow.id} value={flow.id}>{flow.name}</option>)}
        </select>
        <input aria-label="流程名称" value={name} maxLength={200} disabled={!editable}
          onChange={(event) => setName(event.target.value)}
          className="rounded-lg border bg-white px-3 py-2 text-sm dark:bg-slate-800" />
        <span className="text-xs text-amber-600">草稿 · 执行未接入</span>
      </div>
      {missing ? <p className="text-sm text-red-600">当前团队不存在此草稿，请重新选择或新建。</p> : (
        <>
          <div className="flex flex-wrap gap-2">
            {NODE_TYPES.map((type) => <button key={type} type="button" disabled={!editable}
              onClick={() => addNode(type)} className="rounded-lg border px-3 py-1 text-xs disabled:opacity-50">
              + {NODE_LABELS[type]}
            </button>)}
          </div>
          <div className="min-h-0 flex-1 rounded-xl border border-gray-200 dark:border-slate-700" style={{ minHeight: 400 }}>
            <ReactFlow key={viewKey} nodes={nodes} edges={edges}
              onNodesChange={editable ? onNodesChange : undefined}
              onEdgesChange={editable ? onEdgesChange : undefined}
              onConnect={onConnect} nodesDraggable={editable} nodesConnectable={editable}
              elementsSelectable={editable} deleteKeyCode={editable ? 'Backspace' : null}
              onInit={(instance) => { window.requestAnimationFrame(() => void instance.fitView()); }} fitView>
              <Background /><Controls /><MiniMap />
            </ReactFlow>
          </div>
        </>
      )}
    </div>
  );
}

export default function FlowDesigner() {
  const user = useAuthStore((state) => state.user);
  const accountKey = user?.id && user?.team_id ? user.team_id + ':' + user.id : '';
  const canEdit = ['owner', 'admin', 'sales'].includes(String(user?.role || ''));
  return <DraftEditor key={accountKey} accountKey={accountKey} canEdit={canEdit} />;
}
