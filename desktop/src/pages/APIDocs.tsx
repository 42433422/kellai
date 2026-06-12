import { useApiQuery } from '../hooks/useApiQuery';
import { getAPIDocs } from '../api/openPlatform';

export default function APIDocs() {
  const query = useApiQuery(['open', 'docs'], () => getAPIDocs());

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">API 文档</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">客来来开放平台接口参考</p>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white dark:border-slate-700 dark:bg-slate-800">
        <div className="border-b px-6 py-4 dark:border-slate-700">
          <h2 className="font-semibold">REST API</h2>
          <p className="text-sm text-gray-500">Base URL: http://127.0.0.1:8790/api/kellai</p>
        </div>
        <div className="divide-y dark:divide-slate-700">
          {(query.data?.endpoints ?? []).map((ep, i) => (
            <div key={i} className="flex items-start gap-4 px-6 py-4">
              <span
                className={`shrink-0 rounded px-2 py-0.5 font-mono text-xs font-bold ${
                  ep.method === 'GET'
                    ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-300'
                    : 'bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300'
                }`}
              >
                {ep.method}
              </span>
              <div>
                <code className="text-sm font-medium">{ep.path}</code>
                <p className="mt-1 text-sm text-gray-600 dark:text-slate-400">{ep.description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-gray-50 p-6 dark:border-slate-700 dark:bg-slate-900">
        <h3 className="mb-2 font-semibold">认证</h3>
        <p className="text-sm text-gray-600 dark:text-slate-400">
          所有 API 请求需在 Header 中携带 <code className="rounded bg-gray-200 px-1 dark:bg-slate-700">Authorization: Bearer &lt;token&gt;</code>
        </p>
      </div>
    </div>
  );
}
