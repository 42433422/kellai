import api from './client';

export { getReminders, type FollowUpReminder } from './ai';

/** 获取最近消息 / 线索动态 */
export const getRecentMessages = (limit = 10) =>
  api.get('/api/kellai/messages', { params: { limit } });

/** 漏斗阶段概览（与 Dashboard.tsx 一致） */
interface FunnelStage {
  id: string;
  name: string;
  count: number;
  percentage: number;
}

/** 漏斗概览响应（后端返回对象，包含 stages 数组） */
interface FunnelSummaryResponse {
  stages?: Array<{ id: string; name: string; count: number; percentage?: number }>;
  stage_definitions?: Array<{ id: string; label: string; count: number }>;
  total_clients?: number;
  counts?: Record<string, number>;
}

/** 标准化漏斗阶段：将后端返回的对象转换为前端需要的 FunnelStage[] */
function normalizeFunnelStages(data: unknown): FunnelStage[] {
  if (!data || typeof data !== 'object') return [];

  const d = data as FunnelSummaryResponse;

  // 后端返回 { stages: [...] }
  if (Array.isArray(d.stages)) {
    return d.stages.map((s) => ({
      id: s.id,
      name: s.name || s.id,
      count: s.count ?? 0,
      percentage: s.percentage ?? 0,
    }));
  }

  // 后端返回 { stage_definitions: [...] }
  if (Array.isArray(d.stage_definitions)) {
    return d.stage_definitions.map((s) => ({
      id: s.id,
      name: s.label || s.id,
      count: s.count ?? 0,
      percentage: 0,
    }));
  }

  // 如果数据本身是数组（防御性编程）
  if (Array.isArray(data)) {
    return (data as Array<{ id: string; name: string; count: number; percentage?: number }>).map((s) => ({
      id: s.id,
      name: s.name || s.id,
      count: s.count ?? 0,
      percentage: s.percentage ?? 0,
    }));
  }

  return [];
}

/** 获取漏斗概览数据 */
export const getFunnelSummary = () =>
  api.get('/api/kellai/pipeline/funnel');

export { normalizeFunnelStages };
