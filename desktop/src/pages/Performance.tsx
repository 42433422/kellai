import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Target, TrendingUp, Users, Filter, Trophy, Medal, Award, Gauge } from 'lucide-react';
import { clsx } from 'clsx';
import KpiGrid from '../components/KpiGrid';
import ProgressRing from '../components/ProgressRing';
import Loading from '../components/Loading';
import Empty from '../components/Empty';
import { useApiQuery } from '../hooks/useApiQuery';
import { getSalesPerformance, getAttribution } from '../api/sales';
import type { SalesPerformance, AttributionReport } from '../types';

type Period = 'week' | 'month' | 'quarter' | 'year';
const PERIODS: { id: Period; label: string }[] = [
  { id: 'week', label: '本周' },
  { id: 'month', label: '本月' },
  { id: 'quarter', label: '本季' },
  { id: 'year', label: '本年' },
];

const RANK_ICON = [Trophy, Medal, Award];

export default function Performance() {
  const [period, setPeriod] = useState<Period>('month');

  const perfQuery = useApiQuery<SalesPerformance>(
    ['sales', 'performance', period],
    () => getSalesPerformance(period)
  );
  const attrQuery = useApiQuery<AttributionReport>(['sales', 'attribution'], () => getAttribution());

  const perf = perfQuery.data;
  const attr = attrQuery.data;
  const trendMax = Math.max(1, ...(perf?.revenue_trend ?? []).flatMap((t) => [t.target, t.actual]));

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">业绩看板</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">目标追踪、销售排行、归因分析与漏斗摘要</p>
        </div>
        {/* 周期切换 */}
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

      {perfQuery.isLoading ? (
        <Loading text="业绩数据加载中..." className="min-h-[40vh]" />
      ) : !perf ? (
        <Empty title="暂无业绩数据" description="切换周期或稍后再试" />
      ) : (
        <>
          <KpiGrid
            cols={4}
            items={[
              {
                title: '营收目标',
                value: `¥${(perf.revenue_target / 10000).toFixed(0)}万`,
                icon: Target,
                subtitle: `已完成 ¥${(perf.revenue_actual / 10000).toFixed(1)}万`,
              },
              {
                title: '完成率',
                value: `${perf.completion_rate}%`,
                icon: TrendingUp,
                trend: { value: `环比 ${perf.momentum_pct! >= 0 ? '+' : ''}${perf.momentum_pct}%`, positive: (perf.momentum_pct ?? 0) >= 0 },
              },
              { title: '签约数', value: perf.deals_closed, icon: Users, subtitle: `客单价 ¥${perf.avg_deal_size.toLocaleString()}` },
              {
                title: '预测成交',
                value: `¥${((perf.forecast ?? 0) / 10000).toFixed(0)}万`,
                icon: Gauge,
                subtitle: `赢单率 ${perf.win_rate ?? 0}% · 管道 ¥${((perf.pipeline_value ?? 0) / 10000).toFixed(0)}万`,
              },
            ]}
          />

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            {/* 营收趋势：目标 vs 实际 */}
            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800 lg:col-span-2">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="font-semibold text-gray-900 dark:text-slate-100">营收趋势</h3>
                <div className="flex items-center gap-4 text-xs text-gray-500">
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-gray-300" />目标</span>
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-blue-500" />实际</span>
                </div>
              </div>
              <div className="flex h-48 items-end justify-around gap-3">
                {(perf.revenue_trend ?? []).map((t) => (
                  <div key={t.period} className="flex flex-1 flex-col items-center gap-2">
                    <div className="flex h-40 w-full items-end justify-center gap-1">
                      <div
                        className="w-1/3 rounded-t bg-gray-200 transition-all dark:bg-slate-600"
                        style={{ height: `${(t.target / trendMax) * 100}%` }}
                        title={`目标 ¥${t.target.toLocaleString()}`}
                      />
                      <div
                        className="w-1/3 rounded-t bg-blue-500 transition-all"
                        style={{ height: `${(t.actual / trendMax) * 100}%` }}
                        title={`实际 ¥${t.actual.toLocaleString()}`}
                      />
                    </div>
                    <span className="text-xs text-gray-500 dark:text-slate-400">{t.period}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* 目标拆解 */}
            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
              <h3 className="mb-4 font-semibold text-gray-900 dark:text-slate-100">{perf.goals[0]?.title ?? '目标拆解'}</h3>
              <div className="space-y-3">
                {perf.goals[0]?.breakdown.map((b) => (
                  <div key={b.period} className="flex items-center gap-4">
                    <ProgressRing value={b.progress} size={48} strokeWidth={4} />
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-slate-100">{b.period}</p>
                      <p className="text-xs text-gray-500">{b.actual} / {b.target} 单</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* 销售排行榜 */}
          <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
            <h3 className="mb-4 font-semibold text-gray-900 dark:text-slate-100">销售代表排行</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-left text-xs text-gray-400 dark:border-slate-700">
                    <th className="pb-2 font-medium">排名</th>
                    <th className="pb-2 font-medium">销售</th>
                    <th className="pb-2 text-right font-medium">营收</th>
                    <th className="pb-2 text-right font-medium">签约</th>
                    <th className="pb-2 text-right font-medium">赢单率</th>
                    <th className="hidden pb-2 pl-6 font-medium sm:table-cell">目标完成</th>
                  </tr>
                </thead>
                <tbody>
                  {(perf.reps ?? []).map((rep) => {
                    const RankIcon = RANK_ICON[rep.rank - 1];
                    const pct = Math.min(100, Math.round((rep.revenue / rep.target) * 100));
                    return (
                      <tr key={rep.id} className="border-b border-gray-50 last:border-0 dark:border-slate-700/50">
                        <td className="py-2.5">
                          {RankIcon ? (
                            <RankIcon
                              className={clsx(
                                'h-5 w-5',
                                rep.rank === 1 && 'text-amber-400',
                                rep.rank === 2 && 'text-gray-400',
                                rep.rank === 3 && 'text-orange-400'
                              )}
                            />
                          ) : (
                            <span className="pl-1.5 text-gray-400">{rep.rank}</span>
                          )}
                        </td>
                        <td className="py-2.5 font-medium text-gray-900 dark:text-slate-100">{rep.name}</td>
                        <td className="py-2.5 text-right text-gray-700 dark:text-slate-300">¥{(rep.revenue / 10000).toFixed(1)}万</td>
                        <td className="py-2.5 text-right text-gray-700 dark:text-slate-300">{rep.deals}</td>
                        <td className="py-2.5 text-right text-gray-700 dark:text-slate-300">{rep.win_rate}%</td>
                        <td className="hidden py-2.5 pl-6 sm:table-cell">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-24 overflow-hidden rounded-full bg-gray-100 dark:bg-slate-700">
                              <div
                                className={clsx('h-full rounded-full', pct >= 100 ? 'bg-green-500' : 'bg-blue-500')}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                            <span className="text-xs text-gray-400">{pct}%</span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* 跨渠道归因 */}
          <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="font-semibold text-gray-900 dark:text-slate-100">跨渠道归因</h3>
              <span className="text-xs text-gray-400">{attr?.date_range}</span>
            </div>
            {attr ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-left text-xs text-gray-400 dark:border-slate-700">
                      <th className="pb-2 font-medium">渠道</th>
                      <th className="pb-2 text-right font-medium">线索</th>
                      <th className="pb-2 text-right font-medium">转化</th>
                      <th className="pb-2 text-right font-medium">营收</th>
                      <th className="pb-2 text-right font-medium">转化率</th>
                      <th className="pb-2 pl-6 font-medium">贡献占比</th>
                    </tr>
                  </thead>
                  <tbody>
                    {attr.channels.map((c) => (
                      <tr key={c.channel} className="border-b border-gray-50 last:border-0 dark:border-slate-700/50">
                        <td className="py-2.5 font-medium text-gray-900 dark:text-slate-100">{c.channel_label}</td>
                        <td className="py-2.5 text-right text-gray-700 dark:text-slate-300">{c.leads}</td>
                        <td className="py-2.5 text-right text-gray-700 dark:text-slate-300">{c.conversions}</td>
                        <td className="py-2.5 text-right text-gray-700 dark:text-slate-300">¥{(c.revenue / 10000).toFixed(1)}万</td>
                        <td className="py-2.5 text-right text-gray-700 dark:text-slate-300">
                          {((c.conversions / c.leads) * 100).toFixed(1)}%
                        </td>
                        <td className="py-2.5 pl-6">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-24 overflow-hidden rounded-full bg-gray-100 dark:bg-slate-700">
                              <div className="h-full rounded-full bg-blue-500" style={{ width: `${c.contribution_pct}%` }} />
                            </div>
                            <span className="text-xs text-gray-400">{c.contribution_pct}%</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Loading variant="skeleton" rows={4} />
            )}
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <Link
              to="/funnel"
              className="flex items-center gap-2 text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
            >
              <Filter className="h-4 w-4" />
              查看漏斗全链路追踪
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
