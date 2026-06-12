import { useState } from 'react';
import { Send, Bot, Loader2, Download } from 'lucide-react';
import { useApiMutation, useApiQuery } from '../hooks/useApiQuery';
import { askFinance, getBudgetSuggestion, generateFinanceReport, getDecisionAdvice } from '../api/finance';
import type { BudgetSuggestion, DecisionAdvice, FinanceReport } from '../types';

const PRESET_QUESTIONS = [
  '本月利润是多少？',
  '哪个渠道成本最高？',
  '营收趋势如何？',
];

export default function FinanceAI() {
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<{ role: 'user' | 'assistant'; content: string }[]>([]);

  const askMutation = useApiMutation(
    (q: string) => askFinance(q),
    {
      onSuccess: (r) => {
        setMessages((m) => [...m, { role: 'assistant', content: r.answer }]);
      },
    }
  );

  const budgetQuery = useApiQuery<BudgetSuggestion>(
    ['finance', 'budget'],
    () => getBudgetSuggestion()
  );

  const decisionQuery = useApiQuery<DecisionAdvice>(
    ['finance', 'decision'],
    () => getDecisionAdvice()
  );

  const reportMutation = useApiMutation<FinanceReport, string>(
    (period) => generateFinanceReport(period),
    {
      onSuccess: (r) => {
        const a = document.createElement('a');
        a.href = r.download_url;
        a.download = `${r.title}.csv`;
        a.click();
      },
    }
  );

  const handleAsk = (q: string) => {
    setQuestion(q);
    setMessages((m) => [...m, { role: 'user', content: q }]);
    askMutation.mutate(q);
  };

  return (
    <div className="flex h-full flex-col space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">AI 财务助手</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400">自然语言查询财务数据与趋势</p>
        </div>
        <button
          type="button"
          onClick={() => reportMutation.mutate('2026-06')}
          className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-gray-50 dark:border-slate-600 dark:hover:bg-slate-700"
        >
          <Download className="h-4 w-4" /> 导出报表
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {PRESET_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => handleAsk(q)}
            className="rounded-full border px-3 py-1 text-xs hover:bg-gray-50 dark:border-slate-600 dark:hover:bg-slate-700"
          >
            {q}
          </button>
        ))}
      </div>

      <div className="flex flex-1 flex-col rounded-xl border border-gray-200 bg-white dark:border-slate-700 dark:bg-slate-800">
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.map((m, i) => (
            <div
              key={i}
              className={`flex gap-2 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              {m.role === 'assistant' && <Bot className="h-5 w-5 shrink-0 text-blue-500" />}
              <div
                className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                  m.role === 'user'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 dark:bg-slate-700'
                }`}
              >
                {m.content}
              </div>
            </div>
          ))}
        </div>
        <div className="flex gap-2 border-t p-4 dark:border-slate-700">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && question && handleAsk(question)}
            placeholder="输入财务问题..."
            className="flex-1 rounded-lg border px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900"
          />
          <button
            type="button"
            onClick={() => question && handleAsk(question)}
            disabled={askMutation.isPending}
            className="rounded-lg bg-blue-600 p-2 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {askMutation.isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {budgetQuery.data && (
        <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
          <h3 className="mb-2 font-semibold">智能预算建议</h3>
          {budgetQuery.data.allocations.map((a) => (
            <div key={a.channel} className="mb-1 text-sm">
              {a.channel}: ¥{a.amount.toLocaleString()} (ROI {a.roi}x) — {a.reason}
            </div>
          ))}
        </div>
      )}

      {decisionQuery.data && (
        <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
          <h3 className="mb-2 font-semibold">AI 决策建议</h3>
          <p className="mb-2 text-sm text-gray-600 dark:text-slate-400">{decisionQuery.data.summary}</p>
          {decisionQuery.data.actions.map((a, i) => (
            <div key={i} className="mb-1 text-sm">
              <span className="font-medium">{a.title}</span> — {a.description}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
