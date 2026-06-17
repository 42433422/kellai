import { request } from './client';
import type {
  SalesFlow,
  SalesFlowStep,
  Quote,
  Contract,
  LTVForecast,
  SalesPerformance,
  AttributionReport,
  FunnelTrace,
  SalesScriptHint,
} from '../types';

export const getFlow = (customerId: number) =>
  request<SalesFlow>('get', '/api/kellai/sales/flow', { customer_id: customerId });

export const startAutoFlow = (customerId: number, step?: SalesFlowStep) =>
  request<SalesFlow>('post', '/api/kellai/sales/auto-flow', { customer_id: customerId, step });

export const generateQuote = (customerId: number) =>
  request<Quote>('post', '/api/kellai/sales/quote', { customer_id: customerId });

export const getFunnelTrace = (customerId?: number) =>
  request<FunnelTrace>('get', '/api/kellai/sales/funnel-trace', customerId ? { customer_id: customerId } : undefined);

export const generateContract = (customerId: number, quoteId?: string) =>
  request<Contract>('post', '/api/kellai/sales/contract', { customer_id: customerId, quote_id: quoteId });

export const getLTVForecast = (customerId: number) =>
  request<LTVForecast>('get', `/api/kellai/sales/ltv/${customerId}`);

export const getSalesPerformance = (period = 'month') =>
  request<SalesPerformance>('get', '/api/kellai/sales/performance', { period });

export const getAttribution = () =>
  request<AttributionReport>('get', '/api/kellai/sales/attribution');

export const getScriptHint = (customerId: number, stage: string) =>
  request<SalesScriptHint>('get', '/api/kellai/sales/script-hint', { customer_id: customerId, stage });
