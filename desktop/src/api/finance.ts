import { request } from './client';
import type {
  FinanceDashboardData,
  BudgetSuggestion,
  FinancePerformanceMember,
  FinanceAlert,
  FinanceReport,
  DecisionAdvice,
} from '../types';

export const getFinanceDashboard = (period = 'month') =>
  request<FinanceDashboardData>('get', '/api/kellai/finance/dashboard', { period });

export const askFinance = (question: string) =>
  request<{ answer: string }>('post', '/api/kellai/finance/ask', { question });

export const getBudgetSuggestion = () =>
  request<BudgetSuggestion>('get', '/api/kellai/finance/budget-suggest');

export const getFinancePerformance = (period = 'month') =>
  request<FinancePerformanceMember[]>('get', '/api/kellai/finance/performance', { period });

export const getFinanceAlerts = () =>
  request<FinanceAlert[]>('get', '/api/kellai/finance/alerts');

export const generateFinanceReport = (period: string) =>
  request<FinanceReport>('get', '/api/kellai/finance/report', { period });

export const getDecisionAdvice = () =>
  request<DecisionAdvice>('post', '/api/kellai/finance/decision', {});
