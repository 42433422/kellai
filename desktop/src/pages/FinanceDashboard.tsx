import { useState } from 'react';
import { DollarSign, TrendingUp, Wallet, AlertTriangle, Banknote, Receipt, CheckCheck } from 'lucide-react';
import { clsx } from 'clsx';
import KpiGrid from '../components/KpiGrid';
import Loading from '../components/Loading';
import Empty from '../components/Empty';
import { useApiQuery } from '../hooks/useApiQuery';
import { getFinanceDashboard, getFinanceAlerts } from '../api/finance';
import { useFinanceStore } from '../stores/financeStore';
import { formatTimeAgo } from '../utils/format';
import type { FinanceDashboardData, FinanceAlert } from '../types';

type Period = 'month' | 'quarter' | 'year';
const PERIODS: { id: Period; label: string }[] = [
  { id: 'month', label: '本月' },
  { id: 'quarter', label: '本季' },
  { id: 'year', label: '本年' },
];

function growth(v?: number) {
  if (v === undefined) return undefined;
  return { value: `环比 ${v >= 0 ? '+' : ''}${v}%`, positive: v >= 0 };
}

export default function FinanceDashboard() {
  const [period, setPeriod] = useState<Period>('month');
  const { readAlertIds, markAlertRead, markAllAlertsRead } = useFinanceStore();

  const dashQuery = useApiQuery<FinanceDashboardData>(
    ['finance', 'dashboard', period],
    () => getFinanceDashboard(period)
  );
  const alertsQuery = useApiQuery<FinanceAlert[]>(['finance', 'alerts'], () => getFinanceAlerts());

  const dash = dashQuery.data;
  const alerts = alertsQuery.data ?? [];
  const unread = alerts.filter((a) => !readAlertIds.includes(a.id));
  const trendMax = Math.max(1, ...(dash?.monthly_trend ?? []).map((m) => m.revenue));

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">财务看板</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">跨渠道营收、成本、利润与现金流实时汇总</p>
        </div>
        <div className="flex rounded-lg bg-gray-100 p-1 dark:bg-slate-800">
          {PERIODS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setPeriod(p.id)}
              className={clsx(
                'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                period === p.id
                  ? 'bg-white text-gray-900 shadow-sm dark:bg-slate-700 dark:text-slate-100'
                  : 'text-gray-500 hover:text-gray-700 dark:text-slate-400'
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {dashQuery.isLoading ? (
        <Loading text="财务数据加载中..." className="min-h-[40vh]" />
      ) : !dash ? (
        <Empty title="暂无财务数据" description="切换周期或稍后再试" />
      ) : (
        <>
          <KpiGrid
            cols={3}
            items={[
              { title: '营收', value: `¥${(dash.revenue / 10000).toFixed(0)}万`, icon: DollarSign, trend: growth(dash.revenue_growth) },
              { title: '成本', value: `¥${(dash.cost / 10000).toFixed(0)}万`, icon: Wallet, trend: dash.cost_growth !== undefined ? { value: `环比 +${dash.cost_growth}%`, positive: false } : undefined },
              { title: '利润', value: `¥${(dash.profit / 10000).toFixed(0)}万`, icon: TrendingUp, subtitle: `利润率 ${dash.profit_margin}%`, trend: growth(dash.profit_growth) },
            ]}
          />
          <KpiGrid
            cols={3}
            items={[
              { title: '经营现金流', value: `¥${((dash.cash_flow ?? 0) / 10000).toFixed(0)}万`, icon: Banknote },
              { title: '应收账款', value: `¥${((dash.receivable ?? 0) / 10000).toFixed(0)}万`, icon: Receipt },
              { title: '应付账款', value: `¥${((dash.payable ?? 0) / 10000).toFixed(0)}万`, icon: Receipt },
            ]}
          />

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* 渠道 P&L 表 */}
            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
              <h3 className="mb-4 font-semibold text-gray-900 dark:text-slate-100">渠道盈亏（P&L）</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-left text-xs text-gray-400 dark:border-slate-700">
                      <th className="pb-2 font-medium">渠道</th>
                      <th className="pb-2 text-right font-medium">营收</th>
                      <th className="pb-2 text-right font-medium">成本</th>
                      <th className="pb-2 text-right font-medium">利润</th>
                      <th className="pb-2 text-right font-medium">利润率</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dash.channel_breakdown.map((c) => (
                      <tr key={c.channel} className="border-b border-gray-50 last:border-0 dark:border-slate-700/50">
                        <td className="py-2 font-medium text-gray-900 dark:text-slate-100">{c.channel}</td>
                        <td className="py-2 text-right text-gray-700 dark:text-slate-300">¥{(c.revenue / 10000).toFixed(1)}万</td>
                        <td className="py-2 text-right text-gray-500">¥{(c.cost / 10000).toFixed(1)}万</td>
                        <td className="py-2 text-right font-medium text-green-600 dark:text-green-400">¥{(c.profit / 10000).toFixed(1)}万</td>
                        <td className="py-2 text-right text-gray-700 dark:text-slate-300">{Math.round((c.profit / c.revenue) * 100)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* 趋势：营收 vs 利润 */}
            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="font-semibold text-gray-900 dark:text-slate-100">近 6 个月趋势</h3>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-blue-500" />营收</span>
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-green-500" />利润</span>
                </div>
              </div>
              <div className="flex h-40 items-end gap-2">
                {dash.monthly_trend.map((m) => (
                  <div key={m.month} className="flex flex-1 flex-col items-center gap-1">
                    <div className="flex h-32 w-full items-end justify-center gap-0.5">
                      <div className="w-1/2 rounded-t bg-blue-500 transition-all" style={{ height: `${(m.revenue / trendMax) * 100}%`, minHeight: 4 }} title={`营收 ¥${m.revenue.toLocaleString()}`} />
                      <div className="w-1/2 rounded-t bg-green-500 transition-all" style={{ height: `${(m.profit / trendMax) * 100}%`, minHeight: 4 }} title={`利润 ¥${m.profit.toLocaleString()}`} />
                    </div>
                    <span className="text-xs text-gray-500">{m.month.slice(5)}月</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}

      {/* 异常预警 */}
      <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="flex items-center gap-2 font-semibold text-gray-900 dark:text-slate-100">
            <AlertTriangle className="h-5 w-5 text-amber-500" /> 异常预警
            {unread.length > 0 && (
              <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-600 dark:bg-red-500/20 dark:text-red-300">
                {unread.length} 条未读
              </span>
            )}
          </h3>
          {unread.length > 0 && (
            <button
              type="button"
              onClick={() => markAllAlertsRead(alerts.map((a) => a.id))}
              className="flex items-center gap-1 text-xs text-blue-600 hover:underline dark:text-blue-400"
            >
              <CheckCheck className="h-3.5 w-3.5" /> 全部已读
            </button>
          )}
        </div>
        {alertsQuery.isLoading ? (
          <Loading variant="skeleton" rows={3} />
        ) : alerts.length === 0 ? (
          <Empty title="暂无预警" description="财务指标一切正常" />
        ) : (
          alerts.map((a) => {
            const read = readAlertIds.includes(a.id);
            const tone =
              a.severity === 'high'
                ? 'border-red-200 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10'
                : a.severity === 'medium'
                ? 'border-amber-200 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10'
                : 'border-gray-200 bg-gray-50 dark:border-slate-700 dark:bg-slate-900';
            return (
              <div key={a.id} className={clsx('mb-2 flex items-start justify-between gap-3 rounded-lg border p-3', tone, read && 'opacity-60')}>
                <div>
                  <div className="flex items-center gap-2">
                    <span
                      className={clsx(
                        'rounded px-1.5 py-0.5 text-[10px] font-medium',
                        a.severity === 'high' ? 'bg-red-500 text-white' : a.severity === 'medium' ? 'bg-amber-500 text-white' : 'bg-gray-400 text-white'
                      )}
                    >
                      {a.severity === 'high' ? '高' : a.severity === 'medium' ? '中' : '低'}
                    </span>
                    <p className="font-medium text-gray-900 dark:text-slate-100">{a.title}</p>
                  </div>
                  <p className="mt-0.5 text-sm text-gray-600 dark:text-slate-400">{a.message}</p>
                  <p className="mt-0.5 text-xs text-gray-400">{formatTimeAgo(a.timestamp)}</p>
                </div>
                {!read && (
                  <button
                    type="button"
                    onClick={() => markAlertRead(a.id)}
                    className="shrink-0 text-xs text-blue-600 hover:underline dark:text-blue-400"
                  >
                    标记已读
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
