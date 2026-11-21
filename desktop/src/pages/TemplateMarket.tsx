import { useEffect, useRef } from 'react';
import { Download, Zap } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useApiQuery, useApiMutation, useQueryClient } from '../hooks/useApiQuery';
import { getFlowTemplates, createFlow } from '../api/flow';
import { currentAccountKey } from '../api/client';
import { useAuthStore } from '../stores/auth';
import { toastStore } from '../stores/toast';
import type { FlowDefinition, FlowTemplate } from '../types';

export default function TemplateMarket() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const accountKey = user?.team_id + ':' + user?.id;
  const canEdit = ['owner', 'admin', 'sales'].includes(String(user?.role || ''));
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const templatesQuery = useApiQuery<FlowTemplate[]>(
    ['flow', 'templates'],
    () => getFlowTemplates()
  );

  const deployMutation = useApiMutation(
    (tpl: FlowTemplate) => createFlow(tpl.name, tpl.nodes, tpl.edges),
    {
      onSuccess: (saved) => {
        if (!mounted.current || currentAccountKey() !== accountKey) return;
        queryClient.setQueryData<FlowDefinition[]>(['flow', accountKey, 'list'], (old) => [saved, ...(old || [])]);
        toastStore.success('已从示例创建流程草稿');
        navigate('/flow/designer?flow=' + encodeURIComponent(saved.id));
      },
    }
  );

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">模板市场</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">行业流程结构示例，可创建草稿继续编辑；执行尚未接入。</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {(templatesQuery.data ?? []).map((tpl) => (
          <div
            key={tpl.id}
            className="rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800"
          >
            <div className="mb-2 flex items-center gap-2">
              <Zap className="h-5 w-5 text-amber-500" />
              <h3 className="font-semibold text-gray-900 dark:text-slate-100">{tpl.name}</h3>
            </div>
            <p className="mb-3 text-sm text-gray-600 dark:text-slate-400">{tpl.description}</p>
            <div className="mb-4 flex gap-4 text-xs text-gray-500">
              <span>{tpl.nodes.length} 节点</span>
              <span>示例 · 效果未统计</span>
            </div>
            <button
              type="button"
              onClick={() => deployMutation.mutate(tpl)}
              disabled={!canEdit || deployMutation.isPending}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-2 text-sm text-white hover:bg-blue-700"
            >
              <Download className="h-4 w-4" /> 创建草稿
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
