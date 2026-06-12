import { request } from './client';
import type { ScoutTarget, IntentScore, SentimentItem, ScoutTrace } from '../types';

export const scanComments = (keyword?: string) =>
  request<ScoutTarget[]>('post', '/api/kellai/scout/scan', { keyword });

export const scoreIntent = (comment: string) =>
  request<IntentScore>('post', '/api/kellai/scout/intent-score', { comment });

export const autoDM = (targetId: string, message: string) =>
  request<{ success: boolean; message: string }>('post', '/api/kellai/scout/auto-dm', { target_id: targetId, message });

export const getSentiment = () =>
  request<SentimentItem[]>('get', '/api/kellai/scout/sentiment');

export const getScoutTrace = (targetId: string) =>
  request<ScoutTrace>('get', '/api/kellai/scout/trace', { target_id: targetId });

export const matchScript = (comment: string) =>
  request<{ scripts: string[] }>('post', '/api/kellai/scout/match-script', { comment });
