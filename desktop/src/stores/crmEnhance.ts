/**
 * 客户管理增强本地状态（zustand + localStorage 持久化）
 *
 * 承载三类"大厂 CRM"能力的前端侧数据：
 * 1. 自定义字段定义（customFields）—— 管理员可配置的扩展字段 schema
 * 2. 自定义字段值（customValues）—— 按 customer_id 维护的字段取值
 * 3. 跟进任务（followUps）—— 按 customer_id 维护的下次跟进时间 + 备注 + 完成态
 *
 * 说明：后端目前以 mock / 轻量 stub 为主，扩展字段与跟进任务先落在本地，
 *       保证演示闭环；后续接入后端时只需替换读写层。
 */

import { create } from 'zustand';

const CF_KEY = 'kellai:crm:customFields:v1';
const CV_KEY = 'kellai:crm:customValues:v1';
const FU_KEY = 'kellai:crm:followUps:v1';
const SEED_KEY = 'kellai:crm:seeded:v1';

export type CustomFieldType = 'text' | 'number' | 'select' | 'date';

/** 自定义字段定义 */
export interface CustomFieldDef {
  /** 稳定 key（用于值映射，创建后不变） */
  key: string;
  label: string;
  type: CustomFieldType;
  /** select 类型的可选项 */
  options?: string[];
}

/** 跟进任务 */
export interface FollowUp {
  /** 下次跟进日期（yyyy-mm-dd） */
  due_date: string;
  note: string;
  done: boolean;
  created_at: string;
}

type CustomValues = Record<number, Record<string, string>>;
type FollowUpMap = Record<number, FollowUp>;

interface CrmEnhanceState {
  customFields: CustomFieldDef[];
  customValues: CustomValues;
  followUps: FollowUpMap;

  addCustomField: (label: string, type: CustomFieldType, options?: string[]) => void;
  updateCustomField: (key: string, patch: Partial<Omit<CustomFieldDef, 'key'>>) => void;
  removeCustomField: (key: string) => void;

  setCustomValues: (customerId: number, values: Record<string, string>) => void;
  mergeCustomValues: (fromId: number, toId: number) => void;
  clearCustomValues: (customerId: number) => void;

  setFollowUp: (customerId: number, fu: FollowUp | null) => void;
  toggleFollowUpDone: (customerId: number) => void;
}

/* ---------- localStorage 读写 ---------- */

function readJSON<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function writeJSON(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // 隐私模式 / 容量满：忽略
  }
}

/* ---------- 首次种子数据（让演示一上来就有内容） ---------- */

const DEFAULT_FIELDS: CustomFieldDef[] = [
  { key: 'industry', label: '所属行业', type: 'select', options: ['互联网', '制造业', '零售电商', '金融', '教育', '医疗', '物流', '其他'] },
  { key: 'company_size', label: '公司规模', type: 'select', options: ['1-20 人', '20-100 人', '100-500 人', '500+ 人'] },
  { key: 'annual_budget', label: '年度预算(万)', type: 'number' },
  { key: 'decision_cycle', label: '决策周期', type: 'select', options: ['1 周内', '1 个月', '1 个季度', '半年以上'] },
];

function todayPlus(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

/** 首次启动播种：默认字段 + 几条示例跟进（绑定常见 mock 客户 id） */
function seedIfNeeded(): { fields: CustomFieldDef[]; values: CustomValues; follow: FollowUpMap } {
  const seeded = readJSON<boolean>(SEED_KEY, false);
  if (seeded) {
    return {
      fields: readJSON<CustomFieldDef[]>(CF_KEY, DEFAULT_FIELDS),
      values: readJSON<CustomValues>(CV_KEY, {}),
      follow: readJSON<FollowUpMap>(FU_KEY, {}),
    };
  }
  const fields = DEFAULT_FIELDS;
  const values: CustomValues = {
    1005: { industry: '零售电商', company_size: '100-500 人', annual_budget: '36', decision_cycle: '1 个月' },
    1007: { industry: '制造业', company_size: '500+ 人', annual_budget: '120', decision_cycle: '1 个季度' },
    1009: { industry: '金融', company_size: '500+ 人', annual_budget: '200', decision_cycle: '1 周内' },
  };
  const follow: FollowUpMap = {
    1003: { due_date: todayPlus(-2), note: '回访确认需求清单，约下次会议', done: false, created_at: new Date().toISOString() },
    1005: { due_date: todayPlus(0), note: '发送 50 坐席定制方案与报价', done: false, created_at: new Date().toISOString() },
    1007: { due_date: todayPlus(2), note: '跟进老板审批进度，准备议价空间', done: false, created_at: new Date().toISOString() },
    1008: { due_date: todayPlus(5), note: '议价后二次报价，给出阶梯折扣', done: false, created_at: new Date().toISOString() },
  };
  writeJSON(CF_KEY, fields);
  writeJSON(CV_KEY, values);
  writeJSON(FU_KEY, follow);
  writeJSON(SEED_KEY, true);
  return { fields, values, follow };
}

const seed = seedIfNeeded();

/* ---------- store ---------- */

function slugify(label: string): string {
  const base = label
    .trim()
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fa5]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return `${base || 'field'}_${Math.random().toString(36).slice(2, 6)}`;
}

