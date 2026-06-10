/** 格式化相对时间（"3分钟前"、"2小时前"、"昨天"）
 *  - 非法日期 / NaN / 缺字段 → 返回 '-' 而不是 'NaN个月前'
 *  - 未来时间（diff < 0）→ '刚刚' */
export function formatTimeAgo(dateStr: string | number | null | undefined): string {
  if (dateStr === null || dateStr === undefined || dateStr === '') return '-';
  const target = new Date(dateStr).getTime();
  // NaN 表示 Date 解析失败
  if (!Number.isFinite(target)) return '-';
  const now = Date.now();
  const diffMs = now - target;
  if (diffMs < 0) return '刚刚';

  const seconds = Math.floor(diffMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (seconds < 60) return '刚刚';
  if (minutes < 60) return `${minutes}分钟前`;
  if (hours < 24) return `${hours}小时前`;
  if (days === 1) return '昨天';
  if (days < 30) return `${days}天前`;
  return `${Math.floor(days / 30)}个月前`;
}

/** 阶段 ID 转中文标签 */
const stageMap: Record<string, string> = {
  lead: '线索',
  qualified: '合格线索',
  proposal: '方案沟通',
  negotiation: '商务谈判',
  closed_won: '成交',
  closed_lost: '流失',
  new: '新线索',
  contacted: '已联系',
  interested: '有意向',
  intention: '意向客户',
  deal: '成交',
};

export function formatStage(stage: string): string {
  return stageMap[stage] ?? stage;
}

/** 渠道类型转颜色 */
export function getChannelColor(channelType: string): string {
  const colorMap: Record<string, string> = {
    wework: '#2B7CE9',      // 企微蓝
    phone: '#F5A623',       // 电话橙
    douyin: '#161823',      // 抖音黑
    email: '#EA4335',       // 邮件红
    sms: '#8E44AD',         // 短信紫
    web: '#3498DB',         // 网页蓝
    whatsapp: '#25D366',    // WhatsApp 绿
  };
  return colorMap[channelType] ?? '#6B7280';
}

/**
 * 统一解包后端响应数据
 * 后端响应可能为：
 * 1) AxiosResponse：{ data: { data: T } }
 * 2) 已经是 T
 * 统一解包成 T
 */
export function unwrapApiResponse<T>(payload: unknown): T {
  if (payload && typeof payload === 'object' && 'data' in (payload as Record<string, unknown>)) {
    const inner = (payload as { data: unknown }).data;
    if (inner && typeof inner === 'object' && 'data' in (inner as Record<string, unknown>)) {
      return (inner as { data: T }).data;
    }
    return inner as T;
  }
  return payload as T;
}
