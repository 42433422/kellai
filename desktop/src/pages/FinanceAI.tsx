import { useState, useRef, useEffect } from 'react';
import { Send, Bot, Loader2, Download, User, Trash2, PiggyBank, Lightbulb } from 'lucide-react';
import { clsx } from 'clsx';
import { useApiMutation, useApiQuery } from '../hooks/useApiQuery';
import { askFinance, getBudgetSuggestion, generateFinanceReport, getDecisionAdvice } from '../api/finance';
import { toastStore } from '../stores/toast';
import type { BudgetSuggestion, DecisionAdvice, FinanceReport } from '../types';

const PRESET_QUESTIONS = [
  '本月利润是多少？',
  '哪个渠道成本最高？',
  '营收趋势如何？',
  '现金流健康吗？',
  '下月预算怎么分配？',
];

const REPORT_PERIODS = ['2026-06', '2026-05', '2026-Q2', '2026 全年'];

const PRIORITY_TONE: Record<string, string> = {
  high: 'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-300',
  medium: 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300',
  low: 'bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-slate-300',
};
const PRIORITY_LABEL: Record<string, string> = { high: '高', medium: '中', low: '低' };

const WELCOME = '你好，我是客来来 AI 财务助手 👋 可以问我营收、成本、利润、现金流、渠道与预算相关的问题，或点击下方预设问题快速开始。';

