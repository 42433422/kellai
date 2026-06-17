import type { FinanceDashboardData, BudgetSuggestion, FinancePerformanceMember, FinanceAlert, FinanceReport, DecisionAdvice } from '../types';

/** 不同周期的财务画像 */
const FIN_PERIOD: Record<string, { revenue: number; cost: number; rev_g: number; cost_g: number; label: string }> = {
  month: { revenue: 1280000, cost: 456000, rev_g: 4.9, cost_g: 3.6, label: '本月' },
  quarter: { revenue: 3680000, cost: 1340000, rev_g: 11.2, cost_g: 7.1, label: '本季度' },
  year: { revenue: 13600000, cost: 5020000, rev_g: 18.0, cost_g: 9.4, label: '本年' },
};

export function getFinanceDashboard(period = 'month'): FinanceDashboardData {
  const prof = FIN_PERIOD[period] ?? FIN_PERIOD.month;
  const profit = prof.revenue - prof.cost;
  const margin = Math.round((profit / prof.revenue) * 1000) / 10;
  const scale = prof.revenue / 1280000;
  return {
    period,
    revenue: prof.revenue,
    cost: prof.cost,
    profit,
    profit_margin: margin,
    revenue_growth: prof.rev_g,
    cost_growth: prof.cost_g,
    profit_growth: Math.round((prof.rev_g - prof.cost_g) * 10) / 10 + 2,
    cash_flow: Math.round(profit * 0.78),
    receivable: Math.round(prof.revenue * 0.32),
    payable: Math.round(prof.cost * 0.41),
    channel_breakdown: [
      { channel: '微信', revenue: Math.round(448000 * scale), cost: Math.round(120000 * scale), profit: Math.round(328000 * scale) },
      { channel: '抖音', revenue: Math.round(384000 * scale), cost: Math.round(180000 * scale), profit: Math.round(204000 * scale) },
      { channel: '企业微信', revenue: Math.round(256000 * scale), cost: Math.round(80000 * scale), profit: Math.round(176000 * scale) },
      { channel: '邮件', revenue: Math.round(192000 * scale), cost: Math.round(76000 * scale), profit: Math.round(116000 * scale) },
    ],
    monthly_trend: [
      { month: '2026-01', revenue: 980000, cost: 380000, profit: 600000 },
      { month: '2026-02', revenue: 1050000, cost: 400000, profit: 650000 },
      { month: '2026-03', revenue: 1120000, cost: 420000, profit: 700000 },
      { month: '2026-04', revenue: 1180000, cost: 430000, profit: 750000 },
      { month: '2026-05', revenue: 1220000, cost: 440000, profit: 780000 },
      { month: '2026-06', revenue: 1280000, cost: 456000, profit: 824000 },
    ],
  };
}

/** 关键词驱动的财务问答（覆盖更多主题，引用真实口径） */
export function askFinance(question: string): { answer: string } {
  const q = question.toLowerCase();
  if (q.includes('利润') || q.includes('profit')) {
    return { answer: '本月利润 ¥824,000，利润率 64.4%，环比上月增长 5.6%。微信渠道利润贡献最高（¥328,000，占 39.8%）。建议持续加码高利润渠道。' };
  }
  if (q.includes('成本') || q.includes('cost') || q.includes('费用')) {
    return { answer: '本月总成本 ¥456,000（环比 +3.6%），其中抖音渠道占比最高（¥180,000，约 39%）。建议优化抖音投放素材与出价策略以降低 CPC。' };
  }
  if (q.includes('现金流') || q.includes('cash')) {
    return { answer: '本月经营性现金流约 ¥642,000，应收 ¥409,600、应付 ¥186,960，现金流健康。建议加快应收回款以进一步改善周转。' };
  }
  if (q.includes('渠道')) {
    return { answer: '四大渠道利润排序：微信(¥328K) > 抖音(¥204K) > 企业微信(¥176K) > 邮件(¥116K)。微信 ROI 最高(3.2x)，邮件成本最低但规模有限。' };
  }
  if (q.includes('预算')) {
    return { answer: '建议下月营销预算 ¥200,000：微信 ¥70K(ROI 3.2x)、抖音 ¥60K、企业微信 ¥40K、邮件 ¥30K。重点提升抖音 ROI。' };
  }
  if (q.includes('趋势') || q.includes('增长') || q.includes('同比') || q.includes('环比')) {
    return { answer: '近 6 个月营收从 ¥980K 稳步增长至 ¥1,280M，月均增速约 5.5%，同比增长 18%。利润率维持在 60%+ 区间，增长质量良好。' };
  }
  return { answer: `关于「${question}」：本月营收 ¥1,280,000（同比 +18%），利润 ¥824,000，利润率 64.4%。建议关注抖音渠道 ROI 优化与应收回款。` };
}

