import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  Filter,
  Plus,
  Download,
  Upload,
  LayoutGrid,
  List as ListIcon,
  RefreshCw,
  Users,
  Trash2,
  Pencil,
  Eye,
  X,
  Building2,
  Mail,
  Phone,
  ArrowUpDown,
  TrendingUp,
  UserPlus,
  Loader2,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Copy,
  SlidersHorizontal,
  CalendarClock,
} from 'lucide-react';
import { clsx } from 'clsx';
import ChannelLogo from '../components/ChannelLogo';
import KpiGrid, { type KpiItem } from '../components/KpiGrid';
import Empty from '../components/Empty';
import ImportWizard from '../components/customers/ImportWizard';
import DedupeModal from '../components/customers/DedupeModal';
import CustomFieldsModal from '../components/customers/CustomFieldsModal';
import FollowUpModal from '../components/customers/FollowUpModal';
import RemindersBanner from '../components/customers/RemindersBanner';
import CustomFieldsEditor from '../components/customers/CustomFieldsEditor';
import { useApiQuery, useApiMutation, useQueryClient } from '../hooks/useApiQuery';
import { toastStore } from '../stores/toast';
import { useCrmEnhanceStore, followUpUrgency } from '../stores/crmEnhance';
import { formatTimeAgo } from '../utils/format';
import {
  getCustomers,
  createCustomer,
  updateCustomer,
  deleteCustomer,
  batchCustomers,
} from '../api/customer';
import type { CustomerRecord, CustomerListResponse, CustomerProfileInput } from '../types';
import type { CustomFieldDef, FollowUp } from '../stores/crmEnhance';

/* ========================= 常量 ========================= */

/** 阶段徽标配色（兼容前端漏斗 ID 与后端 pipeline ID 两套命名） */
const STAGE_COLOR: Record<string, string> = {
  no_contact: 'bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-slate-300',
  idle: 'bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-slate-300',
  connected: 'bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300',
  requirement: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-500/20 dark:text-cyan-300',
  intake: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-500/20 dark:text-cyan-300',
  submitted: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300',
  intake_done: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300',
  quoted: 'bg-purple-100 text-purple-700 dark:bg-purple-500/20 dark:text-purple-300',
  negotiating: 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300',
  pending_sign: 'bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-300',
  contract_pending: 'bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-300',
  signed: 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-300',
  delivering: 'bg-teal-100 text-teal-700 dark:bg-teal-500/20 dark:text-teal-300',
  delivered: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300',
};

function stageColor(id: string): string {
  return STAGE_COLOR[id] ?? 'bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-slate-300';
}

/** 已成交/已结束的阶段（用于统计"转化中"） */
const CLOSED_STAGES = new Set(['delivered']);
const COLD_STAGES = new Set(['no_contact', 'idle']);

/** 常用渠道选项（筛选 + 表单复选） */
const CHANNEL_OPTIONS: { value: string; label: string }[] = [
  { value: 'wework', label: '企微' },
  { value: 'phone', label: '电话' },
  { value: 'douyin', label: '抖音' },
  { value: 'miniapp', label: '小程序' },
  { value: 'email', label: '邮件' },
  { value: 'sms', label: '短信' },
  { value: 'web', label: '网页' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'telegram', label: 'Telegram' },
  { value: 'line', label: 'LINE' },
];

type SortKey = 'updated_at' | 'created_at' | 'ai_score' | 'display_name';

const PAGE_SIZE_OPTIONS = [10, 20, 50];

/* ========================= 工具函数 ========================= */

function scoreColorText(score: number): string {
  if (score < 0.4) return 'text-red-500';
  if (score < 0.7) return 'text-amber-500';
  return 'text-green-500';
}

