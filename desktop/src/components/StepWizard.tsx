import { clsx } from "clsx";
import { Check } from "lucide-react";

export interface WizardStep {
  id: string;
  label: string;
  description?: string;
}

interface StepWizardProps {
  steps: WizardStep[];
  currentStep: string;
  onStepClick?: (stepId: string) => void;
}

export default function StepWizard({ steps, currentStep, onStepClick }: StepWizardProps) {
  const currentIdx = steps.findIndex((s) => s.id === currentStep);

  return (
    <div className="flex items-center justify-between gap-2">
      {steps.map((step, idx) => {
        const done = idx < currentIdx;
        const active = step.id === currentStep;
        return (
          <div key={step.id} className="flex flex-1 items-center">
            <button
              type="button"
              disabled={!onStepClick}
              onClick={() => onStepClick?.(step.id)}
              className={clsx(
                "flex flex-col items-center gap-1 text-center",
                onStepClick && "cursor-pointer"
              )}
            >
              <div
                className={clsx(
                  "flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium transition-colors",
                  done && "bg-green-500 text-white",
                  active && !done && "bg-blue-600 text-white",
                  !done && !active && "bg-gray-200 text-gray-500 dark:bg-slate-700 dark:text-slate-400"
                )}
              >
                {done ? <Check className="h-4 w-4" /> : idx + 1}
              </div>
              <span
                className={clsx(
                  "text-xs font-medium",
                  active ? "text-blue-600 dark:text-blue-400" : "text-gray-500 dark:text-slate-400"
                )}
              >
                {step.label}
              </span>
            </button>
            {idx < steps.length - 1 && (
              <div
                className={clsx(
                  "mx-2 h-0.5 flex-1",
                  idx < currentIdx ? "bg-green-500" : "bg-gray-200 dark:bg-slate-700"
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
