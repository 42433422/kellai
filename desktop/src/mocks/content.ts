import type { Content, AdStrategy, ContentAnalytics, ABTest } from '../types';

const contentStore: Content[] = [
  {
    id: 'c1',
    type: 'text',
    title: '618 智能获客方案',
    body: '客来来 AI 助力企业全渠道获客，转化率提升 2.8 倍...',
    status: 'published',
    platforms: ['wechat', 'douyin'],
    created_at: '2026-06-01T10:00:00Z',
    published_at: '2026-06-01T12:00:00Z',
  },
];

export function generateText(topic: string): Content {
  const content: Content = {
    id: `c_${Date.now()}`,
    type: 'text',
    title: topic || 'AI 营销推文',
    body: `【${topic}】\n\n在数字化获客时代，企业需要智能化工具提升效率。客来来提供全渠道统一管理、AI 自动对话、智能销售闭环，助力业务增长。\n\n#智能获客 #AI销售`,
    status: 'draft',
    platforms: [],
    created_at: new Date().toISOString(),
  };
  contentStore.unshift(content);
  return content;
}

export function generateImage(prompt: string): Content {
  const content: Content = {
    id: `img_${Date.now()}`,
    type: 'image',
    title: prompt || '营销海报',
    body: prompt,
    image_url: `https://picsum.photos/seed/${Date.now()}/800/600`,
    status: 'draft',
    platforms: [],
    created_at: new Date().toISOString(),
  };
  contentStore.unshift(content);
  return content;
}

export function generateVideoScript(topic: string): Content {
  const content: Content = {
    id: `vs_${Date.now()}`,
    type: 'video_script',
    title: `${topic} - 短视频脚本`,
    body: `【开场 0-3s】痛点引入\n【主体 3-20s】产品亮点展示\n【结尾 20-30s】行动号召：扫码咨询\n\n旁白：${topic}，让 AI 帮你搞定获客！`,
    status: 'draft',
    platforms: [],
    created_at: new Date().toISOString(),
  };
  contentStore.unshift(content);
  return content;
}

export function publishContent(contentId: string, platforms: string[]): Content | null {
  const c = contentStore.find((x) => x.id === contentId);
  if (!c) return null;
  c.status = 'published';
  c.platforms = platforms;
  c.published_at = new Date().toISOString();
  return c;
}

export function getAdStrategy(): AdStrategy {
  return {
    recommended_channels: [
      { channel: 'douyin', label: '抖音', score: 92, best_hours: ['12:00-14:00', '19:00-22:00'] },
      { channel: 'wechat', label: '微信', score: 85, best_hours: ['08:00-10:00', '20:00-22:00'] },
      { channel: 'xiaohongshu', label: '小红书', score: 78, best_hours: ['18:00-21:00'] },
    ],
    budget_split: [
      { channel: 'douyin', pct: 40 },
      { channel: 'wechat', pct: 35 },
      { channel: 'xiaohongshu', pct: 25 },
    ],
    reasoning: '基于受众画像（25-40岁企业决策者），抖音短视频转化最高，微信适合深度内容',
  };
}

export function getContentAnalytics(): ContentAnalytics {
  return {
    items: [
      { content_id: 'c1', title: '618 智能获客方案', platform: '微信', views: 12500, likes: 890, shares: 234, conversions: 45, ctr: 3.6 },
      { content_id: 'c1', title: '618 智能获客方案', platform: '抖音', views: 45000, likes: 3200, shares: 890, conversions: 78, ctr: 1.7 },
    ],
    totals: { views: 57500, likes: 4090, conversions: 123 },
  };
}

export function getABTest(): ABTest {
  return {
    id: 'ab1',
    name: '标题 A/B 测试',
    status: 'running',
    variants: [
      { id: 'va', name: '版本 A：效率提升', content: 'AI 获客效率提升 2.8 倍', views: 5000, conversions: 120, win_rate: 58 },
      { id: 'vb', name: '版本 B：成本降低', content: '获客成本降低 45%', views: 4800, conversions: 95, win_rate: 42 },
    ],
  };
}

export function listContent(): Content[] {
  return contentStore;
}
