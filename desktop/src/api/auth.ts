import { request } from './client';
import type { LoginResponse, User } from '../types';

/** 短信验证码发送响应（开发模式会回带 code 便于联调） */
export interface SmsSendResult {
  success: boolean;
  message?: string;
  error?: string;
  code?: string;
}

/** 发送短信验证码（登录 / 找回密码共用） */
export const sendSmsCode = (phone: string) =>
  request<SmsSendResult>('post', '/api/kellai/auth/sms/send', { phone });

/** 通过手机验证码重置密码 */
export const resetPasswordByPhone = (phone: string, code: string, newPassword: string) =>
  request<{ success: boolean; message?: string; error?: string }>(
    'post',
    '/api/kellai/auth/forgot-password',
    { phone, code, new_password: newPassword },
  );

export interface QrLoginStartResult {
  session_id: string;
  secret: string;
  login_url: string;
  expires_in: number;
  expires_at?: number;
}

export interface QrLoginStatusResult {
  status: 'waiting' | 'scanned' | 'authorized' | 'expired' | 'canceled' | 'failed';
  scanned?: boolean;
  authorized?: boolean;
  expired?: boolean;
  expires_in?: number;
  user?: User;
  login?: LoginResponse;
  error?: string;
}

/** 发起桌面扫码登录 */
export const startQrLogin = () =>
  request<QrLoginStartResult>('post', '/api/kellai/auth/qr/start', {});

/** 桌面端轮询扫码登录状态 */
export const checkQrLoginStatus = (sessionId: string) =>
  request<QrLoginStatusResult>('get', '/api/kellai/auth/qr/status', { session_id: sessionId });

/** 扫码设备打开链接后标记已扫描 */
export const markQrLoginScanned = (sessionId: string, secret: string) =>
  request<{ success?: boolean; status?: string; error?: string }>('post', '/api/kellai/auth/qr/scan', {
    session_id: sessionId,
    secret,
  });

/** 扫码设备确认把当前账号授权给桌面端 */
export const confirmQrLogin = (sessionId: string, secret: string) =>
  request<{ success?: boolean; status?: string; user?: User; error?: string }>('post', '/api/kellai/auth/qr/confirm', {
    session_id: sessionId,
    secret,
  });

/** 扫码设备取消登录 */
export const cancelQrLogin = (sessionId: string, secret: string) =>
  request<{ success?: boolean; status?: string; error?: string }>('post', '/api/kellai/auth/qr/cancel', {
    session_id: sessionId,
    secret,
  });
