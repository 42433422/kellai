import type { RJSFSchema } from '@rjsf/utils';

export interface Account {
  connection_id: string;
  channel_type: string;
  name: string;
  auth_type: 'credentials' | 'oauth2' | 'browser';
  enabled: boolean;
  connected: boolean;
  status: string;
  version: number;
  config: Record<string, unknown>;
}
export interface Channel {
  channel_type: string;
  display_name?: string;
  name?: string;
  config_schema?: RJSFSchema;
  auth_types?: Account['auth_type'][];
  capabilities?: { receive?: boolean; send?: boolean; contacts?: boolean; sync?: boolean; limitations?: string[]; readiness?: string };
}
export interface PendingPairing {
  request_id: string;
  requested_scopes: { id: string; label: string; description: string }[];
  expires_at?: string | number;
  xcmax_user?: { username?: string; display_name?: string };
}
export interface PairStatus {
  state: string;
  connected: boolean;
  message?: string;
  pending?: PendingPairing | null;
  connection?: { authorized_scopes: string[] } | null;
}
export interface Contact {
  customer_id: number;
  connection_id: string;
  channel_type: string;
  contact_id: string;
  contact_name: string;
}
export interface Message {
  id: number | string;
  direction: string;
  content: string;
  metadata?: { delivery_state?: string };
  created_at: string;
}
export interface Receipt {
  request_id: string;
  connection_id: string;
  status: string;
  provider_state?: string;
  error?: string;
  message_id?: number | string;
  provider_message_id?: string;
}

export const scopeLabels: Record<string, string> = {
  'channels.read': '查看账号连接和渠道能力',
  'messages.read': '读取通道联系人与消息',
  'messages.send': '执行 XCMAX 已授权的发送并查询回执',
};

export function receiptLabel(status: string) {
  return ({ accepted: '平台已受理', sent: '发送请求已提交', delivered: '已送达', read: '已读',
    pending: '等待处理', sending: '正在提交', failed: '发送失败', rejected: '未获准发送',
    unknown: '结果待核验，请查询原请求' } as Record<string, string>)[status] || status || '未核验';
}

export function receiptState(receipt: Receipt): string {
  // The ledger records acceptance separately from subsequent platform evidence.
  // An unknown/failed attempt must not be promoted by a stale provider field.
  return receipt.status === 'accepted'
    && ['sent', 'delivered', 'read'].includes(receipt.provider_state || '')
    ? receipt.provider_state! : receipt.status;
}
