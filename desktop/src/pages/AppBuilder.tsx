import { useState } from 'react';
import { Layout, Plus, Trash2, Eye, Send, Loader2, CheckCircle2 } from 'lucide-react';
import { clsx } from 'clsx';
import Loading from '../components/Loading';
import { useApiQuery, useApiMutation } from '../hooks/useApiQuery';
import { getAppTemplates, submitAppReview } from '../api/openPlatform';
import { toastStore } from '../stores/toast';
import type { AppTemplate, AppTemplateField } from '../types';

const FIELD_TYPES = [
  { id: 'text', label: '单行文本' },
  { id: 'textarea', label: '多行文本' },
  { id: 'number', label: '数字' },
  { id: 'select', label: '下拉选择' },
  { id: 'date', label: '日期' },
];

export default function AppBuilder() {
  const [selected, setSelected] = useState<AppTemplate | null>(null);
  const [fields, setFields] = useState<AppTemplateField[]>([]);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [newFieldLabel, setNewFieldLabel] = useState('');
  const [newFieldType, setNewFieldType] = useState('text');
  const [submitted, setSubmitted] = useState(false);

  const query = useApiQuery<AppTemplate[]>(['open', 'templates'], () => getAppTemplates());

  const reviewMutation = useApiMutation(
    () => submitAppReview(selected?.name ?? '自定义应用'),
    {
      onSuccess: () => {
        setSubmitted(true);
        toastStore.success('应用已提交审核');
      },
    }
  );

  const selectTemplate = (t: AppTemplate) => {
    setSelected(t);
    setFields([...t.fields]);
    setFormValues({});
    setSubmitted(false);
  };

  const addField = () => {
    if (!newFieldLabel.trim()) return;
    const key = `field_${Date.now()}`;
    setFields((prev) => [...prev, { key, label: newFieldLabel.trim(), type: newFieldType, options: newFieldType === 'select' ? ['选项一', '选项二'] : undefined }]);
    setNewFieldLabel('');
  };

  const removeField = (key: string) => setFields((prev) => prev.filter((f) => f.key !== key));

  const renderInput = (f: AppTemplateField) => {
    const common = 'w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100';
    const val = formValues[f.key] ?? '';
    const onChange = (v: string) => setFormValues({ ...formValues, [f.key]: v });
    if (f.type === 'select') {
      return (
        <select value={val} onChange={(e) => onChange(e.target.value)} className={common}>
          <option value="">请选择</option>
          {(f.options ?? []).map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      );
    }
    if (f.type === 'textarea') {
      return <textarea value={val} onChange={(e) => onChange(e.target.value)} rows={3} placeholder={f.placeholder} className={common} />;
    }
    return <input type={f.type === 'number' ? 'number' : f.type === 'date' ? 'date' : 'text'} value={val} onChange={(e) => onChange(e.target.value)} placeholder={f.placeholder} className={common} />;
  };

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">应用构建器</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">低代码搭建自定义业务应用，所见即所得</p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        {/* 模板列表 */}
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">选择模板</h3>
          {query.isLoading ? (
            <Loading variant="skeleton" rows={3} />
          ) : (
            (query.data ?? []).map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => selectTemplate(t)}
                className={clsx(
                  'flex w-full items-start gap-2 rounded-lg border p-3 text-left text-sm transition-colors',
                  selected?.id === t.id ? 'border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-500/10' : 'border-gray-200 hover:border-gray-300 dark:border-slate-700'
                )}
              >
                <span className="text-lg">{t.icon ?? '📋'}</span>
                <div>
                  <p className="font-medium text-gray-900 dark:text-slate-100">{t.name}</p>
                  <p className="text-xs text-gray-400">{t.category} · {t.fields.length} 字段</p>
                </div>
              </button>
            ))
          )}
        </div>

        {/* 表单构建 */}
        <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800 lg:col-span-2">
          {selected ? (
            <>
              <div className="mb-4 flex items-center gap-2">
                <span className="text-xl">{selected.icon ?? '📋'}</span>
                <div>
                  <h3 className="font-semibold text-gray-900 dark:text-slate-100">{selected.name}</h3>
                  <p className="text-xs text-gray-400">{selected.description}</p>
                </div>
              </div>
              <div className="space-y-4">
                {fields.map((f) => (
                  <div key={f.key}>
                    <div className="mb-1 flex items-center justify-between">
                      <label className="text-sm font-medium text-gray-700 dark:text-slate-200">
                        {f.label}
                        {f.required && <span className="ml-0.5 text-red-500">*</span>}
                        <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-400 dark:bg-slate-700">{FIELD_TYPES.find((t) => t.id === f.type)?.label ?? f.type}</span>
                      </label>
                      <button type="button" onClick={() => removeField(f.key)} className="text-gray-300 hover:text-red-500">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    {renderInput(f)}
                  </div>
                ))}
              </div>

              {/* 添加字段 */}
              <div className="mt-4 flex gap-2 border-t border-gray-100 pt-4 dark:border-slate-700">
                <input
                  value={newFieldLabel}
                  onChange={(e) => setNewFieldLabel(e.target.value)}
                  placeholder="新字段名称"
                  className="flex-1 rounded-lg border px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                />
                <select
                  value={newFieldType}
                  onChange={(e) => setNewFieldType(e.target.value)}
                  className="rounded-lg border px-2 py-2 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                >
                  {FIELD_TYPES.map((t) => (
                    <option key={t.id} value={t.id}>{t.label}</option>
                  ))}
                </select>
                <button type="button" onClick={addField} className="flex items-center gap-1 rounded-lg border px-3 py-2 text-sm hover:bg-gray-50 dark:border-slate-600 dark:hover:bg-slate-700">
                  <Plus className="h-4 w-4" /> 字段
                </button>
              </div>

              <button
                type="button"
                onClick={() => reviewMutation.mutate()}
                disabled={reviewMutation.isPending || submitted}
                className="mt-4 flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {submitted ? <CheckCircle2 className="h-4 w-4" /> : reviewMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {submitted ? '已提交审核' : '发布应用'}
              </button>
            </>
          ) : (
            <div className="flex h-full min-h-[16rem] flex-col items-center justify-center text-center text-sm text-gray-400">
              <Layout className="mb-2 h-8 w-8 text-gray-300 dark:text-slate-600" />
              请选择左侧模板开始构建
            </div>
          )}
        </div>

        {/* 实时预览 */}
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-5 dark:border-slate-700 dark:bg-slate-900">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-slate-200">
            <Eye className="h-4 w-4" /> 实时预览
          </h3>
          {selected ? (
            <div className="space-y-2 text-sm">
              {fields.map((f) => (
                <div key={f.key} className="flex justify-between gap-2 border-b border-gray-100 py-1.5 dark:border-slate-700/50">
                  <span className="text-gray-500 dark:text-slate-400">{f.label}</span>
                  <span className="text-right font-medium text-gray-900 dark:text-slate-100">{formValues[f.key] || <span className="text-gray-300">—</span>}</span>
                </div>
              ))}
              <pre className="mt-3 overflow-x-auto rounded-lg bg-gray-900 p-3 text-[11px] text-green-300">{JSON.stringify(formValues, null, 2)}</pre>
            </div>
          ) : (
            <p className="text-sm text-gray-400">填写表单后这里实时预览</p>
          )}
        </div>
      </div>
    </div>
  );
}
