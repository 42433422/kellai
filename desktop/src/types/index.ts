/** 客户信息 */
export interface Customer {
  id: string;
  name: string;
  email?: string;
  phone?: string;
  company?: string;
  tags?: string[];
  source?: string;
  createdAt: string;
  updatedAt: string;
}

/** 漏斗阶段 */
export interface PipelineStage {
  id: string;
  name: string;
  order: number;
  color?: string;
}

/** 漏斗看板阶段（含客户列表） */
export interface FunnelStage {
  id: string;
  label: string;
  count: number;
  clients: ClientSummary[];
}

/** 漏斗看板客户摘要 */
export interface ClientSummary {
  customer_id: number;
  username: string;
  stage: string;
  stage_label: string;
  display_name: string;
  intake_sent: boolean;
  last_message_preview: string;
  channel_sources: string[];
  ai_score: number;
  ai_tags: string[];
  updated_at: string;
}

/** 客户 Pipeline 详情 */
export interface CustomerPipeline {
  customer_id: number;
  username: string;
  display_name: string;
  stage: string;
  stage_label: string;
  ai_score: number;
  ai_tags: string[];
  channel_sources: string[];
  intake_sent: boolean;
  last_message_preview: string;
  created_at: string;
  updated_at: string;
  timeline?: PipelineTimelineEntry[];
}

/** Pipeline 时间线条目 */
export interface PipelineTimelineEntry {
  stage: string;
  stage_label: string;
  timestamp: string;
  source: string;
  note?: string;
}

/** 客户消息 */
export interface CustomerMessage {
  id: string;
  customer_id: number;
  channel_type: string;
  contact_id: string;
  direction: 'inbound' | 'outbound';
  content: string;
  intent?: string;
  created_at: string;
}

/** AI 客户画像 */
export interface CustomerAiProfile {
  customer_id: number;
  needs_preference?: string;
  decision_role?: string;
  budget_awareness?: string;
  urgency?: 'high' | 'medium' | 'low';
  one_line_profile?: string;
  ai_tags: string[];
  ai_score: number;
}

/** 需求表单 */
export interface IntakeForm {
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  company_name?: string;
  requirement_desc?: string;
  desktop_system_needed?: string;
  need_mobile?: boolean;
  submitted_at?: string;
}

/** CRM 商机 */
export interface CrmOpportunity {
  id: string;
  company?: string;
  status?: string;
}

/** CRM 报价 */
export interface CrmQuote {
  id: string;
  status?: string;
  summary?: string;
}

/** CRM 发票 */
export interface CrmInvoice {
  id: string;
  invoice_no?: string;
}

/** CRM 交付 */
export interface CrmDelivery {
  details?: string;
}

/** CRM 数据包 */
export interface CrmBundle {
  opportunity?: CrmOpportunity;
  quote?: CrmQuote;
  invoice?: CrmInvoice;
  delivery?: CrmDelivery;
  synced_at?: string;
}

/** AI 推荐回复 */
export interface SuggestedReply {
  replies: string[];
}

/** 漏斗 */
export interface Pipeline {
  id: string;
  name: string;
  stages: PipelineStage[];
  createdAt: string;
  updatedAt: string;
}

/** 消息 */
export interface Message {
  id: string;
  content: string;
  channelId: string;
  customerId: string;
  direction: "inbound" | "outbound";
  read: boolean;
  createdAt: string;
}

/** 渠道 */
export interface Channel {
  id: string;
  name: string;
  type:
    | "email"
    | "sms"
    | "wework"
    | "phone"
    | "douyin"
    | "miniprogram"
    | "whatsapp"
    | "web"
    | "pdd"
    | "taobao"
    | "jd"
    | "alibaba"
    | "telegram"
    | "line";
  config: Record<string, unknown>;
  enabled: boolean;
  connected: boolean;
  createdAt: string;
}

