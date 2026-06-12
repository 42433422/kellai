import { useState } from 'react';
import { Layout, Plus } from 'lucide-react';
import { useApiQuery } from '../hooks/useApiQuery';
import { getAppTemplates } from '../api/openPlatform';
import type { AppTemplate } from '../types';

export default function AppBuilder() {
  const [selected, setSelected] = useState<AppTemplate | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});

  const query = useApiQuery<AppTemplate[]>(['open', 'templates'], () => getAppTemplates());

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">应用构建器</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">低代码自定义业务应用</p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">模板</h3>
          {(query.data ?? []).map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => { setSelected(t); setFormValues({}); }}
              className={`flex w-full items-center gap-2 rounded-lg border p-3 text-left text-sm ${
                selected?.id === t.id ? 'border-blue-500 bg-blue-50 dark:bg-blue-500/10' : 'dark:border-slate-700'
              }`}
            >
              <Layout className="h-4 w-4" />
              {t.name}
            </button>
          ))}
        </div>

        <div className="lg:col-span-2 rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
          {selected ? (
            <>
              <h3 className="mb-4 font-semibold">{selected.name}</h3>
              <p className="mb-4 text-sm text-gray-500">{selected.description}</p>
              {selected.fields.map((f) => (
                <div key={f.key} className="mb-4">
                  <label className="mb-1 block text-sm font-medium">{f.label}</label>
                  <input
                    value={formValues[f.key] ?? ''}
                    onChange={(e) => setFormValues({ ...formValues, [f.key]: e.target.value })}
                    className="w-full rounded-lg border px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900"
                  />
                </div>
              ))}
              <button
                type="button"
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
              >
                <Plus className="h-4 w-4" /> 保存应用
              </button>
            </>
          ) : (
            <p className="text-gray-500">请选择一个模板开始构建</p>
          )}
        </div>
      </div>
    </div>
  );
}