function scoreGradient(score: number): string {
  if (score < 0.4) return 'linear-gradient(90deg,#ef4444,#f97316)';
  if (score < 0.7) return 'linear-gradient(90deg,#f97316,#eab308)';
  return 'linear-gradient(90deg,#eab308,#22c55e)';
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_RE = /^[\d\s+\-()]{6,20}$/;

/** 导出客户为 CSV（带 UTF-8 BOM，Excel 友好），含自定义字段列 */
function exportCustomersCsv(
  rows: CustomerRecord[],
  customFields: CustomFieldDef[] = [],
  customValues: Record<number, Record<string, string>> = {},
) {
  const headers = [
    '客户名称', '公司', '邮箱', '电话', '阶段', '渠道', 'AI评分', '标签', '负责人', '来源', '更新时间',
    ...customFields.map((f) => f.label),
  ];
  const escape = (v: unknown) => {
    const s = String(v ?? '');
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = rows.map((c) => {
    const cv = customValues[c.customer_id] ?? {};
    return [
      c.display_name,
      c.company || '',
      c.email || '',
      c.phone || '',
      c.stage_label,
      (c.channel_sources || []).join(' / '),
      Math.round((c.ai_score || 0) * 100),
      [...(c.tags || []), ...(c.ai_tags || [])].join(' '),
      c.owner || '',
      c.source || '',
      c.updated_at || '',
      ...customFields.map((f) => cv[f.key] || ''),
    ]
      .map(escape)
      .join(',');
  });
  const csv = '\uFEFF' + [headers.join(','), ...lines].join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `客户列表_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/* ========================= 子组件：标签输入 ========================= */

function TagInput({ tags, onChange }: { tags: string[]; onChange: (next: string[]) => void }) {
  const [input, setInput] = useState('');
  const add = (raw: string) => {
    const t = raw.trim();
    if (t && !tags.includes(t)) onChange([...tags, t]);
    setInput('');
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-gray-300 px-2 py-1.5 dark:border-slate-600">
      {tags.map((t) => (
        <span
          key={t}
          className="flex items-center gap-1 rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-600 dark:bg-blue-500/20 dark:text-blue-300"
        >
          {t}
          <button type="button" onClick={() => onChange(tags.filter((x) => x !== t))} aria-label={`移除标签 ${t}`}>
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            add(input);
          } else if (e.key === 'Backspace' && !input && tags.length) {
            onChange(tags.slice(0, -1));
          }
        }}
        onBlur={() => input && add(input)}
        placeholder={tags.length ? '' : '输入后回车添加标签'}
        className="min-w-[120px] flex-1 bg-transparent text-sm text-gray-700 outline-none placeholder:text-gray-400 dark:text-slate-200"
        aria-label="标签输入"
      />
    </div>
  );
}

/* ========================= 子组件：客户表单弹窗 ========================= */

interface FormModalProps {
  initial: CustomerRecord | null;
  stageDefs: { id: string; label: string }[];
  submitting: boolean;
  onClose: () => void;
  onSubmit: (data: CustomerProfileInput, customValues: Record<string, string>) => void;
}

function CustomerFormModal({ initial, stageDefs, submitting, onClose, onSubmit }: FormModalProps) {
  const [form, setForm] = useState<CustomerProfileInput>({
    name: initial?.name ?? '',
    company: initial?.company ?? '',
    email: initial?.email ?? '',
    phone: initial?.phone ?? '',
    owner: initial?.owner ?? '',
    source: initial?.source ?? '',
    note: initial?.note ?? '',
    stage: initial?.stage ?? stageDefs[0]?.id ?? '',
    tags: initial?.tags ?? [],
    channel_sources: initial?.channel_sources ?? [],
  });
  // 自定义字段取值（编辑态从 store 读取既有值；新建态为空）
  const [customValues, setCustomValues] = useState<Record<string, string>>(() =>
    initial ? useCrmEnhanceStore.getState().customValues[initial.customer_id] ?? {} : {},
  );
  const hasCustomFields = useCrmEnhanceStore((s) => s.customFields.length > 0);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const set = <K extends keyof CustomerProfileInput>(k: K, v: CustomerProfileInput[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const validate = (): boolean => {
    const e: Record<string, string> = {};
    if (!form.name?.trim() && !form.company?.trim()) e.name = '客户姓名与公司至少填写一项';
    if (form.email?.trim() && !EMAIL_RE.test(form.email.trim())) e.email = '邮箱格式不正确';
    if (form.phone?.trim() && !PHONE_RE.test(form.phone.trim())) e.phone = '电话格式不正确';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = () => {
    if (!validate()) return;
    onSubmit(form, customValues);
  };

  const toggleChannel = (ch: string) => {
    const cur = form.channel_sources ?? [];
    set('channel_sources', cur.includes(ch) ? cur.filter((c) => c !== ch) : [...cur, ch]);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onMouseDown={onClose}>
      <div
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-xl dark:bg-slate-800"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-800 dark:text-slate-100">
            {initial ? '编辑客户' : '新建客户'}
          </h2>
          <button onClick={onClose} aria-label="关闭" className="rounded p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-700">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="客户姓名" error={errors.name}>
              <input
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder="如：张伟"
                className={inputCls(!!errors.name)}
                aria-label="客户姓名"
              />
            </Field>
            <Field label="公司名称">
              <input
                value={form.company}
                onChange={(e) => set('company', e.target.value)}
                placeholder="如：Acme 科技"
                className={inputCls(false)}
                aria-label="公司名称"
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field label="邮箱" error={errors.email}>
              <input
                value={form.email}
                onChange={(e) => set('email', e.target.value)}
                placeholder="name@company.com"
                className={inputCls(!!errors.email)}
                aria-label="邮箱"
              />
            </Field>
            <Field label="电话" error={errors.phone}>
              <input
                value={form.phone}
                onChange={(e) => set('phone', e.target.value)}
                placeholder="13800138000"
                className={inputCls(!!errors.phone)}
                aria-label="电话"
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field label="阶段">
              <select
                value={form.stage}
                onChange={(e) => set('stage', e.target.value)}
                className={inputCls(false)}
                aria-label="阶段"
              >
                {stageDefs.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="负责人">
              <input
                value={form.owner}
                onChange={(e) => set('owner', e.target.value)}
                placeholder="销售负责人"
                className={inputCls(false)}
                aria-label="负责人"
              />
            </Field>
          </div>

          <Field label="来源">
            <input
              value={form.source}
              onChange={(e) => set('source', e.target.value)}
              placeholder="如：官网咨询 / 转介绍 / 广告投放"
              className={inputCls(false)}
              aria-label="来源"
            />
          </Field>

          <Field label="渠道">
            <div className="flex flex-wrap gap-2">
              {CHANNEL_OPTIONS.map((ch) => {
                const active = (form.channel_sources ?? []).includes(ch.value);
                return (
                  <button
                    key={ch.value}
                    type="button"
                    onClick={() => toggleChannel(ch.value)}
                    className={clsx(
                      'flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs transition-colors',
                      active
                        ? 'border-blue-400 bg-blue-50 text-blue-600 dark:border-blue-500 dark:bg-blue-500/20 dark:text-blue-300'
                        : 'border-gray-200 text-gray-500 hover:bg-gray-50 dark:border-slate-600 dark:text-slate-400 dark:hover:bg-slate-700',
                    )}
                  >
                    <ChannelLogo type={ch.value} size={12} />
                    {ch.label}
                  </button>
                );
              })}
            </div>
          </Field>

          <Field label="标签">
            <TagInput tags={form.tags ?? []} onChange={(t) => set('tags', t)} />
          </Field>

          <Field label="备注">
            <textarea
              value={form.note}
              onChange={(e) => set('note', e.target.value)}
              rows={3}
              placeholder="客户背景、需求要点、跟进注意事项…"
              className={clsx(inputCls(false), 'resize-none')}
              aria-label="备注"
            />
          </Field>

          {hasCustomFields && (
            <div className="border-t border-gray-100 pt-4 dark:border-slate-700">
              <p className="mb-3 text-xs font-medium text-gray-500 dark:text-slate-400">自定义字段</p>
              <CustomFieldsEditor values={customValues} onChange={setCustomValues} />
            </div>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            {initial ? '保存修改' : '创建客户'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-slate-400">{label}</span>
      {children}
      {error && <span className="mt-1 block text-xs text-red-500">{error}</span>}
    </label>
  );
}

function inputCls(hasError: boolean): string {
  return clsx(
    'w-full rounded-lg border px-3 py-2 text-sm text-gray-800 outline-none transition-colors focus:ring-2 focus:ring-blue-500/30 dark:bg-slate-700 dark:text-slate-100',
    hasError ? 'border-red-400' : 'border-gray-300 focus:border-blue-500 dark:border-slate-600',
  );
}

/* ========================= 子组件：确认弹窗 ========================= */

function ConfirmDialog({
  title,
  message,
  confirmText = '确认',
  danger,
  loading,
  onCancel,
  onConfirm,
}: {
  title: string;
  message: string;
  confirmText?: string;
  danger?: boolean;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onMouseDown={onCancel}>
      <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl dark:bg-slate-800" onMouseDown={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center gap-3">
          <div className={clsx('flex h-10 w-10 items-center justify-center rounded-full', danger ? 'bg-red-50 dark:bg-red-500/10' : 'bg-blue-50 dark:bg-blue-500/10')}>
            <AlertCircle className={clsx('h-5 w-5', danger ? 'text-red-500' : 'text-blue-500')} />
          </div>
          <h3 className="text-base font-semibold text-gray-800 dark:text-slate-100">{title}</h3>
        </div>
        <p className="text-sm text-gray-500 dark:text-slate-400">{message}</p>
        <div className="mt-6 flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className={clsx(
              'inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-60',
              danger ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700',
            )}
          >
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ========================= 骨架行 ========================= */

function SkeletonRow() {
  return (
    <tr className="border-b border-gray-100 dark:border-slate-800">
      {Array.from({ length: 7 }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 w-full animate-pulse rounded bg-gray-100 dark:bg-slate-700/60" />
        </td>
      ))}
    </tr>
  );
}

/* ========================= 主组件 ========================= */

export default function Customers() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // CRM 增强 store（自定义字段 / 跟进任务）
  const setCustomValuesStore = useCrmEnhanceStore((s) => s.setCustomValues);
  const customFields = useCrmEnhanceStore((s) => s.customFields);
  const customValuesMap = useCrmEnhanceStore((s) => s.customValues);
  const followUps = useCrmEnhanceStore((s) => s.followUps);

  // 筛选与视图状态
  const [search, setSearch] = useState('');
  const [stageFilter, setStageFilter] = useState('');
  const [channelFilter, setChannelFilter] = useState('');
  const [scoreFilter, setScoreFilter] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('updated_at');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [viewMode, setViewMode] = useState<'table' | 'card'>('table');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // 弹窗状态
  const [editing, setEditing] = useState<CustomerRecord | null | 'new'>(null);
  const [deleting, setDeleting] = useState<CustomerRecord | null>(null);
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false);
  const [importCsv, setImportCsv] = useState<string | null>(null);
  const [dedupeOpen, setDedupeOpen] = useState(false);
  const [fieldsOpen, setFieldsOpen] = useState(false);
  const [followUpFor, setFollowUpFor] = useState<CustomerRecord | null>(null);

  /* ---- 数据加载 ---- */
  const { data, isLoading, isError, refetch, isFetching } = useApiQuery<CustomerListResponse>(
    ['customers', 'list'],
    () => getCustomers({ limit: 500 }),
    { retry: false },
  );

  const allCustomers = useMemo(() => data?.customers ?? [], [data]);
  const stageDefs = useMemo(
    () => data?.stage_definitions ?? [],
    [data],
  );

  /* ---- 筛选 + 排序 ---- */
  const filtered = useMemo(() => {
    let list = [...allCustomers];
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((c) =>
        [c.display_name, c.name, c.company, c.email, c.phone, c.username].some((f) =>
          String(f || '').toLowerCase().includes(q),
        ),
      );
    }
    if (stageFilter) list = list.filter((c) => c.stage === stageFilter);
    if (channelFilter) list = list.filter((c) => (c.channel_sources || []).includes(channelFilter));
    if (scoreFilter === 'high') list = list.filter((c) => c.ai_score >= 0.7);
    else if (scoreFilter === 'mid') list = list.filter((c) => c.ai_score >= 0.4 && c.ai_score < 0.7);
    else if (scoreFilter === 'low') list = list.filter((c) => c.ai_score < 0.4);

    list.sort((a, b) => {
      let av: string | number;
      let bv: string | number;
      if (sortKey === 'ai_score') {
        av = a.ai_score;
        bv = b.ai_score;
      } else if (sortKey === 'display_name') {
        av = a.display_name || '';
        bv = b.display_name || '';
      } else {
        av = a[sortKey] || '';
        bv = b[sortKey] || '';
      }
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return list;
  }, [allCustomers, search, stageFilter, channelFilter, scoreFilter, sortKey, sortDir]);

  // 筛选变化时回到第一页
  useEffect(() => {
    setPage(1);
  }, [search, stageFilter, channelFilter, scoreFilter, pageSize]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const paged = useMemo(
    () => filtered.slice((page - 1) * pageSize, page * pageSize),
    [filtered, page, pageSize],
  );

  /* ---- KPI 概览 ---- */
  const kpis: KpiItem[] = useMemo(() => {
    const total = allCustomers.length;
    const highIntent = allCustomers.filter((c) => c.ai_score >= 0.7).length;
    const converting = allCustomers.filter((c) => !COLD_STAGES.has(c.stage) && !CLOSED_STAGES.has(c.stage)).length;
    const now = new Date();
    const monthNew = allCustomers.filter((c) => {
      const d = new Date(c.created_at || c.updated_at || '');
      return !isNaN(d.getTime()) && d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
    }).length;
    return [
      { title: '客户总数', value: total, icon: Users, subtitle: '全部在管客户' },
      { title: '高意向 (≥70)', value: highIntent, icon: TrendingUp, subtitle: total ? `占比 ${Math.round((highIntent / total) * 100)}%` : '—' },
      { title: '转化中', value: converting, icon: ArrowUpDown, subtitle: '已建联至待签' },
      { title: '本月新增', value: monthNew, icon: UserPlus, subtitle: '当月新建客户' },
    ];
  }, [allCustomers]);

  /* ---- Mutations ---- */
  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['customers'] });
  }, [queryClient]);

  const createMut = useApiMutation(
    ({ body }: { body: CustomerProfileInput; customValues: Record<string, string> }) => createCustomer(body),
    {
      onSuccess: (data, vars) => {
        const newId = (data as { customer_id?: number } | undefined)?.customer_id;
        if (newId != null && Object.keys(vars.customValues).length) setCustomValuesStore(newId, vars.customValues);
        toastStore.success('客户已创建');
        setEditing(null);
        invalidate();
      },
      onError: () => toastStore.error('创建失败，请重试'),
    },
  );

  const updateMut = useApiMutation(
    ({ id, body }: { id: number; body: CustomerProfileInput; customValues: Record<string, string> }) =>
      updateCustomer(id, body),
    {
      onSuccess: (_d, vars) => {
        setCustomValuesStore(vars.id, vars.customValues);
        toastStore.success('客户资料已更新');
        setEditing(null);
        invalidate();
      },
      onError: () => toastStore.error('更新失败，请重试'),
    },
  );

  const deleteMut = useApiMutation((id: number) => deleteCustomer(id), {
    onSuccess: () => {
      toastStore.success('客户已删除');
      setDeleting(null);
      invalidate();
    },
    onError: () => toastStore.error('删除失败，请重试'),
  });

  const batchMut = useApiMutation(
    (body: { customer_ids: number[]; action: 'delete' | 'set_stage' | 'add_tag' | 'remove_tag'; stage?: string; tag?: string }) =>
      batchCustomers(body),
    {
      onSuccess: (_d, vars) => {
        toastStore.success(vars.action === 'delete' ? '已批量删除' : '批量操作完成');
        setSelected(new Set());
        setBatchDeleteOpen(false);
        invalidate();
      },
      onError: () => toastStore.error('批量操作失败'),
    },
  );

  /* ---- 选择逻辑 ---- */
  const allPageSelected = paged.length > 0 && paged.every((c) => selected.has(c.customer_id));
  const toggleSelectAll = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allPageSelected) {
        paged.forEach((c) => next.delete(c.customer_id));
      } else {
        paged.forEach((c) => next.add(c.customer_id));
      }
      return next;
    });
  };
  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const resetFilters = () => {
    setSearch('');
    setStageFilter('');
    setChannelFilter('');
    setScoreFilter('');
  };

  const hasActiveFilter = !!(search || stageFilter || channelFilter || scoreFilter);

  /* ---- CSV 导入（读文件 → 打开字段映射向导） ---- */
  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || '');
      if (!text.trim()) {
        toastStore.error('CSV 内容为空');
        return;
      }
      setImportCsv(text);
    };
    reader.onerror = () => toastStore.error('读取文件失败');
    reader.readAsText(file, 'utf-8');
  };

  /* ========================= 渲染 ========================= */

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto">
      {/* 标题 + 主操作 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800 dark:text-slate-100">客户管理</h1>
          <p className="mt-0.5 text-sm text-gray-400 dark:text-slate-500">
            统一管理客户资料、阶段、标签与跟进，共 {filtered.length} 位客户
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            aria-label="刷新"
          >
            <RefreshCw className={clsx('h-4 w-4', isFetching && 'animate-spin')} />
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            aria-label="导入 CSV"
          >
            <Upload className="h-4 w-4" /> 导入
          </button>
          <input ref={fileInputRef} type="file" accept=".csv" className="hidden" onChange={handleImport} />
          <button
            onClick={() => exportCustomersCsv(filtered, customFields, customValuesMap)}
            disabled={!filtered.length}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            aria-label="导出 CSV"
          >
            <Download className="h-4 w-4" /> 导出
          </button>
          <button
            onClick={() => setDedupeOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            aria-label="查找重复"
          >
            <Copy className="h-4 w-4" /> 查重
          </button>
          <button
            onClick={() => setFieldsOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            aria-label="自定义字段"
          >
            <SlidersHorizontal className="h-4 w-4" /> 字段
          </button>
          <button
            onClick={() => setEditing('new')}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            <Plus className="h-4 w-4" /> 新建客户
          </button>
        </div>
      </div>

      {/* KPI 概览 */}
      <KpiGrid items={kpis} cols={4} />

      {/* 跟进提醒条 */}
      <RemindersBanner customers={allCustomers} onSelect={(id) => navigate(`/customers/${id}`)} />

      {/* 工具栏：搜索 + 筛选 + 视图 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-sm dark:border-slate-700 dark:bg-slate-800">
          <Search className="h-4 w-4 text-gray-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索姓名、公司、邮箱、电话…"
            className="w-56 bg-transparent text-sm text-gray-700 outline-none placeholder:text-gray-400 dark:text-slate-200"
            aria-label="搜索客户"
          />
        </div>

        <FilterSelect value={stageFilter} onChange={setStageFilter} ariaLabel="阶段筛选">
          <option value="">全部阶段</option>
          {stageDefs.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </FilterSelect>

        <FilterSelect value={channelFilter} onChange={setChannelFilter} ariaLabel="渠道筛选">
          <option value="">全部渠道</option>
          {CHANNEL_OPTIONS.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </FilterSelect>

        <FilterSelect value={scoreFilter} onChange={setScoreFilter} ariaLabel="评分筛选">
          <option value="">全部评分</option>
          <option value="high">高 (≥70)</option>
          <option value="mid">中 (40-70)</option>
          <option value="low">低 (&lt;40)</option>
        </FilterSelect>

        {hasActiveFilter && (
          <button onClick={resetFilters} className="text-sm text-blue-600 hover:underline dark:text-blue-400">
            清除筛选
          </button>
        )}

        <div className="ml-auto flex items-center rounded-lg border border-gray-200 p-0.5 dark:border-slate-700">
          <button
            onClick={() => setViewMode('table')}
            className={clsx('rounded-md p-1.5', viewMode === 'table' ? 'bg-blue-600 text-white' : 'text-gray-500 dark:text-slate-400')}
            aria-label="表格视图"
          >
            <ListIcon className="h-4 w-4" />
          </button>
          <button
            onClick={() => setViewMode('card')}
            className={clsx('rounded-md p-1.5', viewMode === 'card' ? 'bg-blue-600 text-white' : 'text-gray-500 dark:text-slate-400')}
            aria-label="卡片视图"
          >
            <LayoutGrid className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* 批量操作栏 */}
      {selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm dark:border-blue-500/30 dark:bg-blue-500/10">
          <span className="font-medium text-blue-700 dark:text-blue-300">已选择 {selected.size} 位客户</span>
          <div className="flex items-center gap-2">
            <span className="text-gray-500 dark:text-slate-400">批量改阶段：</span>
            <select
              onChange={(e) => {
                if (e.target.value) {
                  batchMut.mutate({ customer_ids: [...selected], action: 'set_stage', stage: e.target.value });
                  e.target.value = '';
                }
              }}
              defaultValue=""
              className="rounded-lg border border-gray-200 bg-white px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-700 dark:text-slate-200"
              aria-label="批量改阶段"
            >
              <option value="" disabled>
                选择阶段
              </option>
              {stageDefs.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={() => setBatchDeleteOpen(true)}
            className="inline-flex items-center gap-1 rounded-lg border border-red-200 px-2.5 py-1 text-red-600 hover:bg-red-50 dark:border-red-500/30 dark:text-red-400 dark:hover:bg-red-500/10"
          >
            <Trash2 className="h-3.5 w-3.5" /> 批量删除
          </button>
          <button onClick={() => setSelected(new Set())} className="ml-auto text-gray-500 hover:text-gray-700 dark:text-slate-400">
            取消选择
          </button>
        </div>
      )}

      {/* 主体 */}
      {isLoading ? (
        viewMode === 'table' ? (
          <div className="overflow-hidden rounded-xl border border-gray-200 dark:border-slate-700">
            <table className="w-full">
              <tbody>
                {Array.from({ length: 6 }).map((_, i) => (
                  <SkeletonRow key={i} />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-40 animate-pulse rounded-xl bg-gray-100 dark:bg-slate-800" />
            ))}
          </div>
        )
      ) : isError ? (
        <Empty
          icon={AlertCircle}
          title="加载失败"
          description="无法获取客户列表，请检查网络或稍后重试"
          action={
            <button onClick={() => refetch()} className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
              重新加载
            </button>
          }
        />
      ) : filtered.length === 0 ? (
        <Empty
          icon={Users}
          title={hasActiveFilter ? '没有匹配的客户' : '还没有客户'}
          description={hasActiveFilter ? '试试调整筛选条件' : '点击右上角"新建客户"，或从漏斗、渠道导入客户'}
          action={
            hasActiveFilter ? (
              <button onClick={resetFilters} className="rounded-lg border border-gray-200 px-4 py-2 text-sm dark:border-slate-600">
                清除筛选
              </button>
            ) : (
              <button onClick={() => setEditing('new')} className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
                <Plus className="h-4 w-4" /> 新建客户
              </button>
            )
          }
        />
      ) : viewMode === 'table' ? (
        <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white dark:border-slate-700 dark:bg-slate-800">
          <table className="w-full min-w-[920px] text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-left text-xs text-gray-500 dark:border-slate-700 dark:text-slate-400">
                <th className="w-10 px-4 py-3">
                  <input
                    type="checkbox"
                    checked={allPageSelected}
                    onChange={toggleSelectAll}
                    className="h-4 w-4 rounded border-gray-300 accent-blue-600"
                    aria-label="全选当前页"
                  />
                </th>
                <SortableTh label="客户" active={sortKey === 'display_name'} dir={sortDir} onClick={() => handleSort('display_name')} />
                <th className="px-4 py-3 font-medium">联系方式</th>
                <th className="px-4 py-3 font-medium">阶段</th>
                <th className="px-4 py-3 font-medium">渠道</th>
                <SortableTh label="AI 评分" active={sortKey === 'ai_score'} dir={sortDir} onClick={() => handleSort('ai_score')} />
                <th className="px-4 py-3 font-medium">标签</th>
                <SortableTh label="更新时间" active={sortKey === 'updated_at'} dir={sortDir} onClick={() => handleSort('updated_at')} />
                <th className="px-4 py-3 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {paged.map((c) => (
                <tr
                  key={c.customer_id}
                  onClick={() => navigate(`/customers/${c.customer_id}`)}
                  className={clsx(
                    'cursor-pointer border-b border-gray-100 transition-colors last:border-0 hover:bg-gray-50 dark:border-slate-800 dark:hover:bg-slate-700/40',
                    selected.has(c.customer_id) && 'bg-blue-50/50 dark:bg-blue-500/10',
                  )}
                >
                  <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(c.customer_id)}
                      onChange={() => toggleSelect(c.customer_id)}
                      className="h-4 w-4 rounded border-gray-300 accent-blue-600"
                      aria-label={`选择 ${c.display_name}`}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2.5">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 text-xs font-medium text-white">
                        {(c.display_name || '?').charAt(0)}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate font-medium text-gray-800 dark:text-slate-100">{c.display_name}</p>
                        {c.company && c.company !== c.display_name && (
                          <p className="flex items-center gap-1 truncate text-xs text-gray-400">
                            <Building2 className="h-3 w-3" /> {c.company}
                          </p>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="space-y-0.5 text-xs text-gray-500 dark:text-slate-400">
                      {c.phone && (
                        <p className="flex items-center gap-1">
                          <Phone className="h-3 w-3" /> {c.phone}
                        </p>
                      )}
                      {c.email && (
                        <p className="flex items-center gap-1 truncate">
                          <Mail className="h-3 w-3" /> {c.email}
                        </p>
                      )}
                      {!c.phone && !c.email && <span className="text-gray-300 dark:text-slate-600">—</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={clsx('inline-flex rounded-full px-2 py-0.5 text-xs font-medium', stageColor(c.stage))}>
                      {c.stage_label}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      {(c.channel_sources || []).slice(0, 3).map((ch) => (
                        <span key={ch} title={ch}>
                          <ChannelLogo type={ch} size={16} />
                        </span>
                      ))}
                      {!(c.channel_sources || []).length && <span className="text-gray-300 dark:text-slate-600">—</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-gray-100 dark:bg-slate-700">
                        <div className="h-full rounded-full" style={{ width: `${Math.max(c.ai_score * 100, 2)}%`, background: scoreGradient(c.ai_score) }} />
                      </div>
                      <span className={clsx('text-xs font-medium', scoreColorText(c.ai_score))}>{Math.round(c.ai_score * 100)}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex max-w-[160px] flex-wrap gap-1">
                      {[...(c.tags || []), ...(c.ai_tags || [])].slice(0, 2).map((t, i) => (
                        <span key={`${t}-${i}`} className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600 dark:bg-slate-700 dark:text-slate-300">
                          {t}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400">{formatTimeAgo(c.updated_at)}</td>
                  <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1">
                      <FollowUpButton fu={followUps[c.customer_id]} onClick={() => setFollowUpFor(c)} />
                      <IconBtn title="查看" onClick={() => navigate(`/customers/${c.customer_id}`)}>
                        <Eye className="h-4 w-4" />
                      </IconBtn>
                      <IconBtn title="编辑" onClick={() => setEditing(c)}>
                        <Pencil className="h-4 w-4" />
                      </IconBtn>
                      <IconBtn title="删除" danger onClick={() => setDeleting(c)}>
                        <Trash2 className="h-4 w-4" />
                      </IconBtn>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        /* 卡片视图 */
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {paged.map((c) => (
            <div
              key={c.customer_id}
              className={clsx(
                'group relative rounded-xl border bg-white p-4 transition-all hover:shadow-md dark:bg-slate-800',
                selected.has(c.customer_id) ? 'border-blue-400 dark:border-blue-500' : 'border-gray-200 dark:border-slate-700',
              )}
            >
              <div className="absolute right-3 top-3" onClick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={selected.has(c.customer_id)}
                  onChange={() => toggleSelect(c.customer_id)}
                  className="h-4 w-4 rounded border-gray-300 accent-blue-600"
                  aria-label={`选择 ${c.display_name}`}
                />
              </div>
              <button onClick={() => navigate(`/customers/${c.customer_id}`)} className="flex items-center gap-3 text-left">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 text-sm font-medium text-white">
                  {(c.display_name || '?').charAt(0)}
                </div>
                <div className="min-w-0">
                  <p className="truncate font-semibold text-gray-800 group-hover:text-blue-600 dark:text-slate-100">{c.display_name}</p>
                  {c.company && <p className="truncate text-xs text-gray-400">{c.company}</p>}
                </div>
              </button>

              <div className="mt-3 flex items-center justify-between">
                <span className={clsx('inline-flex rounded-full px-2 py-0.5 text-xs font-medium', stageColor(c.stage))}>{c.stage_label}</span>
                <span className={clsx('text-xs font-medium', scoreColorText(c.ai_score))}>AI {Math.round(c.ai_score * 100)}</span>
              </div>

              <div className="mt-2 space-y-1 text-xs text-gray-500 dark:text-slate-400">
                {c.phone && (
                  <p className="flex items-center gap-1">
                    <Phone className="h-3 w-3" /> {c.phone}
                  </p>
                )}
                {c.email && (
                  <p className="flex items-center gap-1 truncate">
                    <Mail className="h-3 w-3" /> {c.email}
                  </p>
                )}
              </div>

              {!!(c.tags || c.ai_tags) && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {[...(c.tags || []), ...(c.ai_tags || [])].slice(0, 3).map((t, i) => (
                    <span key={`${t}-${i}`} className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600 dark:bg-slate-700 dark:text-slate-300">
                      {t}
                    </span>
                  ))}
                </div>
              )}

              <div className="mt-3 flex items-center justify-between border-t border-gray-100 pt-2 dark:border-slate-700">
                <span className="text-[10px] text-gray-400">{formatTimeAgo(c.updated_at)}</span>
                <div className="flex gap-1">
                  <FollowUpButton fu={followUps[c.customer_id]} onClick={() => setFollowUpFor(c)} />
                  <IconBtn title="编辑" onClick={() => setEditing(c)}>
                    <Pencil className="h-3.5 w-3.5" />
                  </IconBtn>
                  <IconBtn title="删除" danger onClick={() => setDeleting(c)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </IconBtn>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 分页 */}
      {filtered.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 pb-2">
          <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-slate-400">
            <span>每页</span>
            <select
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
              className="rounded-lg border border-gray-200 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-200"
              aria-label="每页条数"
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            <span>
              第 {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, filtered.length)} 条，共 {filtered.length} 条
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="rounded-lg border border-gray-200 p-1.5 text-gray-500 disabled:opacity-40 dark:border-slate-700 dark:text-slate-400"
              aria-label="上一页"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="px-2 text-sm text-gray-600 dark:text-slate-300">
              {page} / {pageCount}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
              disabled={page === pageCount}
              className="rounded-lg border border-gray-200 p-1.5 text-gray-500 disabled:opacity-40 dark:border-slate-700 dark:text-slate-400"
              aria-label="下一页"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* 表单弹窗 */}
      {editing !== null && (
        <CustomerFormModal
          initial={editing === 'new' ? null : editing}
          stageDefs={stageDefs}
          submitting={createMut.isPending || updateMut.isPending}
          onClose={() => setEditing(null)}
          onSubmit={(body, customValues) => {
            if (editing === 'new') createMut.mutate({ body, customValues });
            else updateMut.mutate({ id: editing.customer_id, body, customValues });
          }}
        />
      )}

      {/* 单个删除确认 */}
      {deleting && (
        <ConfirmDialog
          title="删除客户"
          message={`确定删除客户「${deleting.display_name}」吗？该操作不可撤销。`}
          confirmText="删除"
          danger
          loading={deleteMut.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => deleteMut.mutate(deleting.customer_id)}
        />
      )}

      {/* 批量删除确认 */}
      {batchDeleteOpen && (
        <ConfirmDialog
          title="批量删除客户"
          message={`确定删除选中的 ${selected.size} 位客户吗？该操作不可撤销。`}
          confirmText="全部删除"
          danger
          loading={batchMut.isPending}
          onCancel={() => setBatchDeleteOpen(false)}
          onConfirm={() => batchMut.mutate({ customer_ids: [...selected], action: 'delete' })}
        />
      )}

      {/* CSV 导入向导 */}
      {importCsv !== null && (
        <ImportWizard
          csvText={importCsv}
          existing={allCustomers}
          onClose={() => setImportCsv(null)}
          onImported={(count) => {
            setImportCsv(null);
            toastStore.success(count ? `成功导入 ${count} 位客户` : '没有可导入的数据');
            invalidate();
          }}
        />
      )}

      {/* 查重合并 */}
      {dedupeOpen && (
        <DedupeModal customers={allCustomers} onClose={() => setDedupeOpen(false)} onMerged={invalidate} />
      )}

      {/* 自定义字段管理 */}
      {fieldsOpen && <CustomFieldsModal onClose={() => setFieldsOpen(false)} />}

      {/* 设置跟进 */}
      {followUpFor && <FollowUpModal customer={followUpFor} onClose={() => setFollowUpFor(null)} />}
    </div>
  );
}

/** 跟进按钮：依据跟进紧急度着色（逾期红 / 今日橙 / 临期蓝 / 完成绿 / 无灰） */
function FollowUpButton({ fu, onClick }: { fu?: FollowUp; onClick: () => void }) {
  const urgency = followUpUrgency(fu);
  const color =
    urgency === 'overdue'
      ? 'text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10'
      : urgency === 'today'
        ? 'text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-500/10'
        : urgency === 'soon'
          ? 'text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-500/10'
          : urgency === 'done'
            ? 'text-green-500 hover:bg-green-50 dark:hover:bg-green-500/10'
            : 'text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-slate-700 dark:hover:text-slate-200';
  return (
    <button
      title={fu ? `跟进：${fu.due_date}${fu.done ? '（已完成）' : ''}` : '设置跟进'}
      aria-label="设置跟进"
      onClick={onClick}
      className={clsx('rounded-md p-1.5 transition-colors', color)}
    >
      <CalendarClock className="h-3.5 w-3.5" />
    </button>
  );
}

/* ========================= 小组件 ========================= */

function FilterSelect({
  value,
  onChange,
  ariaLabel,
  children,
}: {
  value: string;
  onChange: (v: string) => void;
  ariaLabel: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-sm dark:border-slate-700 dark:bg-slate-800">
      <Filter className="h-3.5 w-3.5 text-gray-400" />
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-transparent text-sm text-gray-700 outline-none dark:bg-slate-800 dark:text-slate-200"
        aria-label={ariaLabel}
      >
        {children}
      </select>
    </div>
  );
}

function SortableTh({ label, active, dir, onClick }: { label: string; active: boolean; dir: 'asc' | 'desc'; onClick: () => void }) {
  return (
    <th className="px-4 py-3 font-medium">
      <button onClick={onClick} className={clsx('inline-flex items-center gap-1 hover:text-gray-700 dark:hover:text-slate-200', active && 'text-blue-600 dark:text-blue-400')}>
        {label}
        <ArrowUpDown className={clsx('h-3 w-3', active ? 'opacity-100' : 'opacity-40')} />
        {active && <span className="text-[10px]">{dir === 'asc' ? '↑' : '↓'}</span>}
      </button>
    </th>
  );
}

function IconBtn({ title, danger, onClick, children }: { title: string; danger?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      title={title}
      aria-label={title}
      onClick={onClick}
      className={clsx(
        'rounded-md p-1.5 text-gray-400 transition-colors',
        danger ? 'hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-500/10' : 'hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-slate-700 dark:hover:text-slate-200',
      )}
    >
      {children}
    </button>
  );
}
