import { useEffect, useState } from 'react';
import { Award, Plus, Loader2, Key, Copy, Trash2, Webhook, ShieldCheck } from 'lucide-react';
import { clsx } from 'clsx';
import { useApiQuery, useApiMutation, useQueryClient } from '../hooks/useApiQuery';
import {
  getAPIKeys,
  createAPIKey,
  revokeAPIKey,
  getISVPartners,
  registerOpenWebhook,
  getWebhooks,
  getEventSubscriptions,
  submitAppReview,
} from '../api/openPlatform';
import { useOpenPlatformStore } from '../stores/openPlatformStore';
import { toastStore } from '../stores/toast';
import { formatTimeAgo } from '../utils/format';
import type { ISVPartner, APIKey, WebhookConfig, EventSubscription } from '../types';

const TIER_META = {
  gold: { color: 'text-amber-500', label: '金牌' },
  silver: { color: 'text-gray-400', label: '银牌' },
  bronze: { color: 'text-amber-700', label: '铜牌' },
};

const SCOPE_OPTIONS = ['customers:read', 'customers:write', 'messages:read', 'messages:write', 'sales:read', 'finance:read'];

export default function DeveloperPortal() {
  const queryClient = useQueryClient();
  const [keyName, setKeyName] = useState('');
  const [keyScopes, setKeyScopes] = useState<string[]>(['customers:read']);
  const [newApiKey, setNewApiKey] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [appName, setAppName] = useState('');
  const [events, setEvents] = useState<EventSubscription[]>([]);
  const { addWebhook } = useOpenPlatformStore();

  const keysQuery = useApiQuery<APIKey[]>(['open', 'keys'], () => getAPIKeys());
  const isvQuery = useApiQuery<ISVPartner[]>(['open', 'isv'], () => getISVPartners());
  const webhooksQuery = useApiQuery<WebhookConfig[]>(['open', 'webhooks'], () => getWebhooks());
  const eventsQuery = useApiQuery<EventSubscription[]>(['open', 'events'], () => getEventSubscriptions());

  useEffect(() => {
    if (events.length === 0 && eventsQuery.data?.length) {
      setEvents(eventsQuery.data);
    }
  }, [events.length, eventsQuery.data]);

  const keyMutation = useApiMutation(
    () => createAPIKey(keyName || '开发密钥', keyScopes),
    {
      onSuccess: (created) => {
        toastStore.success('API 密钥已创建');
        setNewApiKey(created.api_key || '');
        setKeyName('');
        queryClient.invalidateQueries({ queryKey: ['open', 'keys'] });
      },
    }
  );

  const revokeMutation = useApiMutation(
    (id: string) => revokeAPIKey(id),
    {
      onSuccess: () => {
        toastStore.success('密钥已吊销');
        queryClient.invalidateQueries({ queryKey: ['open', 'keys'] });
      },
    }
  );

  const webhookMutation = useApiMutation(
    () => registerOpenWebhook(webhookUrl, ['customer.created', 'message.received']),
    {
      onSuccess: () => {
        addWebhook(webhookUrl);
        toastStore.success('Webhook 已注册');
        setWebhookUrl('');
        queryClient.invalidateQueries({ queryKey: ['open', 'webhooks'] });
      },
    }
  );

  const reviewMutation = useApiMutation(
    () => submitAppReview(appName),
    { onSuccess: () => { toastStore.success('应用已提交审核'); setAppName(''); } }
  );

  const copy = (text: string, label: string) =>
    navigator.clipboard?.writeText(text).then(() => toastStore.success(`${label}已复制`));

  const toggleScope = (s: string) =>
    setKeyScopes((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">开发者门户</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">API 密钥、Webhook、事件订阅与 ISV 认证</p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* API 密钥 */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
          <h3 className="mb-4 flex items-center gap-2 font-semibold text-gray-900 dark:text-slate-100">
            <Key className="h-4 w-4 text-blue-500" /> API 密钥
          </h3>
          <div className="mb-4 space-y-2">
            {(keysQuery.data ?? []).map((k) => (
              <div key={k.id} className="rounded-lg border border-gray-100 p-3 dark:border-slate-700">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-900 dark:text-slate-100">{k.name}</span>
                  <div className="flex items-center gap-2">
                    <button type="button" onClick={() => copy(k.key_prefix, '密钥')} className="text-gray-400 hover:text-blue-500" title="复制">
                      <Copy className="h-3.5 w-3.5" />
                    </button>
                    <button type="button" onClick={() => revokeMutation.mutate(k.id)} className="text-gray-400 hover:text-red-500" title="吊销">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                <code className="text-xs text-gray-500">{k.key_prefix}</code>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {k.scopes.map((s) => (
                    <span key={s} className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-600 dark:bg-blue-500/10 dark:text-blue-300">{s}</span>
                  ))}
                </div>
                {k.last_used_at && <p className="mt-1 text-[11px] text-gray-400">最近使用 {formatTimeAgo(k.last_used_at)}</p>}
              </div>
            ))}
          </div>
          <div className="space-y-2 border-t border-gray-100 pt-3 dark:border-slate-700">
            {newApiKey && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-500/20 dark:bg-amber-500/10">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-amber-800 dark:text-amber-200">仅显示一次的完整密钥</p>
                    <code className="mt-1 block truncate text-xs text-amber-900 dark:text-amber-100">{newApiKey}</code>
                  </div>
                  <button
                    type="button"
                    onClick={() => copy(newApiKey, '完整密钥')}
                    className="shrink-0 rounded-md border border-amber-300 px-2 py-1 text-xs text-amber-800 hover:bg-amber-100 dark:border-amber-400/30 dark:text-amber-100 dark:hover:bg-amber-500/20"
                  >
                    复制
                  </button>
                </div>
              </div>
            )}
            <input
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              placeholder="密钥名称（如：生产环境）"
              className="w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
            />
            <div className="flex flex-wrap gap-1.5">
              {SCOPE_OPTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => toggleScope(s)}
                  className={clsx(
                    'rounded-full px-2 py-0.5 text-[11px]',
                    keyScopes.includes(s) ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-500 dark:bg-slate-700 dark:text-slate-300'
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => keyMutation.mutate()}
              disabled={keyMutation.isPending}
              className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {keyMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} 创建密钥
            </button>
          </div>
        </div>

        {/* Webhook */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
          <h3 className="mb-4 flex items-center gap-2 font-semibold text-gray-900 dark:text-slate-100">
            <Webhook className="h-4 w-4 text-green-500" /> Webhook
          </h3>
          <div className="mb-4 space-y-2">
            {(webhooksQuery.data ?? []).map((w) => (
              <div key={w.id} className="rounded-lg border border-gray-100 p-3 dark:border-slate-700">
                <div className="flex items-center justify-between">
                  <code className="truncate text-xs text-gray-700 dark:text-slate-300">{w.url}</code>
                  <span className={clsx('shrink-0 rounded px-1.5 py-0.5 text-[10px]', w.active ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-300' : 'bg-gray-100 text-gray-500')}>
                    {w.active ? '活跃' : '停用'}
                  </span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {w.events.map((e) => (
                    <span key={e} className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500 dark:bg-slate-700 dark:text-slate-300">{e}</span>
                  ))}
                </div>
                <button type="button" onClick={() => copy(w.secret, 'Secret')} className="mt-1 flex items-center gap-1 text-[11px] text-gray-400 hover:text-blue-500">
                  <Copy className="h-3 w-3" /> 复制签名密钥
                </button>
              </div>
            ))}
            {(webhooksQuery.data ?? []).length === 0 && <p className="text-xs text-gray-400">暂无 Webhook</p>}
          </div>
          <div className="space-y-2 border-t border-gray-100 pt-3 dark:border-slate-700">
            <input
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              placeholder="https://your-server.com/webhook"
              className="w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
            />
            <button
              type="button"
              onClick={() => webhookMutation.mutate()}
              disabled={!webhookUrl || webhookMutation.isPending}
              className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm text-white hover:bg-green-700 disabled:opacity-50"
            >
              {webhookMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} 注册 Webhook
            </button>
          </div>
        </div>
      </div>

      {/* 事件订阅 */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
        <h3 className="mb-4 font-semibold text-gray-900 dark:text-slate-100">事件订阅</h3>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {events.map((ev) => (
            <button
              key={ev.id}
              type="button"
              onClick={() => setEvents((prev) => prev.map((x) => (x.id === ev.id ? { ...x, subscribed: !x.subscribed } : x)))}
              className="flex items-center justify-between rounded-lg border border-gray-100 p-3 text-left dark:border-slate-700"
            >
              <div>
                <code className="text-sm text-gray-800 dark:text-slate-200">{ev.event_type}</code>
                <p className="text-xs text-gray-400">{ev.description}</p>
              </div>
              <span className={clsx('flex h-5 w-9 items-center rounded-full px-0.5 transition-colors', ev.subscribed ? 'justify-end bg-blue-500' : 'justify-start bg-gray-300 dark:bg-slate-600')}>
                <span className="h-4 w-4 rounded-full bg-white" />
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* 应用审核 */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
        <h3 className="mb-4 font-semibold text-gray-900 dark:text-slate-100">应用审核</h3>
        <div className="flex gap-2">
          <input
            value={appName}
            onChange={(e) => setAppName(e.target.value)}
            placeholder="提交应用名称进行上架审核"
            className="flex-1 rounded-lg border px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
          />
          <button
            type="button"
            onClick={() => reviewMutation.mutate()}
            disabled={!appName || reviewMutation.isPending}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            提交审核
          </button>
        </div>
      </div>

      {/* ISV 合作伙伴 */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
        <h3 className="mb-4 font-semibold text-gray-900 dark:text-slate-100">ISV 合作伙伴</h3>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
          {(isvQuery.data ?? []).map((p) => (
            <div key={p.id} className="rounded-lg border border-gray-100 p-4 dark:border-slate-700">
              <div className="flex items-center gap-2">
                <Award className={clsx('h-5 w-5', TIER_META[p.tier].color)} />
                <span className="font-medium text-gray-900 dark:text-slate-100">{p.name}</span>
              </div>
              <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
                <span className="rounded bg-gray-100 px-1.5 py-0.5 dark:bg-slate-700">{TIER_META[p.tier].label}</span>
                <span>{p.solutions} 个方案</span>
                {p.certified && <span className="flex items-center gap-0.5 text-green-600 dark:text-green-400"><ShieldCheck className="h-3 w-3" /> 已认证</span>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
