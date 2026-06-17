import { useMemo, useState } from 'react';
import { FileSpreadsheet, Loader2, AlertTriangle, CheckCircle2, Users } from 'lucide-react';
import { clsx } from 'clsx';
import Modal from './Modal';
import { createCustomer } from '../../api/customer';
import {
  parseCsv,
  autoMapColumns,
  rowToProfile,
  IMPORT_TARGET_FIELDS,
  normalizePhone,
  normalizeEmail,
} from '../../utils/crm';
import type { CustomerRecord, CustomerProfileInput } from '../../types';

interface Props {
  csvText: string;
  existing: CustomerRecord[];
  onClose: () => void;
  onImported: (count: number) => void;
}

const selectCls =
  'w-full rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm text-gray-700 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-200';

const PREVIEW_LIMIT = 6;

interface PreparedRow {
  profile: CustomerProfileInput;
  empty: boolean;
  dup: boolean;
}

/** CSV 导入向导：表头映射 + 预览 + 查重 + 批量写入 */
export default function ImportWizard({ csvText, existing, onClose, onImported }: Props) {
  const parsed = useMemo(() => parseCsv(csvText), [csvText]);
  const [mapping, setMapping] = useState<Record<string, number>>(() => autoMapColumns(parsed.headers));
  const [skipDuplicates, setSkipDuplicates] = useState(true);
  const [importing, setImporting] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });

  // 现有客户的归一手机/邮箱集合（查重用）
  const existingKeys = useMemo(() => {
    const phones = new Set<string>();
    const emails = new Set<string>();
    existing.forEach((c) => {
      const p = normalizePhone(c.phone);
      const e = normalizeEmail(c.email);
      if (p) phones.add(p);
      if (e) emails.add(e);
    });
    return { phones, emails };
  }, [existing]);

  // 逐行预备：映射成 profile + 标记空行 / 疑似重复（含批内重复）
  const prepared = useMemo<PreparedRow[]>(() => {
    const seenPhones = new Set(existingKeys.phones);
    const seenEmails = new Set(existingKeys.emails);
    return parsed.rows.map((row) => {
      const profile = rowToProfile(row, mapping);
      const empty = !profile.name?.trim() && !profile.company?.trim();
      const p = normalizePhone(profile.phone);
      const e = normalizeEmail(profile.email);
      let dup = false;
      if (!empty) {
        if ((p && seenPhones.has(p)) || (e && seenEmails.has(e))) dup = true;
        if (p) seenPhones.add(p);
        if (e) seenEmails.add(e);
      }
      return { profile, empty, dup };
    });
  }, [parsed.rows, mapping, existingKeys]);

  const stats = useMemo(() => {
    const empty = prepared.filter((r) => r.empty).length;
    const dup = prepared.filter((r) => !r.empty && r.dup).length;
    const valid = prepared.length - empty;
    const willImport = prepared.filter((r) => !r.empty && (!skipDuplicates || !r.dup)).length;
    return { total: prepared.length, empty, dup, valid, willImport };
  }, [prepared, skipDuplicates]);

  const setCol = (key: string, idx: number) => {
    setMapping((m) => {
      const next = { ...m };
      if (idx < 0) delete next[key];
      else next[key] = idx;
      return next;
    });
  };

  const handleImport = async () => {
    const toImport = prepared.filter((r) => !r.empty && (!skipDuplicates || !r.dup));
    if (toImport.length === 0) return;
    setImporting(true);
    setProgress({ done: 0, total: toImport.length });
    let ok = 0;
    for (const r of toImport) {
      try {
        await createCustomer(r.profile);
        ok += 1;
      } catch {
        // 单条失败不阻断整体
      }
      setProgress((p) => ({ ...p, done: p.done + 1 }));
    }
    setImporting(false);
    onImported(ok);
  };

  const noFile = parsed.headers.length === 0 || parsed.rows.length === 0;

  return (
    <Modal
      title="导入客户"
      subtitle={noFile ? 'CSV 解析为空' : `检测到 ${parsed.rows.length} 行数据，${parsed.headers.length} 列`}
      icon={<FileSpreadsheet className="h-5 w-5" />}
      size="xl"
      onClose={importing ? () => {} : onClose}
      footer={
        <>
          <label className="mr-auto flex items-center gap-2 text-sm text-gray-600 dark:text-slate-300">
            <input
              type="checkbox"
              checked={skipDuplicates}
              onChange={(e) => setSkipDuplicates(e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 accent-blue-600"
            />
            跳过疑似重复（{stats.dup}）
          </label>
          <button
            onClick={onClose}
            disabled={importing}
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            取消
          </button>
          <button
            onClick={handleImport}
            disabled={importing || noFile || stats.willImport === 0}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {importing && <Loader2 className="h-4 w-4 animate-spin" />}
            {importing ? `导入中 ${progress.done}/${progress.total}` : `导入 ${stats.willImport} 位客户`}
          </button>
        </>
      }
    >
      {noFile ? (
        <p className="py-8 text-center text-sm text-gray-400">无法解析该 CSV 文件，请确认首行为表头且至少包含一行数据。</p>
      ) : (
        <div className="space-y-5">
          {/* 统计条 */}
          <div className="grid grid-cols-4 gap-3">
            <Stat label="总行数" value={stats.total} tone="gray" icon={<FileSpreadsheet className="h-4 w-4" />} />
            <Stat label="有效" value={stats.valid} tone="blue" icon={<Users className="h-4 w-4" />} />
            <Stat label="疑似重复" value={stats.dup} tone="amber" icon={<AlertTriangle className="h-4 w-4" />} />
            <Stat label="将导入" value={stats.willImport} tone="green" icon={<CheckCircle2 className="h-4 w-4" />} />
          </div>

          {/* 字段映射 */}
          <div>
            <p className="mb-2 text-xs font-medium text-gray-500 dark:text-slate-400">字段映射（自动识别，可手动调整）</p>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
              {IMPORT_TARGET_FIELDS.map((f) => (
                <div key={f.key} className="flex items-center gap-2">
                  <span className="w-16 shrink-0 text-right text-xs text-gray-500 dark:text-slate-400">{f.label}</span>
                  <select
                    value={mapping[f.key] ?? -1}
                    onChange={(e) => setCol(f.key, Number(e.target.value))}
                    className={selectCls}
                    aria-label={`${f.label} 对应列`}
                  >
                    <option value={-1}>— 忽略 —</option>
                    {parsed.headers.map((h, i) => (
                      <option key={i} value={i}>
                        {h || `第 ${i + 1} 列`}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          </div>

          {/* 预览 */}
          <div>
            <p className="mb-2 text-xs font-medium text-gray-500 dark:text-slate-400">
              预览（前 {Math.min(PREVIEW_LIMIT, prepared.length)} 行）
            </p>
            <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-slate-700">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50 text-left text-gray-500 dark:border-slate-700 dark:bg-slate-700/40 dark:text-slate-400">
                    <th className="px-3 py-2 font-medium">状态</th>
                    {IMPORT_TARGET_FIELDS.filter((f) => mapping[f.key] !== undefined).map((f) => (
                      <th key={f.key} className="px-3 py-2 font-medium">
                        {f.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {prepared.slice(0, PREVIEW_LIMIT).map((r, i) => (
                    <tr key={i} className="border-b border-gray-100 last:border-0 dark:border-slate-800">
                      <td className="px-3 py-2">
                        {r.empty ? (
                          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500 dark:bg-slate-700 dark:text-slate-400">空行</span>
                        ) : r.dup ? (
                          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700 dark:bg-amber-500/20 dark:text-amber-300">重复</span>
                        ) : (
                          <span className="rounded bg-green-100 px-1.5 py-0.5 text-[10px] text-green-700 dark:bg-green-500/20 dark:text-green-300">新增</span>
                        )}
                      </td>
                      {IMPORT_TARGET_FIELDS.filter((f) => mapping[f.key] !== undefined).map((f) => (
                        <td key={f.key} className="max-w-[160px] truncate px-3 py-2 text-gray-700 dark:text-slate-300">
                          {String((r.profile as Record<string, unknown>)[f.key] ?? '') || '—'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

function Stat({ label, value, tone, icon }: { label: string; value: number; tone: 'gray' | 'blue' | 'amber' | 'green'; icon: React.ReactNode }) {
  const toneCls: Record<string, string> = {
    gray: 'text-gray-500 dark:text-slate-400',
    blue: 'text-blue-600 dark:text-blue-400',
    amber: 'text-amber-600 dark:text-amber-400',
    green: 'text-green-600 dark:text-green-400',
  };
  return (
    <div className="rounded-lg border border-gray-200 px-3 py-2 dark:border-slate-700">
      <div className={clsx('flex items-center gap-1.5 text-xs', toneCls[tone])}>
        {icon}
        {label}
      </div>
      <p className="mt-1 text-lg font-semibold text-gray-800 dark:text-slate-100">{value}</p>
    </div>
  );
}