export default function FinanceAI() {
  const [question, setQuestion] = useState('');
  const [reportPeriod, setReportPeriod] = useState(REPORT_PERIODS[0]);
  const [messages, setMessages] = useState<{ role: 'user' | 'assistant'; content: string }[]>([
    { role: 'assistant', content: WELCOME },
  ]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const askMutation = useApiMutation(
    (q: string) => askFinance(q),
    {
      onSuccess: (r) => setMessages((m) => [...m, { role: 'assistant', content: r.answer }]),
    }
  );

  const budgetQuery = useApiQuery<BudgetSuggestion>(['finance', 'budget'], () => getBudgetSuggestion());
  const decisionQuery = useApiQuery<DecisionAdvice>(['finance', 'decision'], () => getDecisionAdvice());

  const reportMutation = useApiMutation<FinanceReport, string>(
    (period) => generateFinanceReport(period),
    {
      onSuccess: (r) => {
        const a = document.createElement('a');
        a.href = r.download_url;
        a.download = `${r.title}.csv`;
        a.click();
        toastStore.success('报表已导出');
      },
    }
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, askMutation.isPending]);

  const handleAsk = (q: string) => {
    if (!q.trim() || askMutation.isPending) return;
    setQuestion('');
    setMessages((m) => [...m, { role: 'user', content: q }]);
    askMutation.mutate(q);
  };

  const budgetMax = Math.max(1, ...(budgetQuery.data?.allocations ?? []).map((a) => a.amount));

  return (
    <div className="flex h-full flex-col gap-4 flex-1 min-h-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">AI 财务助手</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400">自然语言查询财务数据、趋势与经营建议</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={reportPeriod}
            onChange={(e) => setReportPeriod(e.target.value)}
            className="rounded-lg border border-gray-300 px-2 py-2 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
          >
            {REPORT_PERIODS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => reportMutation.mutate(reportPeriod)}
            disabled={reportMutation.isPending}
            className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-700"
          >
            {reportMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} 导出报表
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {PRESET_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => handleAsk(q)}
            className="rounded-full border px-3 py-1 text-xs hover:bg-blue-50 hover:text-blue-700 dark:border-slate-600 dark:hover:bg-blue-500/10"
          >
            {q}
          </button>
        ))}
      </div>

      <div className="flex flex-1 flex-col rounded-xl border border-gray-200 bg-white dark:border-slate-700 dark:bg-slate-800 min-h-0">
        <div className="flex items-center justify-between border-b px-4 py-2 dark:border-slate-700">
          <span className="text-xs text-gray-400">对话 · {messages.filter((m) => m.role === 'user').length} 个提问</span>
          <button
            type="button"
            onClick={() => setMessages([{ role: 'assistant', content: WELCOME }])}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-red-500"
          >
            <Trash2 className="h-3.5 w-3.5" /> 清空
          </button>
        </div>
        <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4 min-h-0">
          {messages.map((m, i) => (
            <div key={i} className={clsx('flex gap-2', m.role === 'user' ? 'justify-end' : 'justify-start')}>
              {m.role === 'assistant' && <Bot className="h-6 w-6 shrink-0 rounded-full bg-blue-50 p-1 text-blue-500 dark:bg-blue-500/10" />}
              <div
                className={clsx(
                  'max-w-[80%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed',
                  m.role === 'user' ? 'rounded-br-sm bg-blue-600 text-white' : 'rounded-bl-sm bg-gray-100 text-gray-700 dark:bg-slate-700 dark:text-slate-200'
                )}
              >
                {m.content}
              </div>
              {m.role === 'user' && <User className="h-6 w-6 shrink-0 rounded-full bg-gray-100 p-1 text-gray-500 dark:bg-slate-700" />}
            </div>
          ))}
          {askMutation.isPending && (
            <div className="flex gap-2">
              <Bot className="h-6 w-6 shrink-0 rounded-full bg-blue-50 p-1 text-blue-500 dark:bg-blue-500/10" />
              <div className="flex items-center gap-1 rounded-2xl rounded-bl-sm bg-gray-100 px-4 py-3 dark:bg-slate-700">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400" />
              </div>
            </div>
          )}
        </div>
        <div className="flex gap-2 border-t p-4 dark:border-slate-700">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAsk(question)}
            placeholder="输入财务问题，回车发送..."
            className="flex-1 rounded-lg border px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
          />
          <button
            type="button"
            onClick={() => handleAsk(question)}
            disabled={askMutation.isPending || !question.trim()}
            className="rounded-lg bg-blue-600 p-2 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {askMutation.isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {budgetQuery.data && (
          <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <h3 className="mb-3 flex items-center gap-2 font-semibold text-gray-900 dark:text-slate-100">
              <PiggyBank className="h-4 w-4 text-green-500" /> 智能预算建议
              <span className="ml-auto text-sm font-normal text-gray-400">总额 ¥{budgetQuery.data.total_budget.toLocaleString()}</span>
            </h3>
            <div className="space-y-2.5">
              {budgetQuery.data.allocations.map((a) => (
                <div key={a.channel}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className="text-gray-700 dark:text-slate-300">{a.channel}</span>
                    <span className="text-gray-500">¥{a.amount.toLocaleString()} · ROI {a.roi}x</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-gray-100 dark:bg-slate-700">
                    <div className="h-full rounded-full bg-green-500" style={{ width: `${(a.amount / budgetMax) * 100}%` }} />
                  </div>
                  <p className="mt-0.5 text-xs text-gray-400">{a.reason}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {decisionQuery.data && (
          <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <h3 className="mb-2 flex items-center gap-2 font-semibold text-gray-900 dark:text-slate-100">
              <Lightbulb className="h-4 w-4 text-amber-500" /> AI 决策建议
            </h3>
            <p className="mb-3 text-sm text-gray-600 dark:text-slate-400">{decisionQuery.data.summary}</p>
            <div className="space-y-2">
              {decisionQuery.data.actions.map((a, i) => (
                <div key={i} className="flex items-start gap-2 rounded-lg bg-gray-50 p-2.5 dark:bg-slate-900">
                  <span className={clsx('mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium', PRIORITY_TONE[a.priority])}>
                    {PRIORITY_LABEL[a.priority]}
                  </span>
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-slate-100">{a.title}</p>
                    <p className="text-xs text-gray-500 dark:text-slate-400">{a.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
