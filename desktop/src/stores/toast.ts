import toast from "react-hot-toast";

/**
 * 全局 toast 通知封装
 * 在 react-hot-toast 基础上提供统一的 success / error / loading 接口
 * 也提供 promise / dismiss 等工具方法
 */
export const toastStore = {
  /** 成功提示（默认 3s 自动消失） */
  success(message: string, options?: { duration?: number }) {
    return toast.success(message, { duration: options?.duration ?? 3000 });
  },

  /** 错误提示（默认 4s 自动消失） */
  error(message: string, options?: { duration?: number }) {
    return toast.error(message, { duration: options?.duration ?? 4000 });
  },

  /** loading 提示，返回 toastId 用于 dismiss */
  loading(message: string) {
    return toast.loading(message);
  },

  /** 通用提示（默认样式） */
  show(message: string) {
    return toast(message);
  },

  /** 关闭指定 toast */
  dismiss(toastId?: string) {
    toast.dismiss(toastId);
  },

  /** Promise 三态自动处理：loading → success/error */
  promise<T>(
    promise: Promise<T>,
    messages: { loading: string; success: string; error: string }
  ) {
    return toast.promise(promise, messages);
  },
};

/** 默认导出，便于 import toast from */
export default toastStore;
