import { request } from './client';
import type { Content, AdStrategy, ContentAnalytics, ABTest } from '../types';

export const generateText = (topic: string) =>
  request<Content>('post', '/api/kellai/content/generate-text', { topic });

export const generateImage = (prompt: string) =>
  request<Content>('post', '/api/kellai/content/generate-image', { prompt });

export const generateVideoScript = (topic: string) =>
  request<Content>('post', '/api/kellai/content/generate-video-script', { topic });

export const publishContent = (contentId: string, platforms: string[]) =>
  request<Content>('post', '/api/kellai/content/publish', { content_id: contentId, platforms });

export const getAdStrategy = () =>
  request<AdStrategy>('post', '/api/kellai/content/ad-strategy', {});

export const getContentAnalytics = () =>
  request<ContentAnalytics>('get', '/api/kellai/content/analytics');

export const runABTest = () =>
  request<ABTest>('post', '/api/kellai/content/ab-test', {});

export const listContent = () =>
  request<Content[]>('get', '/api/kellai/content/list');
