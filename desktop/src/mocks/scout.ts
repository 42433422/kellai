import type { ScoutTarget, IntentScore, SentimentItem, SentimentOverview, ScoutTrace } from '../types';

const scoutTargets: ScoutTarget[] = [
  { id: 'st1', platform: 'douyin', post_title: 'CRM 系统选型指南', comment: '有没有支持 AI 自动回复的？我们团队急需，怎么收费', author: '创业小王', intent_score: 92, intent_level: 'high', reason: '明确表达购买需求并询价', scanned_at: '2026-06-13T08:00:00Z', source_url: 'https://douyin.com/note/1', followers: 12400, region: '广东 · 深圳', industry: 'SaaS', status: 'new', tags: ['急需', '怎么收费', 'AI'] },
  { id: 'st2', platform: 'xiaohongshu', post_title: '销售工具推荐 2026', comment: '客来来有人用过吗？效果怎么样，想了解下', author: '运营Lisa', intent_score: 78, intent_level: 'high', reason: '主动询问产品口碑', scanned_at: '2026-06-13T07:30:00Z', source_url: 'https://xiaohongshu.com/note/2', followers: 8600, region: '上海', industry: '电商', status: 'contacted', tags: ['有没有', '了解'] },
  { id: 'st3', platform: 'douyin', post_title: '竞品X vs 竞品Y', comment: '价格太贵了，有没有平替推荐', author: '精打细算', intent_score: 65, intent_level: 'medium', reason: '价格敏感但有真实需求', scanned_at: '2026-06-13T06:00:00Z', source_url: 'https://douyin.com/note/3', followers: 3200, region: '浙江 · 杭州', industry: '零售', status: 'new', tags: ['平替', '价格'] },
  { id: 'st4', platform: 'kuaishou', post_title: '中小企业数字化', comment: '了解一下你们的方案', author: '路人甲', intent_score: 35, intent_level: 'low', reason: '意向不明确，需培育', scanned_at: '2026-06-13T05:00:00Z', source_url: 'https://kuaishou.com/note/4', followers: 540, region: '四川 · 成都', industry: '制造', status: 'new', tags: ['了解'] },
  { id: 'st5', platform: 'weibo', post_title: '获客难，求支招', comment: '现在私域获客成本太高了，求好用的工具，最好能自动跟进', author: '增长黑客', intent_score: 81, intent_level: 'high', reason: '痛点明确，需求强烈', scanned_at: '2026-06-13T04:20:00Z', source_url: 'https://weibo.com/note/5', followers: 25800, region: '北京', industry: '互联网', status: 'replied', tags: ['获客', '自动跟进'] },
  { id: 'st6', platform: 'xiaohongshu', post_title: '私域运营复盘', comment: '想找个能管理客户全生命周期的系统', author: '私域阿May', intent_score: 72, intent_level: 'high', reason: '需求清晰，关注全生命周期', scanned_at: '2026-06-13T03:10:00Z', source_url: 'https://xiaohongshu.com/note/6', followers: 15300, region: '广东 · 广州', industry: '教育', status: 'new', tags: ['客户管理'] },
  { id: 'st7', platform: 'douyin', post_title: 'AI 销售实测', comment: '这种 AI 销售真的有用吗，会不会很假', author: '理性吃瓜', intent_score: 48, intent_level: 'medium', reason: '有兴趣但存疑虑', scanned_at: '2026-06-13T02:00:00Z', source_url: 'https://douyin.com/note/7', followers: 7100, region: '江苏 · 南京', industry: '服务', status: 'new', tags: ['AI', '效果'] },
  { id: 'st8', platform: 'weibo', post_title: '企业微信运营技巧', comment: '随便看看', author: '划水王', intent_score: 22, intent_level: 'low', reason: '浏览型，无明确意向', scanned_at: '2026-06-13T01:00:00Z', source_url: 'https://weibo.com/note/8', followers: 320, region: '湖北 · 武汉', industry: '其他', status: 'ignored', tags: [] },
];

export function scanComments(keyword?: string, platform?: string): ScoutTarget[] {
  let list = scoutTargets;
  if (platform && platform !== 'all') list = list.filter((t) => t.platform === platform);
  if (keyword) {
    list = list.filter(
      (t) => t.comment.includes(keyword) || t.post_title.includes(keyword) || (t.industry ?? '').includes(keyword)
    );
  }
  return list;
}

export function scoreIntent(comment: string): IntentScore {
  const highKw = ['急需', '购买', '报价', '怎么收费', '有没有', '推荐一个'];
  const medKw = ['了解', '推荐', '对比', '效果', '平替', '想找'];
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
  return {
    comment,
    score,
    level,
    keywords,
    reason: keywords.length
      ? `命中 ${keywords.length} 个意向关键词，综合判定为${level === 'high' ? '高' : level === 'medium' ? '中' : '低'}意向`
      : '未命中明显意向关键词，建议培育',
  };
}

export function autoDM(targetId: string, message: string): { success: boolean; message: string } {
  const target = scoutTargets.find((t) => t.id === targetId);
  if (!target) return { success: false, message: '目标不存在' };
  if (target.status === 'new') target.status = 'contacted';
  return { success: true, message: `已向 @${target.author} 发送私信：${message.slice(0, 40)}...` };
}

/** 将猎手线索转入 CRM（mock：更新状态） */
export function convertLead(targetId: string): { success: boolean; message: string } {
  const target = scoutTargets.find((t) => t.id === targetId);
  if (!target) return { success: false, message: '目标不存在' };
  target.status = 'converted';
  return { success: true, message: `@${target.author} 已转入 CRM 客户库，进入「已建联」阶段` };
}

