/**
 * 客户管理增强工具集：CSV 解析 / 联系方式归一 / 重复分组 / 导入字段映射
 */

import type { CustomerRecord, CustomerProfileInput } from '../types';

/* ============================ CSV 解析 ============================ */

/** 解析单行 CSV（支持引号包裹、转义双引号、逗号在引号内） */
function parseCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cur += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ',') {
      out.push(cur);
      cur = '';
    } else {
      cur += ch;
    }
  }
  out.push(cur);
  return out.map((c) => c.trim());
}

export interface ParsedCsv {
  headers: string[];
  rows: string[][];
}

/** 解析整段 CSV 文本为 { headers, rows }，自动剥离 UTF-8 BOM */
export function parseCsv(text: string): ParsedCsv {
  const clean = text.replace(/^\uFEFF/, '');
  const lines = clean.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length === 0) return { headers: [], rows: [] };
  const headers = parseCsvLine(lines[0]);
  const rows = lines.slice(1).map(parseCsvLine);
  return { headers, rows };
}

/* ====================== 导入字段映射（目标字段） ====================== */

export interface ImportTargetField {
  key: keyof CustomerProfileInput;
  label: string;
  /** 用于自动匹配的别名关键词（小写） */
  aliases: string[];
}

export const IMPORT_TARGET_FIELDS: ImportTargetField[] = [
  { key: 'name', label: '客户姓名', aliases: ['姓名', '名字', '客户', '联系人', 'name', 'contact'] },
  { key: 'company', label: '公司名称', aliases: ['公司', '企业', '单位', 'company', 'org', 'organization'] },
  { key: 'email', label: '邮箱', aliases: ['邮箱', '邮件', 'email', 'mail', 'e-mail'] },
  { key: 'phone', label: '电话', aliases: ['电话', '手机', '联系方式', '号码', 'phone', 'mobile', 'tel'] },
  { key: 'owner', label: '负责人', aliases: ['负责人', '跟进人', '销售', 'owner', 'sales'] },
  { key: 'source', label: '来源', aliases: ['来源', '渠道来源', 'source', 'channel'] },
  { key: 'note', label: '备注', aliases: ['备注', '说明', '描述', 'note', 'remark', 'memo'] },
];

/**
 * 依据 CSV 表头自动推断「目标字段 → 列索引」的初始映射。
 * 命中规则：表头去空格小写后，与别名相等或互相包含即视为匹配。
 */
export function autoMapColumns(headers: string[]): Record<string, number> {
  const norm = (s: string) => s.replace(/\s+/g, '').toLowerCase();
  const normalizedHeaders = headers.map(norm);
  const map: Record<string, number> = {};
  for (const field of IMPORT_TARGET_FIELDS) {
    const idx = normalizedHeaders.findIndex((h) =>
      h.length > 0 &&
      field.aliases.some((a) => {
        const na = norm(a);
        return h === na || h.includes(na) || na.includes(h);
      }),
    );
    if (idx >= 0 && !Object.values(map).includes(idx)) {
      map[field.key] = idx;
    }
  }
  return map;
}

/** 用映射把一行 CSV 转成客户入参 */
export function rowToProfile(row: string[], mapping: Record<string, number>): CustomerProfileInput {
  const profile: CustomerProfileInput = {};
  for (const [key, idx] of Object.entries(mapping)) {
    if (idx < 0) continue;
    const val = (row[idx] ?? '').trim();
    if (!val) continue;
    (profile as Record<string, unknown>)[key] = val;
  }
  return profile;
}

/* ====================== 联系方式归一 + 重复检测 ====================== */

/** 归一手机号：仅保留数字，去掉国家码常见前缀 */
export function normalizePhone(phone?: string): string {
  if (!phone) return '';
  const digits = phone.replace(/\D/g, '');
  if (digits.length > 11 && digits.startsWith('86')) return digits.slice(-11);
  return digits;
}

export function normalizeEmail(email?: string): string {
  return (email ?? '').trim().toLowerCase();
}

