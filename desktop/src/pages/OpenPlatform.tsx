import { Link } from 'react-router-dom';
import { Globe, Key, Puzzle, Code, BookOpen, Webhook } from 'lucide-react';
import KpiGrid from '../components/KpiGrid';
import { useApiQuery } from '../hooks/useApiQuery';
import { getAPIKeys, getPlugins, getISVPartners } from '../api/openPlatform';

export default function OpenPlatform() {
  const keysQuery = useApiQuery(['open', 'keys'], () => getAPIKeys());
  const pluginsQuery = useApiQuery(['open', 'plugins'], () => getPlugins());
  const isvQuery = useApiQuery(['open', 'isv'], () => getISVPartners());

  const keys = keysQuery.data ?? [];
  const plugins = pluginsQuery.data ?? [];
  const isv = isvQuery.data ?? [];

  return (
    <div className="space-y-6" data-tour="open-platform-home">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">开放平台</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">构建客来来生态，连接开发者与合作伙伴</p>
      </div>

      <KpiGrid
        cols={3}
        items={[
          { title: 'API 密钥', value: keys.length, icon: Key },
          { title: '插件数量', value: plugins.length, icon: Puzzle },
          { title: 'ISV 伙伴', value: isv.length, icon: Globe },
        ]}
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {[
          { to: '/open/plugins', icon: Puzzle, label: '插件市场', desc: '浏览与安装第三方插件' },
          { to: '/open/developer', icon: Code, label: '开发者门户', desc: 'ISV 认证与社区' },
          { to: '/open/app-builder', icon: Webhook, label: '应用构建器', desc: '低代码自定义业务应用' },
          { to: '/open/docs', icon: BookOpen, label: 'API 文档', desc: '接口文档与沙箱' },
        ].map((item) => (
          <Link
            key={item.to}
            to={item.to}
            className="rounded-xl border border-gray-200 bg-white p-5 transition-shadow hover:shadow-md dark:border-slate-700 dark:bg-slate-800"
          >
            <item.icon className="mb-3 h-8 w-8 text-blue-500" />
            <h3 className="font-semibold text-gray-900 dark:text-slate-100">{item.label}</h3>
            <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">{item.desc}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
