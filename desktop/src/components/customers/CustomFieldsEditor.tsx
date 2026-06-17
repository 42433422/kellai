import { useCrmEnhanceStore } from '../../stores/crmEnhance';

interface Props {
  values: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}

const inputCls =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800 outline-none transition-colors focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100';

/** 在客户表单中渲染并编辑「自定义字段」取值（schema 来自 store） */
export default function CustomFieldsEditor({ values, onChange }: Props) {
  const fields = useCrmEnhanceStore((s) => s.customFields);
  if (fields.length === 0) return null;

  const set = (key: string, v: string) => onChange({ ...values, [key]: v });

  return (
    <div className="grid grid-cols-2 gap-4">
      {fields.map((f) => (
        <label key={f.key} className="block">
          <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-slate-400">{f.label}</span>
          {f.type === 'select' ? (
            <select value={values[f.key] ?? ''} onChange={(e) => set(f.key, e.target.value)} className={inputCls} aria-label={f.label}>
              <option value="">未选择</option>
              {(f.options ?? []).map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          ) : (
            <input
              type={f.type === 'number' ? 'number' : f.type === 'date' ? 'date' : 'text'}
              value={values[f.key] ?? ''}
              onChange={(e) => set(f.key, e.target.value)}
              className={inputCls}
              aria-label={f.label}
            />
          )}
        </label>
      ))}
    </div>
  );
}
