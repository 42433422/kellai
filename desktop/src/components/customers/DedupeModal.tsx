import { useMemo, useState } from 'react';
import { Copy, Loader2, Merge, ShieldCheck, Building2, Mail, Phone } from 'lucide-react';
import { clsx } from 'clsx';
import Modal from './Modal';
import { updateCustomer, deleteCustomer } from '../../api/customer';
import { findDuplicateGroups, buildMergedProfile } from '../../utils/crm';
import { useCrmEnhanceStore } from '../../stores/crmEnhance';
import { toastStore } from '../../stores/toast';
import type { CustomerRecord } from '../../types';

interface Props {
  customers: CustomerRecord[];
  onClose: () => void;
  onMerged: () => void;
}

/** 客户查重 + 合并：按手机/邮箱/同名同公司聚合，选主记录后合并补全并删除其余 */
export default function DedupeModal({ customers, onClose, onMerged }: Props) {
  const groups = useMemo(() => findDuplicateGroups(customers), [customers]);
  const mergeCustomValues = useCrmEnhanceStore((s) => s.mergeCustomValues);
  const followUps = useCrmEnhanceStore((s) => s.followUps);
  const setFollowUp = useCrmEnhanceStore((s) => s.setFollowUp);

  // 组签名（成员 id 排序拼接）：稳定 key，刷新后索引漂移也不误判
  const sigOf = (members: CustomerRecord[]) =>
    members.map((m) => m.customer_id).sort((a, b) => a - b).join('-');

  // 每组选中的主记录 id（默认各组首位）
  const [primaryMap, setPrimaryMap] = useState<Record<string, number>>({});
  const [mergingKey, setMergingKey] = useState<string | null>(null);
  const [doneKeys, setDoneKeys] = useState<Set<string>>(new Set());

  const visibleGroups = groups.filter((g) => !doneKeys.has(sigOf(g.members)));

  const handleMerge = async (sig: string) => {
    const group = groups.find((g) => sigOf(g.members) === sig);
    if (!group) return;
    const primaryId = primaryMap[sig] ?? group.members[0].customer_id;
    const primary = group.members.find((m) => m.customer_id === primaryId) ?? group.members[0];
    const others = group.members.filter((m) => m.customer_id !== primary.customer_id);

    setMergingKey(sig);
    try {
      const merged = buildMergedProfile(primary, others);
      await updateCustomer(primary.customer_id, merged);

      // 迁移自定义字段值 + 跟进任务到主记录
      for (const o of others) {
        mergeCustomValues(o.customer_id, primary.customer_id);
        if (!followUps[primary.customer_id] && followUps[o.customer_id]) {
          setFollowUp(primary.customer_id, followUps[o.customer_id]);
        }
        setFollowUp(o.customer_id, null);
        await deleteCustomer(o.customer_id);
      }

      toastStore.success(`已合并 ${others.length + 1} 条为 1 条`);
      setDoneKeys((prev) => new Set(prev).add(sig));
      onMerged();
    } catch {
      toastStore.error('合并失败，请重试');
    } finally {
      setMergingKey(null);
    }
  };

  return (
    <Modal
      title="查找重复客户"
      subtitle={groups.length === 0 ? '未发现重复客户' : `发现 ${groups.length} 组疑似重复`}
      icon={<Copy className="h-5 w-5" />}
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
      {visibleGroups.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-10 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-50 text-green-500 dark:bg-green-500/10">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <p className="text-sm font-medium text-gray-700 dark:text-slate-200">客户数据很干净</p>
          <p className="text-xs text-gray-400">按手机、邮箱、同名同公司检测，未发现重复记录</p>
        </div>
      ) : (
        <div className="space-y-4">
          {groups.map((group) => {
            const sig = sigOf(group.members);
            if (doneKeys.has(sig)) return null;
            const primaryId = primaryMap[sig] ?? group.members[0].customer_id;
            const merging = mergingKey === sig;
            return (
              <div key={sig} className="rounded-xl border border-gray-200 p-3 dark:border-slate-700">
                <div className="mb-2 flex items-center justify-between">
                  <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
                    依据：{group.reason} · {group.members.length} 条
                  </span>
                  <button
                    onClick={() => handleMerge(sig)}
                    disabled={merging}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {merging ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Merge className="h-3.5 w-3.5" />}
                    合并为选中主记录
                  </button>
                </div>
                <div className="space-y-1.5">
                  {group.members.map((m) => (
                    <label
                      key={m.customer_id}
                      className={clsx(
                        'flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 transition-colors',
                        m.customer_id === primaryId
                          ? 'border-blue-400 bg-blue-50/60 dark:border-blue-500 dark:bg-blue-500/10'
                          : 'border-gray-200 hover:bg-gray-50 dark:border-slate-700 dark:hover:bg-slate-700/40',
                      )}
                    >
                      <input
                        type="radio"
                        name={`primary-${sig}`}
                        checked={m.customer_id === primaryId}
                        onChange={() => setPrimaryMap((p) => ({ ...p, [sig]: m.customer_id }))}
                        className="h-4 w-4 accent-blue-600"
                      />
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 text-xs font-medium text-white">
                        {(m.display_name || '?').charAt(0)}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-gray-800 dark:text-slate-100">
                          {m.display_name}
                          {m.customer_id === primaryId && (
                            <span className="ml-2 rounded bg-blue-100 px-1.5 py-0.5 text-[10px] text-blue-600 dark:bg-blue-500/20 dark:text-blue-300">主记录</span>
                          )}
                        </p>
                        <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-gray-400 dark:text-slate-500">
                          {m.company && (
                            <span className="flex items-center gap-1">
                              <Building2 className="h-3 w-3" />
                              {m.company}
                            </span>
                          )}
                          {m.phone && (
                            <span className="flex items-center gap-1">
                              <Phone className="h-3 w-3" />
                              {m.phone}
                            </span>
                          )}
                          {m.email && (
                            <span className="flex items-center gap-1 truncate">
                              <Mail className="h-3 w-3" />
                              {m.email}
                            </span>
                          )}
                        </div>
                      </div>
                      <span className="shrink-0 text-xs text-gray-400">{m.stage_label}</span>
                    </label>
                  ))}
                </div>
                <p className="mt-2 text-[11px] text-gray-400 dark:text-slate-500">
                  合并后：保留主记录，空缺字段由其余记录补全，标签 / 渠道取并集，其余记录将被删除。
                </p>
              </div>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
