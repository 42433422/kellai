import { useState } from 'react';
import { Plus, Trash2, SlidersHorizontal, GripVertical } from 'lucide-react';
import { clsx } from 'clsx';
import Modal from './Modal';
import { useCrmEnhanceStore, type CustomFieldType } from '../../stores/crmEnhance';

const TYPE_LABEL: Record<CustomFieldType, string> = {
  text: '文本',
  number: '数字',
  select: '单选',
  date: '日期',
};

const inputCls =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100';

/** 自定义字段管理：查看 / 新增 / 删除字段定义 */
export default function CustomFieldsModal({ onClose }: { onClose: () => void }) {
  const fields = useCrmEnhanceStore((s) => s.customFields);
  const addCustomField = useCrmEnhanceStore((s) => s.addCustomField);
  const removeCustomField = useCrmEnhanceStore((s) => s.removeCustomField);

  const [label, setLabel] = useState('');
  const [type, setType] = useState<CustomFieldType>('text');
  const [optionsText, setOptionsText] = useState('');

  const canAdd = label.trim().length > 0 && (type !== 'select' || optionsText.trim().length > 0);

  const handleAdd = () => {
    if (!canAdd) return;
    const options = type === 'select' ? optionsText.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean) : undefined;
    addCustomField(label.trim(), type, options);
    setLabel('');
    setOptionsText('');
    setType('text');
  };

  return (
    <Modal
      title="自定义字段"
      subtitle="配置扩展字段，在新建/编辑客户时填写，并随客户一同导出"
      icon={<SlidersHorizontal className="h-5 w-5" />}
      size="lg"
      onClose={onClose}
      footer={
        <button
          onClick={onClose}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          完成
        </button>
      }
    >
      {/* 已有字段 */}
      <div className="mb-5">
        <p className="mb-2 text-xs font-medium text-gray-500 dark:text-slate-400">已有字段 ({fields.length})</p>
        {fields.length === 0 ? (
          <p className="rounded-lg border border-dashed border-gray-200 px-4 py-6 text-center text-sm text-gray-400 dark:border-slate-700">
            还没有自定义字段，在下方添加
          </p>
        ) : (
          <div className="space-y-2">
            {fields.map((f) => (
              <div
                key={f.key}
                className="flex items-center gap-3 rounded-lg border border-gray-200 bg-gray-50/60 px-3 py-2 dark:border-slate-700 dark:bg-slate-700/30"
              >
                <GripVertical className="h-4 w-4 shrink-0 text-gray-300 dark:text-slate-600" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-gray-700 dark:text-slate-200">{f.label}</p>
                  {f.type === 'select' && f.options && f.options.length > 0 && (
                    <p className="mt-0.5 truncate text-xs text-gray-400">选项：{f.options.join('、')}</p>
                  )}
                </div>
                <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-500 dark:bg-slate-700 dark:text-slate-300">
                  {TYPE_LABEL[f.type]}
                </span>
                <button
                  onClick={() => removeCustomField(f.key)}
                  className="shrink-0 rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-500/10"
                  aria-label={`删除字段 ${f.label}`}
                  title="删除字段"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 新增字段 */}
      <div className="rounded-xl border border-gray-200 p-4 dark:border-slate-700">
        <p className="mb-3 text-xs font-medium text-gray-500 dark:text-slate-400">新增字段</p>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500 dark:text-slate-400">字段名称</span>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="如：所属行业"
              className={inputCls}
              aria-label="字段名称"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500 dark:text-slate-400">字段类型</span>
            <select value={type} onChange={(e) => setType(e.target.value as CustomFieldType)} className={inputCls} aria-label="字段类型">
              {(Object.keys(TYPE_LABEL) as CustomFieldType[]).map((t) => (
                <option key={t} value={t}>
                  {TYPE_LABEL[t]}
                </option>
              ))}
            </select>
          </label>
        </div>
        {type === 'select' && (
          <label className="mt-3 block">
            <span className="mb-1 block text-xs text-gray-500 dark:text-slate-400">选项（逗号或换行分隔）</span>
            <textarea
              value={optionsText}
              onChange={(e) => setOptionsText(e.target.value)}
              rows={2}
              placeholder="互联网, 制造业, 零售电商"
              className={clsx(inputCls, 'resize-none')}
              aria-label="选项"
            />
          </label>
        )}
        <div className="mt-3 flex justify-end">
          <button
            onClick={handleAdd}
            disabled={!canAdd}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            <Plus className="h-4 w-4" /> 添加字段
          </button>
        </div>
      </div>
    </Modal>
  );
}