export function getBudgetSuggestion(): BudgetSuggestion {
  return {
    total_budget: 200000,
    allocations: [
      { channel: '微信', amount: 70000, roi: 3.2, reason: 'ROI 最高，建议维持并适度加码' },
      { channel: '抖音', amount: 60000, roi: 2.1, reason: '量大但成本偏高，优化素材与定向' },
      { channel: '企业微信', amount: 40000, roi: 2.8, reason: 'B2B 转化稳定，保持投入' },
      { channel: '邮件', amount: 30000, roi: 1.8, reason: '低成本触达老客户，做召回' },
    ],
  };
}

function trendOf(base: number): number[] {
  return [0.78, 0.85, 0.82, 0.94, 0.97, 1].map((f) => Math.round(base * f));
}

export function getFinancePerformance(period = 'month'): FinancePerformanceMember[] {
  const scale = period === 'quarter' ? 3 : period === 'year' ? 12 : 1;
  const raw = [
    { user_id: 1, name: '张伟', revenue: 285000, deals: 8, conversion_rate: 32, target: 300000 },
    { user_id: 2, name: '李娜', revenue: 198000, deals: 6, conversion_rate: 28, target: 220000 },
    { user_id: 3, name: '王芳', revenue: 156000, deals: 5, conversion_rate: 25, target: 200000 },
    { user_id: 4, name: '刘建', revenue: 98000, deals: 3, conversion_rate: 18, target: 150000 },
    { user_id: 5, name: '赵敏', revenue: 142000, deals: 4, conversion_rate: 22, target: 160000 },
    { user_id: 6, name: '孙浩', revenue: 76000, deals: 2, conversion_rate: 15, target: 120000 },
  ];
  return raw
    .map((m) => {
      const revenue = m.revenue * scale;
      const target = m.target * scale;
      return {
        user_id: m.user_id,
        name: m.name,
        revenue,
        deals: m.deals * scale,
        conversion_rate: m.conversion_rate,
        target,
        attainment: Math.round((revenue / target) * 1000) / 10,
        trend: trendOf(revenue),
        rank: 0,
      };
    })
    .sort((a, b) => b.revenue - a.revenue)
    .map((m, i) => ({ ...m, rank: i + 1 }));
}

export function getFinanceAlerts(): FinanceAlert[] {
  const now = Date.now();
  return [
    { id: 'fa1', type: 'cost_overrun', severity: 'high', title: '抖音渠道成本超标', message: '本月抖音投放成本超出预算 15%（¥27,000），CPC 上升明显', timestamp: new Date(now - 2 * 3600000).toISOString(), read: false },
    { id: 'fa2', type: 'channel_anomaly', severity: 'medium', title: '邮件渠道转化率下降', message: '邮件打开率周环比下降 12%，建议优化标题与发送时段', timestamp: new Date(now - 8 * 3600000).toISOString(), read: false },
    { id: 'fa3', type: 'profit_drop', severity: 'medium', title: '企业微信毛利率波动', message: '企业微信毛利率较上周下降 3.2pct，关注实施成本', timestamp: new Date(now - 26 * 3600000).toISOString(), read: false },
    { id: 'fa4', type: 'channel_anomaly', severity: 'low', title: '应收账款临近账期', message: '3 笔应收（合计 ¥86,000）将于 7 天内到期，建议提前跟进', timestamp: new Date(now - 50 * 3600000).toISOString(), read: false },
  ];
}

export function generateReport(period: string): FinanceReport {
  const csv = [
    'month,revenue,cost,profit,profit_margin',
    '2026-01,980000,380000,600000,61.2',
    '2026-02,1050000,400000,650000,61.9',
    '2026-03,1120000,420000,700000,62.5',
    '2026-04,1180000,430000,750000,63.6',
    '2026-05,1220000,440000,780000,63.9',
    '2026-06,1280000,456000,824000,64.4',
  ].join('%0A');
  return {
    id: `rpt_${Date.now()}`,
    title: `${period} 财务报表`,
    period,
    generated_at: new Date().toISOString(),
    download_url: `data:text/csv;charset=utf-8,${csv}`,
  };
}

export function getDecisionAdvice(): DecisionAdvice {
  return {
    summary: '基于当前数据，建议优先优化抖音投放效率，加大微信渠道投入，并加速应收回款以改善现金流',
    actions: [
      { title: '优化抖音素材', description: 'A/B 测试新短视频脚本，目标将 CPC 降低 12%', priority: 'high' },
      { title: '增加微信预算 10%', description: '微信 ROI 3.2x，仍有增长空间，预计新增利润 ¥32K', priority: 'medium' },
      { title: '加速应收回款', description: '对 3 笔临期应收（¥86K）提前 7 天跟进，改善现金流', priority: 'medium' },
      { title: '启动邮件召回', description: '对 30 天未活跃客户发送专属优惠，盘活存量', priority: 'low' },
    ],
  };
}
