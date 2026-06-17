import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileText,
  DollarSign,
  Loader2,
  Play,
  ChevronRight,
  Search,
  Target,
  Calendar,
  User,
  CheckCircle2,
  Circle,
  Copy,
  Sparkles,
  MessageSquare,
  Clock,
} from 'lucide-react';
import { clsx } from 'clsx';
import StepWizard from '../components/StepWizard';
import ProgressRing from '../components/ProgressRing';
import { useApiQuery, useApiMutation, useQueryClient } from '../hooks/useApiQuery';
import {
  getFlow,
  startAutoFlow,
  generateQuote,
  generateContract,
  getLTVForecast,
  getScriptHint,
} from '../api/sales';
import { useSalesStore } from '../stores/salesStore';
import { toastStore } from '../stores/toast';
import { MOCK_CUSTOMERS } from '../mocks/customers';
import { formatTimeAgo } from '../utils/format';
import type { SalesFlow, Quote, Contract, LTVForecast, SalesScriptHint, SalesFlowStep } from '../types';
import { FLOW_STEPS, STEP_LABELS } from '../mocks/sales';

const WIZARD_STEPS = FLOW_STEPS.map((id) => ({ id, label: STEP_LABELS[id] }));

/** 销售流程步骤 → 话术库 stage 的映射 */
const STEP_TO_HINT: Record<SalesFlowStep, string> = {
  requirement: 'proposal',
  proposal: 'proposal',
  promotion: 'quoted',
  signing: 'pending_sign',
};

