import { Link } from 'react-router-dom';
import { Target, TrendingUp, Users, DollarSign, Filter } from 'lucide-react';
import KpiGrid from '../components/KpiGrid';
import SimpleBarChart from '../components/SimpleBarChart';
import ProgressRing from '../components/ProgressRing';
import { useApiQuery } from '../hooks/useApiQuery';
import { getSalesPerformance, getAttribution } from '../api/sales';
import type { SalesPerformance, AttributionReport } from '../types';

export default function Performance() {
  const perfQuery = useApiQuery<SalesPerformance>(
    ['sales', 'performance'],
    () => getSalesPerformance('month')
  );
  const attrQuery = useApiQuery<AttributionReport>(
    ['sales', 'attribution'],
    () => getAttribution()
  );

  const perf = perfQuery.data;
  const attr = attrQuery.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">业绩看板</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
          目标追踪、归因分析与漏斗摘要
        </p>
      </div>

      {perf && (
        <KpiGrid
          items={[
            { title: '本月目标', value: `¥${(perf.revenue_target / 10000).toFixed(0)}万`, icon: Target },
            { title: '完成率', value: `${perf.completion_rate}%`, icon: TrendingUp, trend: { value: '环比 +5.2%', positive: true } },
            { title: '签约数', value: perf.deals_closed, icon: Users },
            { title: '客单价', value: `¥${perf.avg_deal_size.toLocaleString()}`, icon: DollarSign },
          ]}
        />
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
          <h3 className="mb-4 font-semibold text-gray-900 dark:text-slate-100">目标拆解</h3>
          {perf?.goals[0]?.breakdown.map((b) => (
            <div key={b.period} className="mb-4 flex items-center gap-4">
              <ProgressRing value={b.progress} size={56} strokeWidth={4} />
              <div>
                <p className="font-medium text-gray-900 dark:text-slate-100">{b.period}</p>
                <p className="text-sm text-gray-500">
                  {b.actual} / {b.target} 单
                </p>
              </div>
            </div>
          ))}
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
          <h3 className="mb-4 font-semibold text-gray-900 dark:text-slate-100">跨渠道归因</h3>
          {attr && (
            <SimpleBarChart
              items={attr.channels.map((c) => ({
                label: c.channel_label,
                value: c.contribution_pct,
              }))}
            />
          )}
        </div>
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
    </div>
  );
}
