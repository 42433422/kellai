import { Download, Zap } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useApiQuery, useApiMutation } from '../hooks/useApiQuery';
import { getFlowTemplates, createFlow } from '../api/flow';
import { toastStore } from '../stores/toast';
import type { FlowTemplate } from '../types';

export default function TemplateMarket() {
  const navigate = useNavigate();

  const templatesQuery = useApiQuery<FlowTemplate[]>(
    ['flow', 'templates'],
    () => getFlowTemplates()
  );

  const deployMutation = useApiMutation(
    (tpl: FlowTemplate) => createFlow(tpl.name, tpl.nodes, tpl.edges),
    {
      onSuccess: () => {
        toastStore.success('模板已部署');
        navigate('/flow/designer');
      },
    }
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">模板市场</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">行业开箱即用流程方案</p>
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
              <span>自动化率 {tpl.automation_rate}%</span>
            </div>
            <button
              type="button"
              onClick={() => deployMutation.mutate(tpl)}
              disabled={deployMutation.isPending}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-2 text-sm text-white hover:bg-blue-700"
            >
              <Download className="h-4 w-4" /> 一键部署
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
