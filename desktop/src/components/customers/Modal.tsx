import { X } from 'lucide-react';
import { clsx } from 'clsx';

interface ModalProps {
  title: string;
  subtitle?: string;
  icon?: React.ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  onClose: () => void;
  footer?: React.ReactNode;
  children: React.ReactNode;
}

const SIZE: Record<NonNullable<ModalProps['size']>, string> = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
};

/** 通用弹窗外壳：遮罩点击关闭、标题栏、可选副标题/图标/底部操作区 */
export default function Modal({ title, subtitle, icon, size = 'md', onClose, footer, children }: ModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onMouseDown={onClose}>
      <div
        className={clsx(
          'flex max-h-[90vh] w-full flex-col overflow-hidden rounded-2xl bg-white shadow-xl dark:bg-slate-800',
          SIZE[size],
        )}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-gray-100 px-6 py-4 dark:border-slate-700">
          <div className="flex items-center gap-3">
            {icon && (
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-500/15 dark:text-blue-300">
                {icon}
              </div>
            )}
            <div>
              <h2 className="text-base font-semibold text-gray-800 dark:text-slate-100">{title}</h2>
              {subtitle && <p className="mt-0.5 text-xs text-gray-400 dark:text-slate-500">{subtitle}</p>}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="rounded p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-700"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">{children}</div>

        {footer && (
          <div className="flex items-center justify-end gap-3 border-t border-gray-100 px-6 py-4 dark:border-slate-700">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