/** 渠道配置项 */
export interface ChannelConfigField {
  key: string;
  label: string;
  type: "text" | "password" | "select";
  placeholder?: string;
  options?: { label: string; value: string }[];
}

/** LLM 配置 */
export interface LLMConfig {
  model: string;
  apiKey: string;
  connected: boolean;
  autoReplyEnabled: boolean;
  autoReplyStages: string[];
  confirmScenarios: string[];
}

/** 团队成员 */
export interface TeamMember {
  userId: number;
  displayName: string;
  email: string;
  phone?: string;
  avatarUrl?: string;
  role: "admin" | "sales" | "readonly";
  joinedAt: string;
}

/** 团队信息（含邀请码） */
export interface TeamInfo {
  id: string;
  name: string;
  inviteCode: string;
  memberCount: number;
  ownerId: string;
  createdAt: string;
}

/** 跟进规则 - 阶段超时配置 */
export interface FollowUpStageRule {
  stage: string;
  stageLabel: string;
  timeoutDays: number;
  remindMethods: string[];
}

/** SOP 模板 */
export interface SOPTemplate {
  id: string;
  name: string;
  stage: string;
  stepsCount: number;
  steps: string[];
}

/** 用户通知偏好 */
export interface NotificationPreferences {
  desktopNotification: boolean;
  highIntentNotification: boolean;
  followUpReminder: boolean;
}

/** AI 助手配置 */
export interface AIProfile {
  id: string;
  name: string;
  description?: string;
  model: string;
  systemPrompt?: string;
  temperature?: number;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

/** 客户 AI 画像 */
export interface CustomerProfile {
  customerId: number;
  customerName: string;
  preferences?: string;       // 需求偏好
  decisionRole?: string;      // 决策角色
  budgetAwareness?: string;   // 预算感知
  urgency?: string;           // 紧迫度：high / medium / low
  summary?: string;           // 一句话画像
  aiTags?: string[];          // AI 标签
  aiScore?: number;           // AI 评分 0-100
  stage?: string;             // 当前阶段
  updatedAt?: string;
}

/** 跟进提醒 */
export interface Reminder {
  id: string;
  customerId: number;
  customerName: string;
  stage: string;
  lastFollowUpAt: string;     // 上次跟进时间
  suggestedAction: string;    // AI 建议的下一步动作
  overdue?: boolean;          // 是否超时
}

/** 意图分析结果 */
export interface IntentResult {
  intent: string;             // 识别出的意图
  confidence: number;         // 置信度 0-1
  keywords?: string[];        // 关键词
  sentiment?: string;         // 情感倾向：positive / neutral / negative
  suggestion?: string;        // AI 建议
}

/** AI 对话消息 */
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  type?: 'text' | 'intent' | 'suggest' | 'auto_reply'; // 消息类型
}

/** 用户信息 */
export interface User {
  id: string | number;
  email: string;
  name?: string;
  display_name?: string;
  avatar?: string;
  avatar_url?: string;
  phone?: string;
  role: string;
  teamId?: string | number;
  team_id?: string | number;
  createdAt?: string;
}

/** 团队 */
export interface Team {
  id: string;
  name: string;
  ownerId: string;
  memberCount: number;
  createdAt: string;
  updatedAt: string;
}

/** 登录请求（邮箱） */
export interface LoginRequest {
  email: string;
  password: string;
}

/** 登录请求（手机验证码） */
export interface SmsLoginRequest {
  phone: string;
  code: string;
}

/** 注册请求 */
export interface RegisterRequest {
  email: string;
  password: string;
  name: string;
}

/** 登录响应 */
export interface LoginResponse {
  success?: boolean;
  access_token: string;
  refresh_token?: string;
  access_expires_at?: string;
  refresh_expires_at?: string;
  user: User;
}

/** 通用 API 响应 */
export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

/** 分页请求 */
export interface PaginationParams {
  page: number;
  pageSize: number;
}

/** 分页响应 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}
