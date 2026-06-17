import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import type { SalesFlowStep, FlowDefinition, Plugin } from '../types';
import * as salesMock from './sales';
import * as contentMock from './content';
import * as scoutMock from './scout';
import * as flowMock from './flow';
import * as financeMock from './finance';
import * as openMock from './openPlatform';

function ok<T>(config: InternalAxiosRequestConfig, data: T): AxiosResponse<T> {
  return { data, status: 200, statusText: 'OK', headers: {}, config, request: {} } as AxiosResponse<T>;
}

function safeJson(s: unknown): unknown {
  if (typeof s !== 'string') return s;
  try { return JSON.parse(s); } catch { return s; }
}

/** 处理 v3-v8 新增 API 端点，返回 null 表示未匹配 */
export async function handleExtendedRoutes(
  config: InternalAxiosRequestConfig,
  method: string,
  url: string,
  params: unknown,
  data: unknown
): Promise<AxiosResponse<unknown> | null> {
  // === v3 Sales ===
  if (url === '/api/kellai/sales/flow' && method === 'get') {
    const cid = (params as { customer_id?: number })?.customer_id ?? 1001;
    return ok(config, { success: true, data: salesMock.getOrCreateFlow(Number(cid)) });
  }
  if (url === '/api/kellai/sales/auto-flow' && method === 'post') {
    const body = data as { customer_id?: number; step?: string };
    const flow = salesMock.startAutoFlow(body.customer_id ?? 1001, body.step as SalesFlowStep | undefined);
    if (body.step) return ok(config, { success: true, data: flow });
    return ok(config, { success: true, data: salesMock.advanceFlow(body.customer_id ?? 1001) });
  }
  if (url === '/api/kellai/sales/quote' && method === 'post') {
    const body = data as { customer_id?: number };
    return ok(config, { success: true, data: salesMock.generateQuote(body.customer_id ?? 1001) });
  }
  if (url === '/api/kellai/sales/funnel-trace' && method === 'get') {
    const cid = (params as { customer_id?: number })?.customer_id;
    return ok(config, { success: true, data: salesMock.getFunnelTrace(cid) });
  }
  if (url === '/api/kellai/sales/contract' && method === 'post') {
    const body = data as { customer_id?: number; quote_id?: string };
    return ok(config, { success: true, data: salesMock.generateContract(body.customer_id ?? 1001, body.quote_id) });
  }
  const ltvMatch = url.match(/^\/api\/kellai\/sales\/ltv\/(\d+)$/);
  if (ltvMatch && method === 'get') {
    return ok(config, { success: true, data: salesMock.getLTVForecast(Number(ltvMatch[1])) });
  }
  if (url === '/api/kellai/sales/performance' && method === 'get') {
    const period = (params as { period?: string })?.period ?? 'month';
    return ok(config, { success: true, data: salesMock.getSalesPerformance(period) });
  }
  if (url === '/api/kellai/sales/attribution' && method === 'get') {
    return ok(config, { success: true, data: salesMock.getAttribution() });
  }
  if (url === '/api/kellai/sales/script-hint' && method === 'get') {
    const p = params as { customer_id?: number; stage?: string };
    return ok(config, { success: true, data: salesMock.getScriptHint(p.customer_id ?? 1001, p.stage ?? 'quoted') });
  }

  // === v4 Content ===
  if (url === '/api/kellai/content/generate-text' && method === 'post') {
    const body = data as { topic?: string };
    return ok(config, { success: true, data: contentMock.generateText(body.topic ?? '') });
  }
  if (url === '/api/kellai/content/generate-image' && method === 'post') {
    const body = data as { prompt?: string };
    return ok(config, { success: true, data: contentMock.generateImage(body.prompt ?? '') });
  }
  if (url === '/api/kellai/content/generate-video-script' && method === 'post') {
    const body = data as { topic?: string };
    return ok(config, { success: true, data: contentMock.generateVideoScript(body.topic ?? '') });
  }
  if (url === '/api/kellai/content/publish' && method === 'post') {
    const body = data as { content_id?: string; platforms?: string[] };
    return ok(config, { success: true, data: contentMock.publishContent(body.content_id ?? '', body.platforms ?? []) });
  }
  if (url === '/api/kellai/content/ad-strategy' && method === 'post') {
    return ok(config, { success: true, data: contentMock.getAdStrategy() });
  }
  if (url === '/api/kellai/content/analytics' && method === 'get') {
    return ok(config, { success: true, data: contentMock.getContentAnalytics() });
  }
  if (url === '/api/kellai/content/ab-test' && method === 'post') {
    return ok(config, { success: true, data: contentMock.getABTest() });
  }
  if (url === '/api/kellai/content/list' && method === 'get') {
    return ok(config, { success: true, data: contentMock.listContent() });
  }

  // === v5 Scout ===
  if (url === '/api/kellai/scout/scan' && method === 'post') {
    const body = data as { keyword?: string; platform?: string };
    return ok(config, { success: true, data: scoutMock.scanComments(body.keyword, body.platform) });
  }
  if (url === '/api/kellai/scout/intent-score' && method === 'post') {
    const body = data as { comment?: string };
    return ok(config, { success: true, data: scoutMock.scoreIntent(body.comment ?? '') });
  }
  if (url === '/api/kellai/scout/auto-dm' && method === 'post') {
    const body = data as { target_id?: string; message?: string };
    return ok(config, { success: true, data: scoutMock.autoDM(body.target_id ?? '', body.message ?? '') });
  }
  if (url === '/api/kellai/scout/convert' && method === 'post') {
    const body = data as { target_id?: string };
    return ok(config, { success: true, data: scoutMock.convertLead(body.target_id ?? '') });
  }
  if (url === '/api/kellai/scout/sentiment' && method === 'get') {
    return ok(config, { success: true, data: scoutMock.getSentiment() });
  }
  if (url === '/api/kellai/scout/sentiment-overview' && method === 'get') {
    return ok(config, { success: true, data: scoutMock.getSentimentOverview() });
  }
  if (url === '/api/kellai/scout/trace' && method === 'get') {
    const targetId = (params as { target_id?: string })?.target_id ?? 'st1';
    return ok(config, { success: true, data: scoutMock.getScoutTrace(targetId) });
  }
  if (url === '/api/kellai/scout/match-script' && method === 'post') {
    const body = data as { comment?: string };
    return ok(config, { success: true, data: scoutMock.matchScript(body.comment ?? '') });
  }

  // === v6 Flow ===
  if (url === '/api/kellai/flow/create' && method === 'post') {
    const body = data as { name?: string; nodes?: FlowDefinition['nodes']; edges?: FlowDefinition['edges'] };
    return ok(config, { success: true, data: flowMock.createFlow(body.name ?? '新流程', body.nodes ?? [], body.edges ?? []) });
  }
  if (url === '/api/kellai/flow/update' && method === 'put') {
    const body = data as { id?: string; name?: string; nodes?: FlowDefinition['nodes']; edges?: FlowDefinition['edges'] };
    return ok(config, { success: true, data: flowMock.updateFlow(body.id ?? '', body) });
  }
  if (url === '/api/kellai/flow/list' && method === 'get') {
    return ok(config, { success: true, data: flowMock.listFlows() });
  }
  if (url === '/api/kellai/flow/execute' && method === 'post') {
    const body = data as { flow_id?: string };
    return ok(config, { success: true, data: flowMock.executeFlow(body.flow_id ?? '') });
  }
  if (url === '/api/kellai/flow/anomalies' && method === 'get') {
    return ok(config, { success: true, data: flowMock.getAnomalies() });
  }
  if (url === '/api/kellai/flow/templates' && method === 'get') {
    return ok(config, { success: true, data: flowMock.getTemplates() });
  }
  if (url === '/api/kellai/flow/automation-rate' && method === 'get') {
    return ok(config, { success: true, data: flowMock.getAutomationRate() });
  }
  if (url === '/api/kellai/flow/webhook' && method === 'post') {
    const body = data as { url?: string; events?: string[] };
    return ok(config, { success: true, data: flowMock.registerWebhook(body.url ?? '', body.events ?? []) });
  }

  // === v7 Finance ===
  if (url === '/api/kellai/finance/dashboard' && method === 'get') {
    const period = (params as { period?: string })?.period ?? 'month';
    return ok(config, { success: true, data: financeMock.getFinanceDashboard(period) });
  }
  if (url === '/api/kellai/finance/ask' && method === 'post') {
    const body = data as { question?: string };
    return ok(config, { success: true, data: financeMock.askFinance(body.question ?? '') });
  }
  if (url === '/api/kellai/finance/budget-suggest' && method === 'get') {
    return ok(config, { success: true, data: financeMock.getBudgetSuggestion() });
  }
  if (url === '/api/kellai/finance/performance' && method === 'get') {
    const period = (params as { period?: string })?.period ?? 'month';
    return ok(config, { success: true, data: financeMock.getFinancePerformance(period) });
  }
  if (url === '/api/kellai/finance/alerts' && method === 'get') {
    return ok(config, { success: true, data: financeMock.getFinanceAlerts() });
  }
  if (url === '/api/kellai/finance/report' && method === 'get') {
    const period = (params as { period?: string })?.period ?? '2026-06';
    return ok(config, { success: true, data: financeMock.generateReport(period) });
  }
  if (url === '/api/kellai/finance/decision' && method === 'post') {
    return ok(config, { success: true, data: financeMock.getDecisionAdvice() });
  }

  // === v8 Open ===
  if (url === '/api/kellai/open/api-keys' && method === 'get') {
    return ok(config, { success: true, data: openMock.getAPIKeys() });
  }
  if (url === '/api/kellai/open/api-keys' && method === 'post') {
    const body = data as { name?: string; scopes?: string[] };
    return ok(config, { success: true, data: openMock.createAPIKey(body.name ?? '新密钥', body.scopes ?? []) });
  }
  if (url === '/api/kellai/open/api-keys/revoke' && method === 'post') {
    const body = data as { id?: string };
    return ok(config, { success: true, data: { revoked: openMock.revokeAPIKey(body.id ?? '') } });
  }
  if (url === '/api/kellai/open/stats' && method === 'get') {
    return ok(config, { success: true, data: openMock.getPlatformStats() });
  }
  if (url === '/api/kellai/open/webhooks' && method === 'get') {
    return ok(config, { success: true, data: openMock.getWebhooks() });
  }
  if (url === '/api/kellai/open/plugins' && method === 'get') {
    return ok(config, { success: true, data: openMock.getPlugins() });
  }
  if (url === '/api/kellai/open/plugins/publish' && method === 'post') {
    return ok(config, { success: true, data: openMock.publishPlugin(data as Partial<Plugin>) });
  }
  if (url === '/api/kellai/open/plugins/install' && method === 'post') {
    const body = data as { plugin_id?: string };
    return ok(config, { success: true, data: { installed: openMock.installPlugin(body.plugin_id ?? '') } });
  }
  if (url === '/api/kellai/open/isv' && method === 'get') {
    return ok(config, { success: true, data: openMock.getISVPartners() });
  }
  if (url === '/api/kellai/open/webhooks' && method === 'post') {
    const body = data as { url?: string; events?: string[] };
    return ok(config, { success: true, data: openMock.registerOpenWebhook(body.url ?? '', body.events ?? []) });
  }
  if (url === '/api/kellai/open/events' && method === 'get') {
    return ok(config, { success: true, data: openMock.getEvents() });
  }
  if (url === '/api/kellai/open/app-builder' && method === 'get') {
    return ok(config, { success: true, data: openMock.getAppTemplates() });
  }
  if (url === '/api/kellai/open/docs' && method === 'get') {
    return ok(config, { success: true, data: openMock.getAPIDocs() });
  }
  if (url === '/api/kellai/open/review' && method === 'post') {
    const body = data as { app_name?: string };
    return ok(config, { success: true, data: openMock.submitReview(body.app_name ?? '新应用') });
  }

  return null;
}

export { safeJson };
