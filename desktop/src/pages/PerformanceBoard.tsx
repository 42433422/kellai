import { useState } from 'react';
import { Trophy, Medal, Award, Users, DollarSign, Target } from 'lucide-react';
import { clsx } from 'clsx';
import KpiGrid from '../components/KpiGrid';
import Loading from '../components/Loading';
import Empty from '../components/Empty';
import { useApiQuery } from '../hooks/useApiQuery';
import { getFinancePerformance } from '../api/finance';
import type { FinancePerformanceMember } from '../types';

const RANK_ICONS = [Trophy, Medal, Award];

type Period = 'month' | 'quarter' | 'year';
const PERIODS: { id: Period; label: string }[] = [
  { id: 'month', label: '本月' },
  { id: 'quarter', label: '本季' },
  { id: 'year', label: '本年' },
];

/** 迷你趋势条 */
function Sparkline({ data }: { data: number[] }) {
  const max = Math.max(1, ...data);
  return (
    <div className="flex h-8 items-end gap-0.5">
      {data.map((v, i) => (
        <div key={i} className="w-1.5 rounded-sm bg-blue-400/70" style={{ height: `${(v / max) * 100}%`, minHeight: 2 }} />
      ))}
    </div>
  );
}

export default function PerformanceBoard() {
  const [period, setPeriod] = useState<Period>('month');
  const query = useApiQuery<FinancePerformanceMember[]>(
    ['finance', 'performance', period],
    () => getFinancePerformance(period)
  );

  const members = query.data ?? [];
  const totalRevenue = members.reduce((s, m) => s + m.revenue, 0);
  const totalDeals = members.reduce((s, m) => s + m.deals, 0);
  const avgAttainment = members.length
    ? Math.round((members.reduce((s, m) => s + (m.attainment ?? 0), 0) / members.length) * 10) / 10
    : 0;
  const top = members[0];

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">绩效看板</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">团队与个人多维度业绩追踪</p>
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

      {query.isLoading ? (
        <Loading text="绩效数据加载中..." className="min-h-[40vh]" />
      ) : members.length === 0 ? (
        <Empty title="暂无绩效数据" description="切换周期或稍后再试" />
      ) : (
        <>
          <KpiGrid
            cols={4}
            items={[
              { title: '团队总营收', value: `¥${(totalRevenue / 10000).toFixed(0)}万`, icon: DollarSign },
              { title: '总成交数', value: totalDeals, icon: Users },
              { title: '平均达成率', value: `${avgAttainment}%`, icon: Target, trend: { value: avgAttainment >= 90 ? '达标' : '冲刺中', positive: avgAttainment >= 90 } },
              { title: '冠军', value: top?.name ?? '-', icon: Trophy, subtitle: top ? `¥${(top.revenue / 10000).toFixed(1)}万` : undefined },
            ]}
          />

          <div className="overflow-auto rounded-xl border border-gray-200 bg-white dark:border-slate-700 dark:bg-slate-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-gray-50 text-left text-xs text-gray-400 dark:border-slate-700 dark:bg-slate-900">
                  <th className="px-4 py-3 font-medium">排名</th>
                  <th className="px-4 py-3 font-medium">成员</th>
                  <th className="px-4 py-3 text-right font-medium">营收</th>
                  <th className="px-4 py-3 text-right font-medium">成交</th>
                  <th className="px-4 py-3 text-right font-medium">转化率</th>
                  <th className="px-4 py-3 font-medium">目标达成</th>
                  <th className="hidden px-4 py-3 font-medium md:table-cell">近 6 期走势</th>
                </tr>
              </thead>
              <tbody>
                {members.map((m, i) => {
                  const RankIcon = RANK_ICONS[i];
                  const attainment = m.attainment ?? 0;
                  return (
                    <tr key={m.user_id} className="border-b last:border-0 dark:border-slate-700/50">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          {RankIcon ? (
                            <RankIcon className={clsx('h-4 w-4', i === 0 ? 'text-amber-500' : i === 1 ? 'text-gray-400' : 'text-orange-400')} />
                          ) : null}
                          <span className="text-gray-500">#{m.rank}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 font-medium text-gray-900 dark:text-slate-100">{m.name}</td>
                      <td className="px-4 py-3 text-right text-gray-700 dark:text-slate-300">¥{(m.revenue / 10000).toFixed(1)}万</td>
                      <td className="px-4 py-3 text-right text-gray-700 dark:text-slate-300">{m.deals}</td>
                      <td className="px-4 py-3 text-right text-gray-700 dark:text-slate-300">{m.conversion_rate}%</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-gray-100 dark:bg-slate-700">
                            <div
                              className={clsx('h-full rounded-full', attainment >= 100 ? 'bg-green-500' : attainment >= 80 ? 'bg-blue-500' : 'bg-amber-500')}
                              style={{ width: `${Math.min(100, attainment)}%` }}
                            />
                          </div>
                          <span className="text-xs text-gray-400">{attainment}%</span>
                        </div>
                      </td>
                      <td className="hidden px-4 py-3 md:table-cell">
                        {m.trend ? <Sparkline data={m.trend} /> : <span className="text-gray-300">-</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
