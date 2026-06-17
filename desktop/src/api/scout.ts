import { request } from './client';
import type { ScoutTarget, IntentScore, SentimentItem, SentimentOverview, ScoutTrace } from '../types';

export const scanComments = (keyword?: string, platform?: string) =>
  request<ScoutTarget[]>('post', '/api/kellai/scout/scan', { keyword, platform });

export const scoreIntent = (comment: string) =>
  request<IntentScore>('post', '/api/kellai/scout/intent-score', { comment });

export const autoDM = (targetId: string, message: string) =>
  request<{ success: boolean; message: string }>('post', '/api/kellai/scout/auto-dm', { target_id: targetId, message });

export const convertLead = (targetId: string) =>
  request<{ success: boolean; message: string }>('post', '/api/kellai/scout/convert', { target_id: targetId });

export const getSentiment = () =>
  request<SentimentItem[]>('get', '/api/kellai/scout/sentiment');

export const getSentimentOverview = () =>
  request<SentimentOverview>('get', '/api/kellai/scout/sentiment-overview');

export const getScoutTrace = (targetId: string) =>
  request<ScoutTrace>('get', '/api/kellai/scout/trace', { target_id: targetId });

export const matchScript = (comment: string) =>
  request<{ scripts: string[] }>('post', '/api/kellai/scout/match-script', { comment });
