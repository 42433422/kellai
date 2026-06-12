import { AlertCircle, Activity, Gauge } from 'lucide-react';
import { clsx } from 'clsx';
import KpiGrid from '../components/KpiGrid';
import { useApiQuery } from '../hooks/useApiQuery';
import { getAnomalies, getAutomationRate, listFlows } from '../api/flow';
import { useFlowStore } from '../stores/flowStore';
import type { Anomaly, FlowDefinition } from '../types';

export default function FlowMonitor() {
  const { lastExecution } = useFlowStore();

  const anomaliesQuery = useApiQuery<Anomaly[]>(['flow', 'anomalies'], () => getAnomalies());
  const rateQuery = useApiQuery(['flow', 'automation-rate'], () => getAutomationRate());
  const flowsQuery = useApiQuery<FlowDefinition[]>(['flow', 'list'], () => listFlows());

  const rate = rateQuery.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">流程监控</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">执行日志、异常检测与自动化率</p>
      </div>

      {rate && (
        <KpiGrid
          cols={3}
          items={[
            { title: '全流程自动化率', value: `${rate.rate}%`, icon: Gauge },
            ...rate.breakdown.map((b) => ({
              title: `${b.stage}自动化`,
              value: `${b.rate}%`,
              icon: Activity,
            })),
          ]}
        />
      )}

      {lastExecution && (
        <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
          <h3 className="mb-3 font-semibold">最近执行 — {lastExecution.flow_name}</h3>
          <div className="space-y-2">
            {lastExecution.logs.map((log, i) => (
              <div key={i} className="flex gap-3 text-sm">
                <span className="text-gray-400">{new Date(log.timestamp).toLocaleTimeString('zh-CN')}</span>
                <span>{log.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        <h3 className="mb-3 flex items-center gap-2 font-semibold">
          <AlertCircle className="h-5 w-5 text-amber-500" /> 异常检测
        </h3>
        {(anomaliesQuery.data ?? []).map((a) => (
          <div
            key={a.id}
            className={clsx(
              'mb-3 rounded-lg border p-3',
              a.severity === 'critical' ? 'border-red-300 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10' : 'border-amber-300 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10'
            )}
          >
            <p className="font-medium">{a.message}</p>
            <p className="mt-1 text-sm text-gray-600 dark:text-slate-400">建议：{a.suggestion}</p>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        <h3 className="mb-3 font-semibold">流程列表</h3>
        {(flowsQuery.data ?? []).map((f) => (
          <div key={f.id} className="mb-2 flex justify-between text-sm">
            <span>{f.name}</span>
            <span className="text-gray-500">{f.nodes.length} 节点</span>
          </div>
        ))}
      </div>
    </div>
  );
}