export function getSentiment(): SentimentItem[] {
  return [
    { id: 's1', type: 'hotspot', title: 'AI 获客工具热度上升', summary: '行业讨论量周环比 +45%，多个头部账号发布测评内容', severity: 'high', timestamp: '2026-06-13T09:00:00Z', sentiment: 'positive', sentiment_score: 82, volume: 1240, volume_change: 45, source: '抖音 / 小红书', url: 'https://example.com/s1', keywords: ['AI获客', '测评', '自动化'] },
    { id: 's2', type: 'competitor', title: '竞品 X 发布评论区自动触达', summary: '竞品上线新功能，部分用户反馈触达过于频繁引发反感', severity: 'medium', timestamp: '2026-06-12T15:00:00Z', sentiment: 'negative', sentiment_score: 38, volume: 680, volume_change: 12, source: '微博', url: 'https://example.com/s2', keywords: ['竞品X', '骚扰', '触达'] },
    { id: 's3', type: 'opportunity', title: '教育行业数字化招标季', summary: '3 个大型招标即将截止，预算合计超 2000 万', severity: 'high', timestamp: '2026-06-12T10:00:00Z', sentiment: 'positive', sentiment_score: 76, volume: 420, volume_change: 28, source: '招标网', url: 'https://example.com/s3', keywords: ['招标', '教育', '数字化'] },
    { id: 's4', type: 'hotspot', title: '私域运营成本讨论', summary: '中小企业普遍反映私域获客成本上升，寻求降本工具', severity: 'medium', timestamp: '2026-06-12T08:00:00Z', sentiment: 'neutral', sentiment_score: 55, volume: 910, volume_change: 8, source: '小红书', url: 'https://example.com/s4', keywords: ['私域', '成本', '降本'] },
    { id: 's5', type: 'competitor', title: '竞品 Y 降价促销', summary: '竞品 Y 推出 5 折年付活动，需关注客户流失风险', severity: 'high', timestamp: '2026-06-11T19:00:00Z', sentiment: 'negative', sentiment_score: 32, volume: 560, volume_change: 60, source: '公众号', url: 'https://example.com/s5', keywords: ['竞品Y', '降价', '促销'] },
    { id: 's6', type: 'opportunity', title: '某连锁品牌咨询批量采购', summary: '连锁餐饮品牌在社群咨询 50+ 坐席采购', severity: 'medium', timestamp: '2026-06-11T11:00:00Z', sentiment: 'positive', sentiment_score: 80, volume: 130, volume_change: 15, source: '企业微信', url: 'https://example.com/s6', keywords: ['批量采购', '连锁', '餐饮'] },
  ];
}

export function getSentimentOverview(): SentimentOverview {
  return {
    total: 3940,
    positive_pct: 52,
    neutral_pct: 31,
    negative_pct: 17,
    volume_change: 23,
    volume_trend: [
      { date: '06-07', count: 280 },
      { date: '06-08', count: 320 },
      { date: '06-09', count: 410 },
      { date: '06-10', count: 380 },
      { date: '06-11', count: 520 },
      { date: '06-12', count: 610 },
      { date: '06-13', count: 720 },
    ],
    top_keywords: [
      { word: 'AI获客', count: 412 },
      { word: '私域', count: 356 },
      { word: '客户管理', count: 298 },
      { word: '自动跟进', count: 241 },
      { word: '竞品X', count: 187 },
      { word: '招标', count: 142 },
      { word: '降本', count: 118 },
    ],
    watch_terms: ['客来来', 'AI获客', '私域运营', 'CRM', '竞品X', '竞品Y'],
  };
}

export function getScoutTrace(targetId: string): ScoutTrace {
  return {
    target_id: targetId,
    steps: [
      { action: '评论巡检', timestamp: '2026-06-10T08:00:00Z', result: 'AI 在抖音评论区发现高意向评论' },
      { action: '意向评分', timestamp: '2026-06-10T08:01:00Z', result: '综合评分 92，判定为高意向' },
      { action: '自动私信', timestamp: '2026-06-10T08:05:00Z', result: '已发送个性化触达话术' },
      { action: '客户回复', timestamp: '2026-06-10T14:00:00Z', result: '客户表达进一步兴趣并留下联系方式' },
      { action: '转入漏斗', timestamp: '2026-06-11T09:00:00Z', result: '已转入 CRM，阶段：已建联' },
    ],
    converted: true,
  };
}

export function matchScript(comment: string): { scripts: string[] } {
  const score = scoreIntent(comment);
  if (score.level === 'high') {
    return {
      scripts: [
        '您好！看到您对 AI 获客很感兴趣，我们有一站式解决方案，方便私信详聊吗？',
        '感谢关注！我可以为您安排 15 分钟产品演示，看看是否契合您的场景',
        '您提到的需求我们正好擅长，本周有专属优惠，要不要先免费试用？',
      ],
    };
  }
  if (score.level === 'medium') {
    return {
      scripts: [
        '您好，关于您的疑问我可以详细解答，方便加个微信深入聊聊吗？',
        '我们有同行业的成功案例，分享给您参考一下？',
      ],
    };
  }
  return {
    scripts: ['您好，感谢评论！有任何问题欢迎随时交流', '我们提供免费试用，感兴趣可以了解一下'],
  };
}

export function getScoutTargets(): ScoutTarget[] {
  return scoutTargets;
}
