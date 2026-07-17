import api, { loopbackClient } from './client';

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

/** 获取企业微信客服客户入口（客来来中转链接） */
export const getWeworkCustomerEntry = (source = 'settings') =>
  api.get('/api/kellai/channels/wework/customer-entry', { params: { source, mode: 'json' } });

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

/** 发起企业微信服务商第三方应用安装（获取主入口二维码 URL） */
export const initiateWeworkOAuth = () =>
  api.post('/api/kellai/channels/wework/install');

/** 查询企业微信第三方应用安装状态 */
export const checkWeworkOAuthStatus = (state: string) =>
  api.get('/api/kellai/channels/wework/install/status', { params: { state } });

/** 授权成功后同步企业微信真实外部联系人 */
export const syncWeworkCustomers = (limit = 500) =>
  api.post('/api/kellai/channels/wework/customers/sync', null, { params: { limit } });

/** 获取当前账号团队可用于获客链接的企业微信成员 */
export const getWeworkAcquisitionMembers = () =>
  api.get('/api/kellai/channels/wework/acquisition/members');

/** 使用当前账号团队的企业微信授权创建获客链接 */
export const createWeworkAcquisitionLink = (payload: {
  link_name: string;
  userids: string[];
  skip_verify?: boolean;
}) => api.post('/api/kellai/channels/wework/acquisition/links', payload);

/** 发起微信开放平台 OAuth 授权（获取扫码 URL） */
export const initiateWechatOAuth = () =>
  api.post('/api/kellai/channels/wechat/oauth/initiate');

/** 查询微信开放平台 OAuth 授权状态 */
export const checkWechatOAuthStatus = (state: string) =>
  api.get('/api/kellai/channels/wechat/oauth/status', { params: { state } });

/** 发起抖音企业号 OAuth 授权（返回可扫码的官方授权 URL） */
export const initiateDouyinOAuth = () =>
  api.post('/api/kellai/channels/douyin/oauth/initiate');

/** 查询抖音企业号 OAuth 授权状态 */
export const checkDouyinOAuthStatus = (state: string) =>
  api.get('/api/kellai/channels/douyin/oauth/status', { params: { state } });

/** 抖音网站 Token 连接状态 */
export const getDouyinWebPortalStatus = () =>
  api.get('/api/kellai/channels/douyin/web-portal/status');

/** 使用网站 token 建立连接 */
export const connectDouyinWebPortal = (tokenOrUrl: string) =>
  api.post('/api/kellai/channels/douyin/web-portal/connect', { token_or_url: tokenOrUrl });

/** 同步第三方客服网页的账号、联系人和历史消息 */
export const syncDouyinWebPortal = (maxConversations = 200, historyLimit = 20) =>
  api.post('/api/kellai/channels/douyin/web-portal/sync', {
    max_conversations: maxConversations,
    history_limit: historyLimit,
  });

/** 开始/停止第三方客服网页实时私信监听 */
export const startDouyinWebPortalMonitor = () =>
  api.post('/api/kellai/channels/douyin/web-portal/monitor/start');

export const stopDouyinWebPortalMonitor = () =>
  api.post('/api/kellai/channels/douyin/web-portal/monitor/stop');

/** 断开第三方客服网页 */
export const disconnectDouyinWebPortal = () =>
  api.delete('/api/kellai/channels/douyin/web-portal');

/** XCMAX AI 本机绑定状态与授权动作。 */
export const getXcmaxIntegrationStatus = () =>
  loopbackClient.get('/api/kellai/integrations/xcmax/status');

export const getXcmaxBindingPending = () =>
  loopbackClient.get('/api/kellai/integrations/xcmax/pending');

export const approveXcmaxBinding = (payload: {
  request_id: string;
  authorization_secret: string;
  accepted_scopes: string[];
}) =>
  loopbackClient.post('/api/kellai/integrations/xcmax/approve', payload);

export const cancelXcmaxBinding = (payload: {
  request_id: string;
  authorization_secret: string;
}) =>
  loopbackClient.post('/api/kellai/integrations/xcmax/cancel', payload);

export const disconnectXcmaxBinding = () =>
  loopbackClient.post('/api/kellai/integrations/xcmax/disconnect');
