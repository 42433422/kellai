import { useState } from 'react';
import { PenTool, Image, Video, Send, Sparkles, Loader2 } from 'lucide-react';
import { clsx } from 'clsx';
import { useApiMutation, useApiQuery } from '../hooks/useApiQuery';
import {
  generateText,
  generateImage,
  generateVideoScript,
  publishContent,
  getAdStrategy,
} from '../api/content';
import { useContentStore } from '../stores/contentStore';
import { toastStore } from '../stores/toast';
import type { Content, AdStrategy } from '../types';

const PLATFORMS = [
  { id: 'wechat', label: '微信' },
  { id: 'douyin', label: '抖音' },
  { id: 'xiaohongshu', label: '小红书' },
  { id: 'kuaishou', label: '快手' },
];

export default function ContentStudio() {
  const [tab, setTab] = useState<'text' | 'image' | 'video_script'>('text');
  const [topic, setTopic] = useState('');
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>(['wechat']);
  const [showStrategy, setShowStrategy] = useState(false);
  const { draft, setDraft } = useContentStore();

  const strategyQuery = useApiQuery<AdStrategy>(
    ['content', 'strategy'],
    () => getAdStrategy(),
    { enabled: showStrategy }
  );

  const genMutation = useApiMutation<Content, void>(
    () => {
      if (tab === 'text') return generateText(topic);
      if (tab === 'image') return generateImage(topic);
      return generateVideoScript(topic);
    },
    {
      onSuccess: (c) => {
        setDraft(c);
        toastStore.success('内容已生成');
      },
    }
  );

  const publishMutation = useApiMutation(
    () => publishContent(draft!.id, selectedPlatforms),
    { onSuccess: () => toastStore.success('已分发至选定平台') }
  );

  const tabs = [
    { id: 'text' as const, label: '图文', icon: PenTool },
    { id: 'image' as const, label: '图片', icon: Image },
    { id: 'video_script' as const, label: '视频脚本', icon: Video },
  ];

  return (
    <div className="flex h-full flex-col space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">内容创作工作台</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400">AIGC 图文视频一键创作与分发</p>
        </div>
        <button
          type="button"
          onClick={() => setShowStrategy(true)}
          className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-gray-50 dark:border-slate-600 dark:hover:bg-slate-700"
        >
          <Sparkles className="h-4 w-4" />
          投放策略
        </button>
      </div>

      <div className="flex flex-1 gap-4 overflow-hidden">
        <div className="w-48 shrink-0 space-y-1">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={clsx(
                'flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm',
                tab === t.id ? 'bg-blue-50 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300' : 'hover:bg-gray-50 dark:hover:bg-slate-800'
              )}
            >
              <t.icon className="h-4 w-4" /> {t.label}
            </button>
          ))}
        </div>

        <div className="flex flex-1 flex-col rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="输入主题或关键词..."
            className="mb-4 rounded-lg border px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900"
          />
          <button
            type="button"
            onClick={() => genMutation.mutate()}
            disabled={genMutation.isPending || !topic}
            className="mb-4 flex items-center justify-center gap-2 rounded-lg bg-blue-600 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {genMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            AI 生成
          </button>
          {draft && (
            <div className="flex-1 overflow-y-auto rounded-lg bg-gray-50 p-4 text-sm dark:bg-slate-900">
              {draft.image_url && (
                <img src={draft.image_url} alt="" className="mb-4 max-h-48 rounded-lg object-cover" />
              )}
              <pre className="whitespace-pre-wrap font-sans">{draft.body}</pre>
            </div>
          )}
        </div>

        <div className="w-56 shrink-0 space-y-4">
          <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <h3 className="mb-2 text-sm font-semibold">分发平台</h3>
            {PLATFORMS.map((p) => (
              <label key={p.id} className="flex items-center gap-2 py-1 text-sm">
                <input
                  type="checkbox"
                  checked={selectedPlatforms.includes(p.id)}
                  onChange={(e) =>
                    setSelectedPlatforms(
                      e.target.checked
                        ? [...selectedPlatforms, p.id]
                        : selectedPlatforms.filter((x) => x !== p.id)
                    )
                  }
                />
                {p.label}
              </label>
            ))}
            <button
              type="button"
              onClick={() => publishMutation.mutate()}
              disabled={!draft || publishMutation.isPending}
              className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-green-600 py-2 text-sm text-white hover:bg-green-700 disabled:opacity-50"
            >
              <Send className="h-4 w-4" /> 一键分发
            </button>
          </div>
        </div>
      </div>

      {showStrategy && strategyQuery.data && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowStrategy(false)}>
          <div className="w-96 rounded-xl bg-white p-6 dark:bg-slate-800" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-3 font-semibold">智能投放策略</h3>
            <p className="mb-4 text-sm text-gray-600 dark:text-slate-400">{strategyQuery.data.reasoning}</p>
            {strategyQuery.data.recommended_channels.map((c) => (
              <div key={c.channel} className="mb-2 text-sm">
                <span className="font-medium">{c.label}</span> — 评分 {c.score}，最佳时段 {c.best_hours.join(', ')}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
