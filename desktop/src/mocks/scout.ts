import type { ScoutTarget, IntentScore, SentimentItem, ScoutTrace } from '../types';

const scoutTargets: ScoutTarget[] = [
  { id: 'st1', platform: 'douyin', post_title: 'CRM 系统选型指南', comment: '有没有支持 AI 自动回复的？我们团队急需', author: '创业小王', intent_score: 92, intent_level: 'high', reason: '明确表达购买需求', scanned_at: '2026-06-12T08:00:00Z' },
  { id: 'st2', platform: 'xiaohongshu', post_title: '销售工具推荐 2026', comment: '客来来有人用过吗？效果怎么样', author: '运营Lisa', intent_score: 78, intent_level: 'high', reason: '主动询问产品', scanned_at: '2026-06-12T07:30:00Z' },
  { id: 'st3', platform: 'douyin', post_title: '竞品X vs 竞品Y', comment: '价格太贵了，有没有平替', author: '精打细算', intent_score: 65, intent_level: 'medium', reason: '价格敏感但有需求', scanned_at: '2026-06-12T06:00:00Z' },
  { id: 'st4', platform: 'kuaishou', post_title: '中小企业数字化', comment: '了解一下', author: '路人甲', intent_score: 35, intent_level: 'low', reason: '意向不明确', scanned_at: '2026-06-12T05:00:00Z' },
];

export function scanComments(keyword?: string): ScoutTarget[] {
  if (!keyword) return scoutTargets;
  return scoutTargets.filter(
    (t) => t.comment.includes(keyword) || t.post_title.includes(keyword)
  );
}

export function scoreIntent(comment: string): IntentScore {
  const highKw = ['急需', '购买', '报价', '怎么收费', '有没有'];
  const medKw = ['了解', '推荐', '对比', '效果'];
  let score = 30;
  const keywords: string[] = [];
  for (const kw of highKw) {
    if (comment.includes(kw)) { score += 20; keywords.push(kw); }
  }
  for (const kw of medKw) {
    if (comment.includes(kw)) { score += 10; keywords.push(kw); }
  }
  score = Math.min(100, score);
  const level = score >= 70 ? 'high' : score >= 45 ? 'medium' : 'low';
  return { comment, score, level, keywords, reason: `基于关键词分析，意向等级 ${level}` };
}

export function autoDM(targetId: string, message: string): { success: boolean; message: string } {
  const target = scoutTargets.find((t) => t.id === targetId);
  if (!target) return { success: false, message: '目标不存在' };
  return { success: true, message: `已向 ${target.author} 发送私信：${message.slice(0, 50)}...` };
}

export function getSentiment(): SentimentItem[] {
  return [
    { id: 's1', type: 'hotspot', title: 'AI 获客工具热度上升', summary: '行业讨论量周环比 +45%', severity: 'high', timestamp: '2026-06-12T09:00:00Z' },
    { id: 's2', type: 'competitor', title: '竞品 X 发布新功能', summary: '新增评论区自动触达，需关注', severity: 'medium', timestamp: '2026-06-11T15:00:00Z' },
    { id: 's3', type: 'opportunity', title: '教育行业招标季', summary: '3 个大型招标即将截止', severity: 'high', timestamp: '2026-06-11T10:00:00Z' },
  ];
}

export function getScoutTrace(targetId: string): ScoutTrace {
  return {
    target_id: targetId,
    steps: [
      { action: '评论巡检', timestamp: '2026-06-10T08:00:00Z', result: '发现高意向评论' },
      { action: '自动私信', timestamp: '2026-06-10T08:05:00Z', result: '私信已发送' },
      { action: '客户回复', timestamp: '2026-06-10T14:00:00Z', result: '表达进一步兴趣' },
      { action: '转入漏斗', timestamp: '2026-06-11T09:00:00Z', result: '阶段：已建联' },
    ],
    converted: true,
  };
}

export function matchScript(comment: string): { scripts: string[] } {
  const score = scoreIntent(comment);
  if (score.level === 'high') {
    return { scripts: ['您好！看到您对 AI 获客很感兴趣，我们有一站式解决方案，方便私信详聊吗？', '感谢关注！我可以为您安排 15 分钟产品演示'] };
  }
  return { scripts: ['您好，感谢评论！有任何问题欢迎随时交流', '我们提供免费试用，感兴趣可以了解一下'] };
}

export function getScoutTargets(): ScoutTarget[] {
  return scoutTargets;
}
