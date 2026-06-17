import { request } from './client';
import type {
  APIKey,
  Plugin,
  ISVPartner,
  WebhookConfig,
  EventSubscription,
  AppTemplate,
  ReviewStatus,
  PlatformStats,
  ApiEndpointDoc,
} from '../types';

export const getAPIKeys = () =>
  request<APIKey[]>('get', '/api/kellai/open/api-keys');

export const createAPIKey = (name: string, scopes: string[]) =>
  request<APIKey>('post', '/api/kellai/open/api-keys', { name, scopes });

export const revokeAPIKey = (id: string) =>
  request<{ revoked: boolean }>('post', '/api/kellai/open/api-keys/revoke', { id });

export const getPlatformStats = () =>
  request<PlatformStats>('get', '/api/kellai/open/stats');

export const getWebhooks = () =>
  request<WebhookConfig[]>('get', '/api/kellai/open/webhooks');

export const getPlugins = () =>
  request<Plugin[]>('get', '/api/kellai/open/plugins');

export const publishPlugin = (data: Partial<Plugin>) =>
  request<Plugin>('post', '/api/kellai/open/plugins/publish', data);

export const installPlugin = (pluginId: string) =>
  request<{ installed: boolean }>('post', '/api/kellai/open/plugins/install', { plugin_id: pluginId });

export const getISVPartners = () =>
  request<ISVPartner[]>('get', '/api/kellai/open/isv');

export const registerOpenWebhook = (url: string, events: string[]) =>
  request<WebhookConfig>('post', '/api/kellai/open/webhooks', { url, events });

export const getEventSubscriptions = () =>
  request<EventSubscription[]>('get', '/api/kellai/open/events');

export const getAppTemplates = () =>
  request<AppTemplate[]>('get', '/api/kellai/open/app-builder');

export const getAPIDocs = () =>
  request<{ endpoints: ApiEndpointDoc[] }>('get', '/api/kellai/open/docs');

export const submitAppReview = (appName: string) =>
  request<ReviewStatus>('post', '/api/kellai/open/review', { app_name: appName });
