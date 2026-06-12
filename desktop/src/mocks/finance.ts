import type { FinanceDashboardData, BudgetSuggestion, FinancePerformanceMember, FinanceAlert, FinanceReport, DecisionAdvice } from '../types';

export function getFinanceDashboard(): FinanceDashboardData {
  return {
    revenue: 1280000,
    cost: 456000,
    profit: 824000,
    profit_margin: 64.4,
    channel_breakdown: [
      { channel: '微信', revenue: 448000, cost: 120000, profit: 328000 },
      { channel: '抖音', revenue: 384000, cost: 180000, profit: 204000 },
      { channel: '企业微信', revenue: 256000, cost: 80000, profit: 176000 },
      { channel: '邮件', revenue: 192000, cost: 76000, profit: 116000 },
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

export function askFinance(question: string): { answer: string } {
  const q = question.toLowerCase();
  if (q.includes('利润') || q.includes('profit')) {
    return { answer: '本月利润 ¥824,000，利润率 64.4%，环比上月增长 5.6%。微信渠道利润贡献最高（¥328,000）。' };
  }
  if (q.includes('成本') || q.includes('cost')) {
    return { answer: '本月总成本 ¥456,000，抖音渠道成本占比最高（39%），建议优化投放策略。' };
  }
  return { answer: `关于「${question}」：本月营收 ¥1,280,000，同比增长 18%。建议关注抖音渠道 ROI 优化。` };
}

export function getBudgetSuggestion(): BudgetSuggestion {
  return {
    total_budget: 200000,
    allocations: [
      { channel: '微信', amount: 70000, roi: 3.2, reason: 'ROI 最高，建议维持' },
      { channel: '抖音', amount: 60000, roi: 2.1, reason: '量大但成本偏高，优化素材' },
      { channel: '企业微信', amount: 40000, roi: 2.8, reason: 'B2B 转化稳定' },
      { channel: '邮件', amount: 30000, roi: 1.8, reason: '低成本触达老客户' },
    ],
  };
}

export function getFinancePerformance(): FinancePerformanceMember[] {
  return [
    { user_id: 1, name: '张伟', revenue: 285000, deals: 8, conversion_rate: 32, rank: 1 },
    { user_id: 2, name: '李娜', revenue: 198000, deals: 6, conversion_rate: 28, rank: 2 },
    { user_id: 3, name: '王芳', revenue: 156000, deals: 5, conversion_rate: 25, rank: 3 },
    { user_id: 4, name: '刘建', revenue: 98000, deals: 3, conversion_rate: 18, rank: 4 },
  ];
}

export function getFinanceAlerts(): FinanceAlert[] {
  return [
    { id: 'fa1', type: 'cost_overrun', severity: 'high', title: '抖音渠道成本超标', message: '本月抖音投放成本超出预算 15%', timestamp: new Date().toISOString(), read: false },
    { id: 'fa2', type: 'channel_anomaly', severity: 'medium', title: '邮件渠道转化率下降', message: '邮件打开率周环比下降 12%', timestamp: new Date().toISOString(), read: false },
  ];
}

export function generateReport(period: string): FinanceReport {
  return {
    id: `rpt_${Date.now()}`,
    title: `${period} 财务报表`,
    period,
    generated_at: new Date().toISOString(),
    download_url: 'data:text/csv;charset=utf-8,month,revenue,cost,profit%0A2026-06,1280000,456000,824000',
  };
}

export function getDecisionAdvice(): DecisionAdvice {
  return {
    summary: '基于当前数据，建议优先优化抖音投放效率，加大微信渠道投入',
    actions: [
      { title: '优化抖音素材', description: 'A/B 测试新短视频脚本，降低 CPC', priority: 'high' },
      { title: '增加微信预算 10%', description: '微信 ROI 3.2x，仍有增长空间', priority: 'medium' },
      { title: '启动邮件召回', description: '对 30 天未活跃客户发送优惠', priority: 'low' },
    ],
  };
}