export function normalizeName(name?: string): string {
  return (name ?? '').replace(/\s+/g, '').toLowerCase();
}

/** 两个客户是否疑似重复（手机 / 邮箱 / 同名同公司任一命中） */
export function isLikelyDuplicate(a: CustomerRecord, b: CustomerRecord): boolean {
  const pa = normalizePhone(a.phone);
  const pb = normalizePhone(b.phone);
  if (pa && pa === pb) return true;
  const ea = normalizeEmail(a.email);
  const eb = normalizeEmail(b.email);
  if (ea && ea === eb) return true;
  const na = normalizeName(a.name || a.display_name);
  const nb = normalizeName(b.name || b.display_name);
  const ca = normalizeName(a.company);
  const cb = normalizeName(b.company);
  if (na && na === nb && ca && ca === cb) return true;
  return false;
}

export interface DuplicateGroup {
  /** 命中的归一 key（用于展示分组依据） */
  reason: string;
  members: CustomerRecord[];
}

/**
 * 在现有客户中找出重复分组：依次按手机、邮箱、姓名+公司聚合，
 * 同一客户只归入第一个命中的分组，返回成员数 ≥ 2 的分组。
 */
export function findDuplicateGroups(customers: CustomerRecord[]): DuplicateGroup[] {
  const used = new Set<number>();
  const groups: DuplicateGroup[] = [];

  const collect = (keyFn: (c: CustomerRecord) => string, reasonLabel: (key: string) => string) => {
    const buckets = new Map<string, CustomerRecord[]>();
    for (const c of customers) {
      if (used.has(c.customer_id)) continue;
      const key = keyFn(c);
      if (!key) continue;
      const arr = buckets.get(key) ?? [];
      arr.push(c);
      buckets.set(key, arr);
    }
    for (const [key, members] of buckets) {
      if (members.length >= 2) {
        members.forEach((m) => used.add(m.customer_id));
        groups.push({ reason: reasonLabel(key), members });
      }
    }
  };

  collect((c) => normalizePhone(c.phone), (k) => `电话 ${k}`);
  collect((c) => normalizeEmail(c.email), (k) => `邮箱 ${k}`);
  collect(
    (c) => {
      const n = normalizeName(c.name || c.display_name);
      const co = normalizeName(c.company);
      return n && co ? `${n}@@${co}` : '';
    },
    () => '同名同公司',
  );

  return groups;
}

/**
 * 计算合并后的主记录资料：以主记录为基准，空字段用其它记录补全，
 * 标签 / 渠道并集去重。返回 CustomerProfileInput（用于 updateCustomer）。
 */
export function buildMergedProfile(primary: CustomerRecord, others: CustomerRecord[]): CustomerProfileInput {
  const pick = (cur: string | undefined, getter: (c: CustomerRecord) => string | undefined): string => {
    if (cur && cur.trim()) return cur;
    for (const o of others) {
      const v = getter(o);
      if (v && v.trim()) return v;
    }
    return cur ?? '';
  };
  const tags = new Set<string>([...(primary.tags ?? [])]);
  const channels = new Set<string>([...(primary.channel_sources ?? [])]);
  for (const o of others) {
    (o.tags ?? []).forEach((t) => tags.add(t));
    (o.channel_sources ?? []).forEach((c) => channels.add(c));
  }
  const noteParts = [primary.note, ...others.map((o) => o.note)].filter((n) => n && n.trim()) as string[];
  return {
    name: pick(primary.name, (c) => c.name),
    company: pick(primary.company, (c) => c.company),
    email: pick(primary.email, (c) => c.email),
    phone: pick(primary.phone, (c) => c.phone),
    owner: pick(primary.owner, (c) => c.owner),
    source: pick(primary.source, (c) => c.source),
    note: Array.from(new Set(noteParts)).join(' / '),
    stage: primary.stage,
    tags: Array.from(tags),
    channel_sources: Array.from(channels),
  };
}
