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

/** 获取 LLM 状态 */
export const getLlmStatus = () =>
  api.get('/api/kellai/ai/llm-status');

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
