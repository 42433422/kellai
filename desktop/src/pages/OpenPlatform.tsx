import { Link } from 'react-router-dom';
import { Globe, Key, Puzzle, Code, BookOpen, Webhook, Activity, Zap, Download, ShieldCheck } from 'lucide-react';
import KpiGrid from '../components/KpiGrid';
import Loading from '../components/Loading';
import { useApiQuery } from '../hooks/useApiQuery';
import { getPlatformStats } from '../api/openPlatform';
import { formatTimeAgo } from '../utils/format';
import type { PlatformStats } from '../types';

const ACTIVITY_ICON: Record<string, typeof Zap> = {
  install: Download,
  key: Key,
  webhook: Webhook,
  review: ShieldCheck,
};

export default function OpenPlatform() {
  const statsQuery = useApiQuery<PlatformStats>(['open', 'stats'], () => getPlatformStats());
  const stats = statsQuery.data;
  const trendMax = Math.max(1, ...(stats?.call_trend ?? []).map((c) => c.count));

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0" data-tour="open-platform-home">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">开放平台</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">构建客来来生态，连接开发者与合作伙伴</p>
      </div>

      {statsQuery.isLoading ? (
        <Loading text="加载平台数据..." className="min-h-[30vh]" />
      ) : stats ? (
        <>
          <KpiGrid
            cols={4}
            items={[
              { title: '30 日 API 调用', value: `${(stats.api_calls_30d / 10000).toFixed(1)}万`, icon: Activity, trend: { value: `可用性 ${stats.uptime}%`, positive: true } },
              { title: '插件数', value: stats.plugins, icon: Puzzle, subtitle: `${stats.total_installs.toLocaleString()} 次安装` },
              { title: 'ISV 伙伴', value: stats.isv_partners, icon: Globe },
              { title: '今日事件', value: stats.events_today.toLocaleString(), icon: Zap, subtitle: `${stats.active_webhooks} 个活跃 Webhook` },
            ]}
          />

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800 lg:col-span-2">
              <h3 className="mb-4 font-semibold text-gray-900 dark:text-slate-100">近 7 日 API 调用量</h3>
              <div className="flex h-40 items-end justify-around gap-2">
                {stats.call_trend.map((c) => (
                  <div key={c.date} className="flex flex-1 flex-col items-center gap-1">
                    <div className="flex w-full justify-center">
                      <div className="w-2/3 rounded-t bg-blue-500 transition-all" style={{ height: `${(c.count / trendMax) * 128}px`, minHeight: 4 }} title={`${c.count.toLocaleString()} 次`} />
                    </div>
                    <span className="text-xs text-gray-500">{c.date}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
              <h3 className="mb-4 font-semibold text-gray-900 dark:text-slate-100">最近动态</h3>
              <ol className="space-y-3">
                {stats.recent_activity.map((a) => {
                  const Icon = ACTIVITY_ICON[a.type] ?? Activity;
                  return (
                    <li key={a.id} className="flex gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gray-100 dark:bg-slate-700">
                        <Icon className="h-4 w-4 text-blue-500" />
                      </div>
                      <div>
                        <p className="text-sm text-gray-800 dark:text-slate-200">{a.text}</p>
                        <p className="text-xs text-gray-400">{formatTimeAgo(a.timestamp)}</p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>
          </div>
        </>
      ) : null}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[
          { to: '/open/plugins', icon: Puzzle, label: '插件市场', desc: '浏览与安装第三方插件' },
          { to: '/open/developer', icon: Code, label: '开发者门户', desc: 'API 密钥、Webhook 与 ISV 认证' },
          { to: '/open/app-builder', icon: Webhook, label: '应用构建器', desc: '低代码自定义业务应用' },
          { to: '/open/docs', icon: BookOpen, label: 'API 文档', desc: '接口文档与调用示例' },
        ].map((item) => (
          <Link
            key={item.to}
            to={item.to}
            className="group rounded-xl border border-gray-200 bg-white p-5 transition-all hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-md dark:border-slate-700 dark:bg-slate-800"
          >
            <item.icon className="mb-3 h-8 w-8 text-blue-500 transition-transform group-hover:scale-110" />
            <h3 className="font-semibold text-gray-900 dark:text-slate-100">{item.label}</h3>
            <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">{item.desc}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
