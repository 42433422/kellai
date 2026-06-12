import { useState } from 'react';
import { Search, Star, Send, Loader2, MessageCircle } from 'lucide-react';
import { clsx } from 'clsx';
import { useApiQuery, useApiMutation } from '../hooks/useApiQuery';
import { scanComments, autoDM, matchScript, getScoutTrace } from '../api/scout';
import { useScoutStore } from '../stores/scoutStore';
import { toastStore } from '../stores/toast';
import type { ScoutTarget, ScoutTrace } from '../types';

function IntentStars({ score }: { score: number }) {
  const level = score >= 70 ? 5 : score >= 55 ? 4 : score >= 40 ? 3 : score >= 25 ? 2 : 1;
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star
          key={i}
          className={clsx('h-3.5 w-3.5', i < level ? 'fill-amber-400 text-amber-400' : 'text-gray-300')}
        />
      ))}
    </div>
  );
}

export default function ScoutHunter() {
  const [keyword, setKeyword] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dmMessage, setDmMessage] = useState('');
  const { setHighIntentQueue } = useScoutStore();

  const scanQuery = useApiQuery<ScoutTarget[]>(
    ['scout', 'scan', keyword],
    () => scanComments(keyword || undefined),
    { enabled: true }
  );

  const traceQuery = useApiQuery<ScoutTrace>(
    ['scout', 'trace', selectedId],
    () => getScoutTrace(selectedId!),
    { enabled: !!selectedId }
  );

  const dmMutation = useApiMutation(
    ({ targetId, message }: { targetId: string; message: string }) => autoDM(targetId, message),
    { onSuccess: (r) => toastStore.success(r.message) }
  );

  const scriptMutation = useApiMutation(
    (comment: string) => matchScript(comment),
    {
      onSuccess: (r) => {
        if (r.scripts[0]) setDmMessage(r.scripts[0]);
      },
    }
  );

  const targets = scanQuery.data ?? [];
  const highIntent = targets.filter((t) => t.intent_level === 'high');

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">猎手巡检台</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">AI 扫描评论区，识别高意向客户</p>
      </div>

      <div className="flex gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索关键词..."
            className="w-full rounded-lg border py-2 pl-10 pr-4 text-sm dark:border-slate-600 dark:bg-slate-800"
          />
        </div>
        <button
          type="button"
          onClick={() => {
            scanQuery.refetch();
            setHighIntentQueue(highIntent);
          }}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
        >
          开始巡检
        </button>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-3">
          {targets.map((t) => (
            <div
              key={t.id}
              className={clsx(
                'cursor-pointer rounded-xl border p-4 transition-colors dark:bg-slate-800',
                selectedId === t.id ? 'border-blue-500 bg-blue-50/50 dark:border-blue-400' : 'border-gray-200 dark:border-slate-700'
              )}
              onClick={() => setSelectedId(t.id)}
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs text-gray-500">{t.platform} · {t.post_title}</span>
                <IntentStars score={t.intent_score} />
              </div>
              <p className="text-sm font-medium text-gray-900 dark:text-slate-100">{t.comment}</p>
              <p className="mt-1 text-xs text-gray-500">@{t.author} — {t.reason}</p>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    scriptMutation.mutate(t.comment);
                    setSelectedId(t.id);
                  }}
                  className="text-xs text-blue-600 hover:underline dark:text-blue-400"
                >
                  匹配话术
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <MessageCircle className="h-4 w-4" /> 自动私信
            </h3>
            <textarea
              value={dmMessage}
              onChange={(e) => setDmMessage(e.target.value)}
              rows={4}
              className="mb-3 w-full rounded-lg border px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900"
              placeholder="输入或匹配话术..."
            />
            <button
              type="button"
              onClick={() => selectedId && dmMutation.mutate({ targetId: selectedId, message: dmMessage })}
              disabled={!selectedId || !dmMessage || dmMutation.isPending}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-green-600 py-2 text-sm text-white hover:bg-green-700 disabled:opacity-50"
            >
              {dmMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              发送私信
            </button>
          </div>

          {traceQuery.data && (
            <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
              <h3 className="mb-3 text-sm font-semibold">来源追踪</h3>
              {traceQuery.data.steps.map((s, i) => (
                <div key={i} className="mb-2 border-l-2 border-blue-400 pl-3 text-sm">
                  <p className="font-medium">{s.action}</p>
                  <p className="text-xs text-gray-500">{s.result}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