export default function SalesFlow() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { selectedCustomerId, setSelectedCustomer, setActiveFlow, setActiveQuote } = useSalesStore();
  const [customerId, setCustomerId] = useState(selectedCustomerId ?? MOCK_CUSTOMERS[0]?.customer_id ?? 1001);
  const [search, setSearch] = useState('');

  const flowQuery = useApiQuery<SalesFlow>(
    ['sales', 'flow', customerId],
    () => getFlow(customerId),
    { enabled: !!customerId }
  );

  const ltvQuery = useApiQuery<LTVForecast>(
    ['sales', 'ltv', customerId],
    () => getLTVForecast(customerId),
    { enabled: !!customerId }
  );

  const flow = flowQuery.data;
  const currentStep = (flow?.current_step ?? 'requirement') as SalesFlowStep;

  const scriptQuery = useApiQuery<SalesScriptHint>(
    ['sales', 'script', customerId, currentStep],
    () => getScriptHint(customerId, STEP_TO_HINT[currentStep] ?? 'proposal'),
    { enabled: !!customerId }
  );

  const advanceMutation = useApiMutation<SalesFlow, void>(
    () => startAutoFlow(customerId),
    {
      onSuccess: (next) => {
        setActiveFlow(next);
        if (next.status === 'completed') {
          toastStore.success('🎉 商机已赢单，恭喜成交！');
        } else {
          toastStore.success(`流程已推进至「${STEP_LABELS[next.current_step]}」`);
        }
        queryClient.invalidateQueries({ queryKey: ['sales', 'flow', customerId] });
      },
    }
  );

  const quoteMutation = useApiMutation<Quote, void>(
    () => generateQuote(customerId),
    {
      onSuccess: (quote) => {
        setActiveQuote(quote);
        toastStore.success('智能报价已生成');
      },
    }
  );

  const contractMutation = useApiMutation<Contract, void>(
    () => generateContract(customerId, quoteMutation.data?.id),
    {
      onSuccess: () => toastStore.success('合同已生成，等待电子签约'),
    }
  );

  useEffect(() => {
    setSelectedCustomer(customerId);
  }, [customerId, setSelectedCustomer]);

  const filteredCustomers = useMemo(() => {
    const kw = search.trim().toLowerCase();
    if (!kw) return MOCK_CUSTOMERS;
    return MOCK_CUSTOMERS.filter(
      (c) =>
        c.display_name?.toLowerCase().includes(kw) ||
        c.company?.toLowerCase().includes(kw)
    );
  }, [search]);

  const quote = quoteMutation.data;
  const contract = contractMutation.data;
  const isCompleted = flow?.status === 'completed';

  const copySignUrl = () => {
    if (!contract?.sign_url) return;
    navigator.clipboard?.writeText(contract.sign_url).then(
      () => toastStore.success('签约链接已复制'),
      () => toastStore.error('复制失败，请手动复制')
    );
  };

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-auto min-h-0" data-tour="sales-flow-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">自动销售流程</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
            AI 驱动的需求确认 → 方案推荐 → 促单 → 签约全流程
          </p>
        </div>
        {flow && (
          <span
            className={clsx(
              'rounded-full px-3 py-1 text-xs font-medium',
              isCompleted
                ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-300'
                : 'bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300'
            )}
          >
            {isCompleted ? '已赢单' : flow.status === 'running' ? '进行中' : '待启动'}
          </span>
        )}
      </div>

      {/* 商机概览条 */}
      {flow && (
        <div className="grid grid-cols-2 gap-4 rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800 lg:grid-cols-4">
          <div className="flex items-center gap-3">
            <ProgressRing value={flow.win_probability ?? 0} size={56} strokeWidth={5} />
            <div>
              <p className="text-xs text-gray-500 dark:text-slate-400">赢单概率</p>
              <p className="text-sm font-semibold text-gray-900 dark:text-slate-100">AI 实时预测</p>
            </div>
          </div>
          <Metric icon={DollarSign} label="商机金额" value={`¥${((flow.deal_value ?? 0) / 10000).toFixed(1)}万`} />
          <Metric icon={Calendar} label="预计成交" value={flow.expected_close_date ?? '-'} />
          <Metric icon={User} label="负责人" value={flow.owner ?? '-'} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* 客户选择 */}
        <div className="lg:col-span-3">
          <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <h3 className="mb-3 text-sm font-semibold text-gray-700 dark:text-slate-200">选择商机客户</h3>
            <div className="relative mb-3">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索客户 / 公司"
                className="w-full rounded-lg border border-gray-300 py-1.5 pl-8 pr-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
              />
            </div>
            <div className="max-h-[26rem] space-y-1 overflow-y-auto">
              {filteredCustomers.map((c) => (
                <button
                  key={c.customer_id}
                  type="button"
                  onClick={() => setCustomerId(c.customer_id)}
                  className={clsx(
                    'flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-colors',
                    customerId === c.customer_id
                      ? 'bg-blue-50 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300'
                      : 'hover:bg-gray-50 dark:hover:bg-slate-700'
                  )}
                >
                  <span className="truncate">{c.display_name}</span>
                  <span className="ml-2 shrink-0 text-xs text-gray-400">{c.stage_label}</span>
                </button>
              ))}
              {filteredCustomers.length === 0 && (
                <p className="py-6 text-center text-xs text-gray-400">未找到匹配客户</p>
              )}
            </div>
          </div>
        </div>

        {/* 流程向导 + AI 洞察 */}
        <div className="lg:col-span-6 space-y-4">
          <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800" data-tour="sales-flow-wizard">
            <StepWizard steps={WIZARD_STEPS} currentStep={currentStep} />

            <div className="mt-8 space-y-4">
              {/* AI 洞察 */}
              <div className="rounded-lg border border-blue-100 bg-blue-50/60 p-4 dark:border-blue-500/20 dark:bg-blue-500/10">
                <div className="mb-1.5 flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-blue-500" />
                  <h4 className="text-sm font-semibold text-gray-900 dark:text-slate-100">
                    {STEP_LABELS[currentStep]} · AI 洞察
                  </h4>
                </div>
                {flowQuery.isLoading ? (
                  <div className="h-4 w-2/3 animate-pulse rounded bg-blue-100 dark:bg-blue-500/20" />
                ) : (
                  <p className="text-sm leading-relaxed text-gray-600 dark:text-slate-300">{flow?.ai_insight}</p>
                )}
              </div>

              {/* 待办清单 */}
              {flow?.checklist && (
                <div className="rounded-lg bg-gray-50 p-4 dark:bg-slate-900">
                  <p className="mb-2 text-xs font-medium text-gray-500 dark:text-slate-400">本阶段待办</p>
                  <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                    {flow.checklist.map((item, i) => {
                      const done = (flow.steps_completed?.length ?? 0) > 0 && i === 0;
                      return (
                        <div key={item} className="flex items-center gap-2 text-sm text-gray-700 dark:text-slate-300">
                          {done ? (
                            <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" />
                          ) : (
                            <Circle className="h-4 w-4 shrink-0 text-gray-300 dark:text-slate-600" />
                          )}
                          <span className={clsx(done && 'text-gray-400 line-through')}>{item}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* 下一步最佳行动 */}
              {flow?.next_action && (
                <div className="flex items-start gap-2 rounded-lg border border-amber-100 bg-amber-50 p-3 text-sm dark:border-amber-500/20 dark:bg-amber-500/10">
                  <Target className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                  <div>
                    <span className="font-medium text-amber-700 dark:text-amber-300">下一步：</span>
                    <span className="text-gray-700 dark:text-slate-300">{flow.next_action}</span>
                  </div>
                </div>
              )}

              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => advanceMutation.mutate()}
                  disabled={advanceMutation.isPending || isCompleted}
                  className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {advanceMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  {isCompleted ? '流程已完成' : '推进流程'}
                </button>
                <button
                  type="button"
                  onClick={() => quoteMutation.mutate()}
                  disabled={quoteMutation.isPending}
                  className="flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium hover:bg-gray-50 dark:border-slate-600 dark:hover:bg-slate-700"
                >
                  {quoteMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <DollarSign className="h-4 w-4" />}
                  生成报价
                </button>
              </div>
            </div>
          </div>

          {/* 流程时间线 */}
          {flow?.timeline && flow.timeline.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
              <div className="mb-3 flex items-center gap-2">
                <Clock className="h-4 w-4 text-gray-400" />
                <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">流程时间线</h3>
              </div>
              <ol className="space-y-3">
                {[...flow.timeline].reverse().map((t, i) => (
                  <li key={`${t.at}-${i}`} className="flex gap-3">
                    <div className="flex flex-col items-center">
                      <span className="mt-1 h-2 w-2 rounded-full bg-blue-500" />
                      {i < flow.timeline!.length - 1 && <span className="h-full w-px flex-1 bg-gray-200 dark:bg-slate-700" />}
                    </div>
                    <div className="pb-1">
                      <p className="text-sm text-gray-800 dark:text-slate-200">{t.note}</p>
                      <p className="text-xs text-gray-400">{formatTimeAgo(t.at)}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>

        {/* 右侧：LTV + 报价明细 + 合同 + 话术 */}
        <div className="space-y-4 lg:col-span-3">
          <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <h3 className="mb-2 text-sm font-semibold text-gray-700 dark:text-slate-200">LTV 预测</h3>
            {ltvQuery.isLoading ? (
              <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
            ) : ltvQuery.data ? (
              <>
                <p className="text-2xl font-bold text-green-600 dark:text-green-400">
                  ¥{ltvQuery.data.predicted_ltv.toLocaleString()}
                </p>
                <p className="mt-0.5 text-xs text-gray-400">
                  置信度 {(ltvQuery.data.confidence * 100).toFixed(0)}%
                </p>
                <p className="mt-1 text-xs text-gray-500 dark:text-slate-400">{ltvQuery.data.recommendation}</p>
              </>
            ) : null}
          </div>

          {quote && (
            <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
              <h3 className="mb-2 text-sm font-semibold text-gray-700 dark:text-slate-200">智能报价明细</h3>
              <div className="space-y-1.5">
                {quote.items.map((it) => (
                  <div key={it.name} className="flex justify-between text-xs">
                    <span className="text-gray-500 dark:text-slate-400">
                      {it.name} ×{it.quantity}
                    </span>
                    <span className="font-medium text-gray-800 dark:text-slate-200">¥{it.total.toLocaleString()}</span>
                  </div>
                ))}
              </div>
              <div className="mt-2 space-y-1 border-t border-gray-100 pt-2 dark:border-slate-700">
                <div className="flex justify-between text-xs text-gray-500">
                  <span>小计</span>
                  <span>¥{quote.subtotal.toLocaleString()}</span>
                </div>
                <div className="flex justify-between text-xs text-amber-600 dark:text-amber-400">
                  <span>折扣</span>
                  <span>-{(quote.discount * 100).toFixed(0)}%</span>
                </div>
                <div className="flex justify-between text-sm font-bold text-gray-900 dark:text-slate-100">
                  <span>合计</span>
                  <span>¥{quote.total.toLocaleString()}</span>
                </div>
              </div>
              <p className="mt-1 text-[11px] text-gray-400">有效期至 {quote.valid_until}</p>
            </div>
          )}

          {contract ? (
            <div className="rounded-xl border border-green-200 bg-green-50/50 p-4 dark:border-green-500/20 dark:bg-green-500/10">
              <h3 className="mb-1 text-sm font-semibold text-gray-800 dark:text-slate-100">{contract.title}</h3>
              <p className="text-xs leading-relaxed text-gray-600 dark:text-slate-400">{contract.content_preview}</p>
              <button
                type="button"
                onClick={copySignUrl}
                className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-green-300 bg-white py-1.5 text-xs font-medium text-green-700 hover:bg-green-50 dark:border-green-500/30 dark:bg-slate-800 dark:text-green-300"
              >
                <Copy className="h-3.5 w-3.5" />
                复制电子签约链接
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => contractMutation.mutate()}
              disabled={contractMutation.isPending || !quote}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-green-600 px-4 py-3 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              {contractMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
              {quote ? '生成合同' : '请先生成报价'}
            </button>
          )}

          {/* 话术建议 */}
          {scriptQuery.data && (
            <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
              <div className="mb-2 flex items-center gap-2">
                <MessageSquare className="h-4 w-4 text-blue-500" />
                <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-200">AI 话术建议</h3>
              </div>
              <div className="space-y-1.5">
                {scriptQuery.data.scripts.map((s, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() =>
                      navigator.clipboard?.writeText(s).then(() => toastStore.success('话术已复制'))
                    }
                    className="block w-full rounded-lg bg-gray-50 px-3 py-2 text-left text-xs text-gray-600 transition-colors hover:bg-blue-50 hover:text-blue-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-blue-500/10"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          <button
            type="button"
            onClick={() => navigate(`/customers/${customerId}`)}
            className="flex w-full items-center justify-center gap-1 text-sm text-blue-600 hover:underline dark:text-blue-400"
          >
            查看客户详情 <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof DollarSign;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-100 dark:bg-slate-700">
        <Icon className="h-5 w-5 text-blue-500 dark:text-blue-400" />
      </div>
      <div>
        <p className="text-xs text-gray-500 dark:text-slate-400">{label}</p>
        <p className="text-sm font-semibold text-gray-900 dark:text-slate-100">{value}</p>
      </div>
    </div>
  );
}
