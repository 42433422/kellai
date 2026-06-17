import { request } from './client';

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
