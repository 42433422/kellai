import { useState } from 'react';
import { Award, Plus, Loader2 } from 'lucide-react';
import { clsx } from 'clsx';
import { useApiQuery, useApiMutation } from '../hooks/useApiQuery';
import { getISVPartners, createAPIKey, registerOpenWebhook, submitAppReview } from '../api/openPlatform';
import { useOpenPlatformStore } from '../stores/openPlatformStore';
import { toastStore } from '../stores/toast';
import type { ISVPartner } from '../types';

const TIER_COLORS = {
  gold: 'text-amber-500',
  silver: 'text-gray-400',
  bronze: 'text-amber-700',
};

export default function DeveloperPortal() {
  const [webhookUrl, setWebhookUrl] = useState('');
  const [appName, setAppName] = useState('');
  const { addWebhook } = useOpenPlatformStore();

  const isvQuery = useApiQuery<ISVPartner[]>(['open', 'isv'], () => getISVPartners());

  const keyMutation = useApiMutation(
    () => createAPIKey('开发密钥', ['customers:read', 'messages:read']),
    { onSuccess: () => toastStore.success('API 密钥已创建') }
  );

  const webhookMutation = useApiMutation(
    () => registerOpenWebhook(webhookUrl, ['customer.created', 'message.received']),
    {
      onSuccess: () => {
        addWebhook(webhookUrl);
        toastStore.success('Webhook 已注册');
        setWebhookUrl('');
      },
    }
  );

  const reviewMutation = useApiMutation(
    () => submitAppReview(appName),
    { onSuccess: () => toastStore.success('应用已提交审核') }
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">开发者门户</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">ISV 认证、API 密钥与 Webhook 管理</p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
          <h3 className="mb-4 font-semibold">API 密钥</h3>
          <button
            type="button"
            onClick={() => keyMutation.mutate()}
            disabled={keyMutation.isPending}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
          >
            {keyMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            创建密钥
          </button>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
          <h3 className="mb-4 font-semibold">Webhook 注册</h3>
          <input
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
            placeholder="https://your-server.com/webhook"
            className="mb-3 w-full rounded-lg border px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900"
          />
          <button
            type="button"
            onClick={() => webhookMutation.mutate()}
            disabled={!webhookUrl || webhookMutation.isPending}
            className="rounded-lg bg-green-600 px-4 py-2 text-sm text-white hover:bg-green-700 disabled:opacity-50"
          >
            注册
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
        <h3 className="mb-4 font-semibold">应用审核</h3>
        <div className="flex gap-2">
          <input
            value={appName}
            onChange={(e) => setAppName(e.target.value)}
            placeholder="应用名称"
            className="flex-1 rounded-lg border px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900"
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

      <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
        <h3 className="mb-4 font-semibold">ISV 合作伙伴</h3>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {(isvQuery.data ?? []).map((p) => (
            <div key={p.id} className="rounded-lg border p-4 dark:border-slate-700">
              <div className="flex items-center gap-2">
                <Award className={clsx('h-5 w-5', TIER_COLORS[p.tier])} />
                <span className="font-medium">{p.name}</span>
              </div>
              <p className="mt-1 text-sm text-gray-500">{p.solutions} 个解决方案 · {p.certified ? '已认证' : '待认证'}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
