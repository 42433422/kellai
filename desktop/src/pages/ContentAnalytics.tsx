import { BarChart3, Eye, Heart, MousePointer } from 'lucide-react';
import KpiGrid from '../components/KpiGrid';
import SimpleBarChart from '../components/SimpleBarChart';
import { useApiQuery } from '../hooks/useApiQuery';
import { getContentAnalytics, runABTest } from '../api/content';
import type { ContentAnalytics, ABTest } from '../types';

export default function ContentAnalyticsPage() {
  const analyticsQuery = useApiQuery<ContentAnalytics>(
    ['content', 'analytics'],
    () => getContentAnalytics()
  );

  const abQuery = useApiQuery<ABTest>(
    ['content', 'ab'],
    () => runABTest(),
    { staleTime: 60000 }
  );

  const data = analyticsQuery.data;
  const ab = abQuery.data;

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">内容效果分析</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">阅读、点赞、转化全链路追踪</p>
      </div>

      {data && (
        <>
          <KpiGrid
            cols={3}
            items={[
              { title: '总阅读', value: data.totals.views.toLocaleString(), icon: Eye },
              { title: '总点赞', value: data.totals.likes.toLocaleString(), icon: Heart },
              { title: '总转化', value: data.totals.conversions, icon: MousePointer },
            ]}
          />

          <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
            <h3 className="mb-4 flex items-center gap-2 font-semibold">
              <BarChart3 className="h-5 w-5" /> 平台效果对比
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b dark:border-slate-700">
                    <th className="py-2 text-left">内容</th>
                    <th className="py-2 text-left">平台</th>
                    <th className="py-2 text-right">阅读</th>
                    <th className="py-2 text-right">转化</th>
                    <th className="py-2 text-right">CTR</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item, i) => (
                    <tr key={i} className="border-b dark:border-slate-700/50">
                      <td className="py-2">{item.title}</td>
                      <td className="py-2">{item.platform}</td>
                      <td className="py-2 text-right">{item.views.toLocaleString()}</td>
                      <td className="py-2 text-right">{item.conversions}</td>
                      <td className="py-2 text-right">{item.ctr}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {ab && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
          <h3 className="mb-4 font-semibold">A/B 测试 — {ab.name}</h3>
          <SimpleBarChart
            items={ab.variants.map((v) => ({
              label: v.name,
              value: v.win_rate,
              color: v.win_rate > 50 ? 'bg-green-500' : 'bg-gray-400',
            }))}
          />
          <div className="mt-4 space-y-2">
            {ab.variants.map((v) => (
              <div key={v.id} className="rounded-lg bg-gray-50 p-3 text-sm dark:bg-slate-900">
                <p className="font-medium">{v.content}</p>
                <p className="text-gray-500">浏览 {v.views} · 转化 {v.conversions} · 胜率 {v.win_rate}%</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
