import { useMemo, useState } from 'react';
import { BellRing, CheckCircle2, ChevronDown, ChevronUp, CalendarClock } from 'lucide-react';
import { clsx } from 'clsx';
import { useCrmEnhanceStore, followUpUrgency, type FollowUpUrgency } from '../../stores/crmEnhance';
import type { CustomerRecord } from '../../types';

interface Props {
  customers: CustomerRecord[];
  onSelect: (customerId: number) => void;
}

const URGENCY_META: Record<Exclude<FollowUpUrgency, 'done' | 'later'>, { label: string; dot: string; text: string }> = {
  overdue: { label: '已逾期', dot: 'bg-red-500', text: 'text-red-600 dark:text-red-400' },
  today: { label: '今天', dot: 'bg-amber-500', text: 'text-amber-600 dark:text-amber-400' },
  soon: { label: '即将到期', dot: 'bg-blue-500', text: 'text-blue-600 dark:text-blue-400' },
};

/** 跟进提醒条：聚合逾期 / 今日 / 临期的跟进任务，置顶提醒销售 */
export default function RemindersBanner({ customers, onSelect }: Props) {
  const followUps = useCrmEnhanceStore((s) => s.followUps);
  const toggleDone = useCrmEnhanceStore((s) => s.toggleFollowUpDone);
  const [collapsed, setCollapsed] = useState(false);

  const nameOf = useMemo(() => {
    const map = new Map<number, string>();
    customers.forEach((c) => map.set(c.customer_id, c.display_name));
    return map;
  }, [customers]);

  const items = useMemo(() => {
    const rank: Record<string, number> = { overdue: 0, today: 1, soon: 2 };
    return Object.entries(followUps)
      .map(([id, fu]) => ({ id: Number(id), fu, urgency: followUpUrgency(fu) }))
      .filter((x) => x.urgency === 'overdue' || x.urgency === 'today' || x.urgency === 'soon')
      .filter((x) => nameOf.has(x.id))
      .sort((a, b) => rank[a.urgency!] - rank[b.urgency!] || a.fu.due_date.localeCompare(b.fu.due_date));
  }, [followUps, nameOf]);

  if (items.length === 0) return null;

  const counts = items.reduce(
    (acc, x) => {
      acc[x.urgency as 'overdue' | 'today' | 'soon'] += 1;
      return acc;
    },
    { overdue: 0, today: 0, soon: 0 } as Record<'overdue' | 'today' | 'soon', number>,
  );

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/70 dark:border-amber-500/30 dark:bg-amber-500/10">
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-100 text-amber-600 dark:bg-amber-500/20 dark:text-amber-300">
          <BellRing className="h-5 w-5" />
        </div>
        <div className="flex-1">
          <p className="text-sm font-semibold text-amber-800 dark:text-amber-200">
            待跟进提醒 · 共 {items.length} 条
          </p>
          <p className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-amber-700/80 dark:text-amber-300/80">
            {counts.overdue > 0 && <span>逾期 {counts.overdue}</span>}
            {counts.today > 0 && <span>今天 {counts.today}</span>}
            {counts.soon > 0 && <span>临期 {counts.soon}</span>}
          </p>
        </div>
        {collapsed ? <ChevronDown className="h-4 w-4 text-amber-600" /> : <ChevronUp className="h-4 w-4 text-amber-600" />}
      </button>

      {!collapsed && (
        <div className="space-y-1.5 px-3 pb-3">
          {items.map(({ id, fu, urgency }) => {
            const meta = URGENCY_META[urgency as 'overdue' | 'today' | 'soon'];
            return (
              <div
                key={id}
                className="flex items-center gap-3 rounded-lg bg-white px-3 py-2 shadow-sm dark:bg-slate-800"
              >
                <span className={clsx('h-2 w-2 shrink-0 rounded-full', meta.dot)} />
                <button onClick={() => onSelect(id)} className="min-w-0 flex-1 text-left">
                  <p className="truncate text-sm font-medium text-gray-700 hover:text-blue-600 dark:text-slate-200">
                    {nameOf.get(id)}
                  </p>
                  {fu.note && <p className="truncate text-xs text-gray-400 dark:text-slate-500">{fu.note}</p>}
                </button>
                <span className={clsx('flex shrink-0 items-center gap-1 text-xs font-medium', meta.text)}>
                  <CalendarClock className="h-3.5 w-3.5" />
                  {meta.label} · {fu.due_date.slice(5)}
                </span>
                <button
                  onClick={() => toggleDone(id)}
                  title="标记完成"
                  aria-label="标记完成"
                  className="shrink-0 rounded-md p-1 text-gray-300 hover:bg-green-50 hover:text-green-500 dark:hover:bg-green-500/10"
                >
                  <CheckCircle2 className="h-4 w-4" />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
