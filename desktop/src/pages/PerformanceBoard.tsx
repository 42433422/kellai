import { Trophy, Medal, Award } from 'lucide-react';
import { clsx } from 'clsx';
import { useApiQuery } from '../hooks/useApiQuery';
import { getFinancePerformance } from '../api/finance';
import type { FinancePerformanceMember } from '../types';

const RANK_ICONS = [Trophy, Medal, Award];

export default function PerformanceBoard() {
  const query = useApiQuery<FinancePerformanceMember[]>(
    ['finance', 'performance'],
    () => getFinancePerformance()
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">绩效看板</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">团队与个人多维度业绩追踪</p>
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-slate-700 dark:bg-slate-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-gray-50 dark:border-slate-700 dark:bg-slate-900">
              <th className="px-4 py-3 text-left">排名</th>
              <th className="px-4 py-3 text-left">成员</th>
              <th className="px-4 py-3 text-right">营收</th>
              <th className="px-4 py-3 text-right">成交数</th>
              <th className="px-4 py-3 text-right">转化率</th>
            </tr>
          </thead>
          <tbody>
            {(query.data ?? []).map((m, i) => {
              const RankIcon = RANK_ICONS[i] ?? Award;
              return (
                <tr key={m.user_id} className="border-b dark:border-slate-700/50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {i < 3 && <RankIcon className={clsx('h-4 w-4', i === 0 ? 'text-amber-500' : i === 1 ? 'text-gray-400' : 'text-amber-700')} />}
                      #{m.rank}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-medium">{m.name}</td>
                  <td className="px-4 py-3 text-right">¥{m.revenue.toLocaleString()}</td>
                  <td className="px-4 py-3 text-right">{m.deals}</td>
                  <td className="px-4 py-3 text-right">{m.conversion_rate}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
