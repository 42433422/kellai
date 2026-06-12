import { DollarSign, TrendingUp, Wallet, AlertTriangle } from 'lucide-react';
import KpiGrid from '../components/KpiGrid';
import SimpleBarChart from '../components/SimpleBarChart';
import { useApiQuery } from '../hooks/useApiQuery';
import { getFinanceDashboard, getFinanceAlerts } from '../api/finance';
import { useFinanceStore } from '../stores/financeStore';
import type { FinanceDashboardData, FinanceAlert } from '../types';
import { clsx } from 'clsx';

export default function FinanceDashboard() {
  const { readAlertIds, markAlertRead } = useFinanceStore();

  const dashQuery = useApiQuery<FinanceDashboardData>(
    ['finance', 'dashboard'],
    () => getFinanceDashboard()
  );
  const alertsQuery = useApiQuery<FinanceAlert[]>(
    ['finance', 'alerts'],
    () => getFinanceAlerts()
  );

  const dash = dashQuery.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">财务看板</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">跨渠道营收、成本、利润实时汇总</p>
      </div>

      {dash && (
        <>
          <KpiGrid
            items={[
              { title: '营收', value: `¥${(dash.revenue / 10000).toFixed(0)}万`, icon: DollarSign },
              { title: '成本', value: `¥${(dash.cost / 10000).toFixed(0)}万`, icon: Wallet },
              { title: '利润', value: `¥${(dash.profit / 10000).toFixed(0)}万`, icon: TrendingUp, trend: { value: `利润率 ${dash.profit_margin}%`, positive: true } },
            ]}
          />

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
              <h3 className="mb-4 font-semibold">渠道利润分布</h3>
              <SimpleBarChart
                items={dash.channel_breakdown.map((c) => ({
                  label: c.channel,
                  value: Math.round(c.profit / 10000),
                  color: 'bg-green-500',
                }))}
                unit="万"
              />
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
              <h3 className="mb-4 font-semibold">6 个月趋势</h3>
              <div className="flex h-40 items-end gap-2">
                {dash.monthly_trend.map((m) => (
                  <div key={m.month} className="flex flex-1 flex-col items-center gap-1">
                    <div
                      className="w-full rounded-t bg-blue-500"
                      style={{ height: `${(m.revenue / 1280000) * 100}%`, minHeight: 4 }}
                    />
                    <span className="text-xs text-gray-500">{m.month.slice(5)}月</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}

      <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        <h3 className="mb-3 flex items-center gap-2 font-semibold">
          <AlertTriangle className="h-5 w-5 text-amber-500" /> 异常预警
        </h3>
        {(alertsQuery.data ?? []).map((a) => (
          <div
            key={a.id}
            className={clsx(
              'mb-2 flex items-center justify-between rounded-lg border p-3',
              a.severity === 'high' ? 'border-red-200 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10' : 'border-amber-200 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10',
              readAlertIds.includes(a.id) && 'opacity-60'
            )}
          >
            <div>
              <p className="font-medium">{a.title}</p>
              <p className="text-sm text-gray-600 dark:text-slate-400">{a.message}</p>
            </div>
            {!readAlertIds.includes(a.id) && (
              <button
                type="button"
                onClick={() => markAlertRead(a.id)}
                className="text-xs text-blue-600 hover:underline dark:text-blue-400"
              >
                标记已读
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
