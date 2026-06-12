import { Sparkles, X } from "lucide-react";
import type { SalesScriptHint } from "../types";

interface ScriptHintToastProps {
  hint: SalesScriptHint | null;
  onDismiss: () => void;
  onUse: (text: string) => void;
}

export default function ScriptHintToast({ hint, onDismiss, onUse }: ScriptHintToastProps) {
  if (!hint) return null;

  return (
    <div className="fixed bottom-6 right-6 z-50 w-96 rounded-xl border border-purple-200 bg-white p-4 shadow-xl dark:border-purple-500/30 dark:bg-slate-800">
      <div className="mb-2 flex items-start justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-purple-500" />
          <span className="text-sm font-semibold text-gray-900 dark:text-slate-100">
            销售话术提示
          </span>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-700"
          aria-label="关闭"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <p className="mb-1 text-xs text-purple-600 dark:text-purple-400">{hint.stage_label}</p>
      <p className="mb-3 text-sm text-gray-700 dark:text-slate-300">{hint.suggestion}</p>
      <div className="space-y-2">
        {hint.scripts.map((script, i) => (
          <button
            key={i}
            type="button"
            onClick={() => onUse(script)}
            className="w-full rounded-lg bg-purple-50 px-3 py-2 text-left text-sm text-purple-800 transition-colors hover:bg-purple-100 dark:bg-purple-500/10 dark:text-purple-200 dark:hover:bg-purple-500/20"
          >
            {script}
          </button>
        ))}
      </div>
    </div>
  );
}
