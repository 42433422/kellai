import { useState } from 'react';
import { CalendarClock, Trash2 } from 'lucide-react';
import { clsx } from 'clsx';
import Modal from './Modal';
import { useCrmEnhanceStore } from '../../stores/crmEnhance';
import type { CustomerRecord } from '../../types';
import { toastStore } from '../../stores/toast';

const inputCls =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100';

function todayPlus(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

const QUICK = [
  { label: '今天', days: 0 },
  { label: '明天', days: 1 },
  { label: '3 天后', days: 3 },
  { label: '下周', days: 7 },
];

/** 为单个客户设置 / 修改 / 清除跟进任务 */
export default function FollowUpModal({ customer, onClose }: { customer: CustomerRecord; onClose: () => void }) {
  const existing = useCrmEnhanceStore((s) => s.followUps[customer.customer_id]);
  const setFollowUp = useCrmEnhanceStore((s) => s.setFollowUp);

  const [dueDate, setDueDate] = useState(existing?.due_date ?? todayPlus(1));
  const [note, setNote] = useState(existing?.note ?? '');
  const [done, setDone] = useState(existing?.done ?? false);

  const save = () => {
    if (!dueDate) {
      toastStore.error('请选择跟进日期');
      return;
    }
    setFollowUp(customer.customer_id, {
      due_date: dueDate,
      note: note.trim(),
      done,
      created_at: existing?.created_at ?? new Date().toISOString(),
    });
    toastStore.success('跟进任务已保存');
    onClose();
  };

  const clear = () => {
    setFollowUp(customer.customer_id, null);
    toastStore.success('已清除跟进任务');
    onClose();
  };

  return (
    <Modal
      title="设置跟进"
      subtitle={`客户：${customer.display_name}`}
      icon={<CalendarClock className="h-5 w-5" />}
      size="md"
      onClose={onClose}
      footer={
        <>
          {existing && (
            <button
              onClick={clear}
              className="mr-auto inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-2 text-sm text-red-600 hover:bg-red-50 dark:border-red-500/30 dark:text-red-400 dark:hover:bg-red-500/10"
            >
              <Trash2 className="h-4 w-4" /> 清除
            </button>
          )}
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            取消
          </button>
          <button onClick={save} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
            保存
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <span className="mb-1.5 block text-xs font-medium text-gray-500 dark:text-slate-400">跟进日期</span>
          <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} className={inputCls} aria-label="跟进日期" />
          <div className="mt-2 flex flex-wrap gap-2">
            {QUICK.map((q) => (
              <button
                key={q.label}
                onClick={() => setDueDate(todayPlus(q.days))}
                className={clsx(
                  'rounded-full border px-2.5 py-1 text-xs transition-colors',
                  dueDate === todayPlus(q.days)
                    ? 'border-blue-400 bg-blue-50 text-blue-600 dark:border-blue-500 dark:bg-blue-500/20 dark:text-blue-300'
                    : 'border-gray-200 text-gray-500 hover:bg-gray-50 dark:border-slate-600 dark:text-slate-400 dark:hover:bg-slate-700',
                )}
              >
                {q.label}
              </button>
            ))}
          </div>
        </div>

        <label className="block">
          <span className="mb-1.5 block text-xs font-medium text-gray-500 dark:text-slate-400">跟进事项</span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            placeholder="如：回访确认需求、发送报价方案、约下次会议…"
            className={clsx(inputCls, 'resize-none')}
            aria-label="跟进事项"
          />
        </label>

        <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-slate-300">
          <input
            type="checkbox"
            checked={done}
            onChange={(e) => setDone(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 accent-blue-600"
          />
          标记为已完成
        </label>
      </div>
    </Modal>
  );
}
