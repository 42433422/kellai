import api from './client';

/** 获取渠道列表 */
export const getChannels = () =>
  api.get('/api/kellai/channels');

/** 测试渠道连接 */
export const testChannel = (channelType: string) =>
  api.post(`/api/kellai/channels/${channelType}/test`);

/** 保存渠道配置 */
export const saveChannelConfig = (
  channelType: string,
  config: Record<string, string>,
  options?: { name?: string; enabled?: boolean }
) => api.put(`/api/kellai/channels/${channelType}/config`, { config, ...options });

/** 断开 / 删除渠道 */
export const deleteChannel = (channelType: string) =>
  api.delete(`/api/kellai/channels/${channelType}`);

/** 同步指定渠道收件箱 */
export const syncChannelInbox = (channelType: string, limit = 20) =>
  api.post('/api/kellai/channels/sync-inbox', { channel_type: channelType, limit });

/** 获取 LLM 状态 */
export const getLlmStatus = () =>
  api.get('/api/kellai/ai/llm-status');

/** 保存真实 LLM 配置 */
export const saveLlmConfig = (payload: {
  provider: string;
  model?: string;
  base_url?: string;
  api_key?: string;
  auto_reply_enabled?: boolean;
  auto_reply_stages?: string[];
  confirm_scenarios?: string[];
}) =>
  api.put('/api/kellai/ai/llm-config', payload);

/** 手动测试真实 LLM 连通性 */
export const probeLlmConfig = () =>
  api.post('/api/kellai/ai/llm-probe');

/** 获取脱敏 LLM 配置诊断 */
export const getLlmDiagnostics = () =>
  api.get('/api/kellai/ai/llm-diagnostics');

/** 获取团队信息 */
export const getTeamInfo = () =>
  api.get('/api/kellai/team');

/** 获取团队成员列表 */
export const getTeamMembers = () =>
  api.get('/api/kellai/team/members');

/** 邀请成员 */
export const inviteMember = (email: string, phone: string, role: string) =>
  api.post('/api/kellai/team/invite', { email, phone, role });

/** 更新成员角色 */
export const updateMemberRole = (userId: number, role: string) =>
  api.put(`/api/kellai/team/members/${userId}/role`, { role });

/** 获取当前用户信息 */
export const getUserInfo = () =>
  api.get('/api/kellai/auth/me');

/** 更新当前用户信息 */
export const updateUserInfo = (data: { display_name?: string; avatar_url?: string }) =>
  api.put('/api/kellai/auth/me', data);

/** 发起企微 OAuth 授权（获取扫码 URL） */
export const initiateWeworkOAuth = () =>
  api.post('/api/kellai/channels/wework/oauth/initiate');

/** 查询企微 OAuth 授权状态 */
export const checkWeworkOAuthStatus = (state: string) =>
  api.get('/api/kellai/channels/wework/oauth/status', { params: { state } });