export const useCrmEnhanceStore = create<CrmEnhanceState>((set, get) => ({
  customFields: seed.fields,
  customValues: seed.values,
  followUps: seed.follow,

  addCustomField: (label, type, options) => {
    const field: CustomFieldDef = {
      key: slugify(label),
      label: label.trim(),
      type,
      options: type === 'select' ? (options ?? []).filter(Boolean) : undefined,
    };
    const next = [...get().customFields, field];
    writeJSON(CF_KEY, next);
    set({ customFields: next });
  },

  updateCustomField: (key, patch) => {
    const next = get().customFields.map((f) => (f.key === key ? { ...f, ...patch } : f));
    writeJSON(CF_KEY, next);
    set({ customFields: next });
  },

  removeCustomField: (key) => {
    const next = get().customFields.filter((f) => f.key !== key);
    const values = { ...get().customValues };
    for (const id of Object.keys(values)) {
      const cid = Number(id);
      if (values[cid] && key in values[cid]) {
        const { [key]: _drop, ...rest } = values[cid];
        values[cid] = rest;
      }
    }
    writeJSON(CF_KEY, next);
    writeJSON(CV_KEY, values);
    set({ customFields: next, customValues: values });
  },

  setCustomValues: (customerId, values) => {
    const cleaned: Record<string, string> = {};
    for (const [k, v] of Object.entries(values)) {
      if (String(v).trim()) cleaned[k] = String(v).trim();
    }
    const next = { ...get().customValues, [customerId]: cleaned };
    if (Object.keys(cleaned).length === 0) delete next[customerId];
    writeJSON(CV_KEY, next);
    set({ customValues: next });
  },

  mergeCustomValues: (fromId, toId) => {
    const all = { ...get().customValues };
    const from = all[fromId];
    if (!from) return;
    all[toId] = { ...from, ...(all[toId] ?? {}) };
    delete all[fromId];
    writeJSON(CV_KEY, all);
    set({ customValues: all });
  },

  clearCustomValues: (customerId) => {
    const next = { ...get().customValues };
    delete next[customerId];
    writeJSON(CV_KEY, next);
    set({ customValues: next });
  },

  setFollowUp: (customerId, fu) => {
    const next = { ...get().followUps };
    if (fu) next[customerId] = fu;
    else delete next[customerId];
    writeJSON(FU_KEY, next);
    set({ followUps: next });
  },

  toggleFollowUpDone: (customerId) => {
    const cur = get().followUps[customerId];
    if (!cur) return;
    const next = { ...get().followUps, [customerId]: { ...cur, done: !cur.done } };
    writeJSON(FU_KEY, next);
    set({ followUps: next });
  },
}));

/* ---------- 纯函数：跟进到期判定（供 banner / 徽标复用） ---------- */

export type FollowUpUrgency = 'overdue' | 'today' | 'soon' | 'later' | 'done';

export function followUpUrgency(fu: FollowUp | undefined): FollowUpUrgency | null {
  if (!fu) return null;
  if (fu.done) return 'done';
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(fu.due_date);
  due.setHours(0, 0, 0, 0);
  const diffDays = Math.round((due.getTime() - today.getTime()) / 86400000);
  if (diffDays < 0) return 'overdue';
  if (diffDays === 0) return 'today';
  if (diffDays <= 3) return 'soon';
  return 'later';
}
