import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, DollarSign, Loader2, Play, ChevronRight } from 'lucide-react';
import { clsx } from 'clsx';
import StepWizard from '../components/StepWizard';
import { useApiQuery, useApiMutation, useQueryClient } from '../hooks/useApiQuery';
import {
  startAutoFlow,
  generateQuote,
  generateContract,
  getLTVForecast,
} from '../api/sales';
import { useSalesStore } from '../stores/salesStore';
import { toastStore } from '../stores/toast';
import { MOCK_CUSTOMERS } from '../mocks/customers';
import type { SalesFlow, Quote, LTVForecast, SalesFlowStep } from '../types';
import { FLOW_STEPS, STEP_LABELS } from '../mocks/sales';

const WIZARD_STEPS = FLOW_STEPS.map((id) => ({ id, label: STEP_LABELS[id] }));

export default function SalesFlow() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { selectedCustomerId, setSelectedCustomer, setActiveFlow, setActiveQuote } = useSalesStore();
  const [customerId, setCustomerId] = useState(selectedCustomerId ?? MOCK_CUSTOMERS[0]?.customer_id ?? 1001);

  const ltvQuery = useApiQuery<LTVForecast>(
    ['sales', 'ltv', customerId],
    () => getLTVForecast(customerId),
    { enabled: !!customerId }
  );

  const flowMutation = useApiMutation<SalesFlow, { advance?: boolean }>(
    () => startAutoFlow(customerId),
    {
      onSuccess: (flow) => {
        setActiveFlow(flow);
        toastStore.success(`流程已推进至「${STEP_LABELS[flow.current_step]}」`);
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

  const contractMutation = useApiMutation(
    () => generateContract(customerId, quoteMutation.data?.id),
    {
      onSuccess: () => toastStore.success('合同已生成，等待电子签约'),
    }
  );

  const currentStep = flowMutation.data?.current_step ?? 'requirement';

  useEffect(() => {
    setSelectedCustomer(customerId);
  }, [customerId, setSelectedCustomer]);

  return (
    <div className="space-y-6" data-tour="sales-flow-page">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">自动销售流程</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
          AI 驱动的需求确认 → 方案推荐 → 促单 → 签约全流程
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* 客户选择 */}
        <div className="lg:col-span-3">
          <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <h3 className="mb-3 text-sm font-semibold text-gray-700 dark:text-slate-200">选择客户</h3>
            <div className="max-h-96 space-y-1 overflow-y-auto">
              {MOCK_CUSTOMERS.map((c) => (
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
                  <span>{c.display_name}</span>
                  <span className="text-xs text-gray-400">{c.stage_label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* 流程向导 */}
        <div className="lg:col-span-6">
          <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800" data-tour="sales-flow-wizard">
            <StepWizard steps={WIZARD_STEPS} currentStep={currentStep} />
            <div className="mt-8 space-y-4">
              <div className="rounded-lg bg-gray-50 p-4 dark:bg-slate-900">
                <h4 className="font-medium text-gray-900 dark:text-slate-100">
                  当前步骤：{STEP_LABELS[currentStep as SalesFlowStep]}
                </h4>
                <p className="mt-2 text-sm text-gray-600 dark:text-slate-400">
                  {currentStep === 'requirement' && 'AI 正在分析客户需求，确认预算与决策链...'}
                  {currentStep === 'proposal' && '根据客户画像生成个性化方案推荐...'}
                  {currentStep === 'promotion' && '识别促单时机，推送限时优惠策略...'}
                  {currentStep === 'signing' && '生成电子合同，引导客户完成签约...'}
                </p>
              </div>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => flowMutation.mutate({})}
                  disabled={flowMutation.isPending}
                  className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {flowMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  推进流程
                </button>
                <button
                  type="button"
                  onClick={() => quoteMutation.mutate()}
                  disabled={quoteMutation.isPending}
                  className="flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium hover:bg-gray-50 dark:border-slate-600 dark:hover:bg-slate-700"
                >
                  <DollarSign className="h-4 w-4" />
                  生成报价
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* 右侧：LTV + 报价 + 合同 */}
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
                <p className="mt-1 text-xs text-gray-500">{ltvQuery.data.recommendation}</p>
              </>
            ) : null}
          </div>

          {quoteMutation.data && (
            <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
              <h3 className="mb-2 text-sm font-semibold">智能报价</h3>
              <p className="text-xl font-bold">¥{quoteMutation.data.total.toLocaleString()}</p>
              <p className="text-xs text-gray-500">含 {quoteMutation.data.items.length} 项</p>
            </div>
          )}

          <button
            type="button"
            onClick={() => contractMutation.mutate()}
            disabled={contractMutation.isPending || !quoteMutation.data}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-green-600 px-4 py-3 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            <FileText className="h-4 w-4" />
            生成合同
          </button>

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
