import { AlertTriangle, TrendingUp, Users } from 'lucide-react';
import { clsx } from 'clsx';
import { useApiQuery } from '../hooks/useApiQuery';
import { getSentiment } from '../api/scout';
import type { SentimentItem } from '../types';

const TYPE_ICONS = {
  hotspot: TrendingUp,
  competitor: Users,
  opportunity: AlertTriangle,
};

const SEVERITY_COLORS = {
  high: 'border-red-300 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10',
  medium: 'border-amber-300 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10',
  low: 'border-gray-200 bg-gray-50 dark:border-slate-700 dark:bg-slate-800',
};

export default function SentimentMonitor() {
  const query = useApiQuery<SentimentItem[]>(['scout', 'sentiment'], () => getSentiment());

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">舆情监控</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">行业热点、竞品动态与商机预警</p>
      </div>

      <div className="space-y-4">
        {(query.data ?? []).map((item) => {
          const Icon = TYPE_ICONS[item.type];
          return (
            <div
              key={item.id}
              className={clsx('rounded-xl border p-4', SEVERITY_COLORS[item.severity])}
            >
              <div className="mb-2 flex items-center gap-2">
                <Icon className="h-5 w-5" />
                <span className="font-semibold text-gray-900 dark:text-slate-100">{item.title}</span>
                <span className="ml-auto text-xs text-gray-500">
                  {new Date(item.timestamp).toLocaleString('zh-CN')}
                </span>
              </div>
              <p className="text-sm text-gray-600 dark:text-slate-400">{item.summary}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
