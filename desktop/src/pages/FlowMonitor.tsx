import { AlertCircle, Activity, Gauge } from 'lucide-react';
import { clsx } from 'clsx';
import KpiGrid from '../components/KpiGrid';
import { useApiQuery } from '../hooks/useApiQuery';
import { getAnomalies, getAutomationRate, listFlows } from '../api/flow';
import { useAuthStore } from '../stores/auth';
import type { Anomaly, FlowDefinition } from '../types';

export default function FlowMonitor() {
  const user = useAuthStore((state) => state.user);
  const accountKey = user?.team_id + ':' + user?.id;

  const anomaliesQuery = useApiQuery<Anomaly[]>(['flow', accountKey, 'anomalies'], () => getAnomalies());
  const rateQuery = useApiQuery(['flow', accountKey, 'automation-rate'], () => getAutomationRate());
  const flowsQuery = useApiQuery<FlowDefinition[]>(['flow', accountKey, 'list'], () => listFlows());

  const rate = rateQuery.data;

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">流程监控</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">当前保存流程草稿；图形执行、执行日志与效果统计尚未接入。</p>
      </div>

      {rate && (
        <KpiGrid
          cols={3}
          items={[
            { title: '全流程自动化率', value: rate.rate == null || rate.measurement_status === 'unmeasured' ? '未统计' : `${rate.rate}%`, icon: Gauge },
            ...rate.breakdown.map((b) => ({
              title: `${b.stage}自动化`,
              value: b.rate == null ? '未统计' : `${b.rate}%`,
              icon: Activity,
            })),
          ]}
        />
      )}

      <div className="rounded-xl border border-gray-200 bg-white p-4 text-sm dark:border-slate-700 dark:bg-slate-800">
        执行未接入，暂无可核验的图形流程执行记录。消息自动回复的实际状态请查看消息中心与 AI 设置。
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        <h3 className="mb-3 flex items-center gap-2 font-semibold">
          <AlertCircle className="h-5 w-5 text-amber-500" /> 异常检测
        </h3>
        <p className="mb-3 text-sm text-gray-500">图形流程尚未执行，异常检测未启用。</p>
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
        <h3 className="mb-3 font-semibold">流程草稿</h3>
        {flowsQuery.isError && <p className="text-sm text-red-600">草稿加载失败，请稍后重试。</p>}
        {flowsQuery.isSuccess && !flowsQuery.data?.length && <p className="text-sm text-gray-500">暂无流程草稿。</p>}
        {(flowsQuery.data ?? []).map((f) => (
          <div key={f.id} className="mb-2 flex justify-between text-sm">
            <span>{f.name}</span>
            <span className="text-gray-500">{f.nodes.length} 节点 · 草稿 · 执行未接入</span>
          </div>
        ))}
      </div>
    </div>
  );
}
