import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryOptions,
  type UseMutationOptions,
  type QueryKey,
} from "@tanstack/react-query";
import { AxiosError } from "axios";
import client from "../api/client";
import type { ApiResponse } from "../types";

/* ===== useApiQuery ===== */
/**
 * 统一的 useQuery 封装
 * 自动：
 * 1. 调用 axios 实例（拦截器统一处理 401 / loading / 错误 toast）
 * 2. 解包 ApiResponse.data
 * 3. 统一 queryKey
 */
export function useApiQuery<TData = unknown, TParams = void>(
  queryKey: QueryKey,
  fn: TParams extends void ? () => Promise<TData> | TData : (params: TParams) => Promise<TData> | TData,
  options?: Omit<UseQueryOptions<TData, AxiosError, TData>, "queryKey" | "queryFn"> & {
    params?: TParams;
  }
) {
  return useQuery<TData, AxiosError>({
    queryKey,
    queryFn: async () => {
      // 通过 client 发起请求保持拦截器行为（401/loading/错误 toast）
      const result = await (fn as (p: unknown) => Promise<TData> | TData)(
        options?.params as unknown
      );
      return result;
    },
    ...options,
  });
}

/**
 * 直接基于 HTTP 调用方式的 query hook
 * 适用于简单 GET 请求，无需手写 queryFn
 */
export function useApiGet<T = unknown>(
  queryKey: QueryKey,
  url: string,
  config?: { params?: Record<string, unknown>; skipErrorToast?: boolean } & Omit<
    UseQueryOptions<T, AxiosError, T>,
    "queryKey" | "queryFn"
  >
) {
  const { params, skipErrorToast, ...rest } = config || {};
  return useQuery<T, AxiosError>({
    queryKey,
    queryFn: async () => {
      const res = await client.get<ApiResponse<T>>(url, {
        params,
        skipErrorToast,
      } as never);
      return res.data.data;
    },
    ...rest,
  });
}

/* ===== useApiMutation ===== */

/**
 * 统一的 useMutation 封装
 * 自动：
 * 1. 调用 axios 实例（拦截器统一处理 401 / loading / 错误 toast）
 * 2. 解包 ApiResponse.data
 */
export function useApiMutation<TData = unknown, TVariables = void, TContext = unknown>(
  mutationFn: (variables: TVariables) => Promise<TData> | TData,
  options?: UseMutationOptions<TData, AxiosError, TVariables, TContext>
) {
  return useMutation<TData, AxiosError, TVariables, TContext>({
    mutationFn: async (variables) => mutationFn(variables),
    ...options,
  });
}

/** 重新导出 useQueryClient 方便统一引用 */
export { useQueryClient };
