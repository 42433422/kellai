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

// === v3 Sales ===
export type SalesFlowStep = 'requirement' | 'proposal' | 'promotion' | 'signing';
export type SalesFlowStatus = 'idle' | 'running' | 'completed' | 'failed';
export type ContractStatus = 'draft' | 'pending_sign' | 'signed' | 'cancelled';

export interface SalesFlow {
  id: string;
  customer_id: number;
  customer_name: string;
  current_step: SalesFlowStep;
  status: SalesFlowStatus;
  started_at: string;
  updated_at: string;
  steps_completed: SalesFlowStep[];
}

export interface QuoteItem {
  name: string;
  quantity: number;
  unit_price: number;
  total: number;
}

export interface QuoteRequest {
  customer_id: number;
  industry?: string;
  scale?: string;
}

export interface Quote {
  id: string;
  customer_id: number;
  items: QuoteItem[];
  subtotal: number;
  discount: number;
  total: number;
  valid_until: string;
  created_at: string;
}

export interface Contract {
  id: string;
  customer_id: number;
  quote_id: string;
  status: ContractStatus;
  title: string;
  content_preview: string;
  sign_url?: string;
  created_at: string;
}

export interface LTVForecast {
  customer_id: number;
  predicted_ltv: number;
  confidence: number;
  factors: { name: string; impact: number }[];
  recommendation: string;
}

export interface GoalBreakdown {
  period: string;
  target: number;
  actual: number;
  progress: number;
}

export interface PerformanceGoal {
  id: string;
  title: string;
  target: number;
  actual: number;
  unit: string;
  breakdown: GoalBreakdown[];
}

export interface SalesPerformance {
  period: string;
  revenue_target: number;
  revenue_actual: number;
  completion_rate: number;
  deals_closed: number;
  avg_deal_size: number;
  goals: PerformanceGoal[];
}

export interface AttributionChannel {
  channel: string;
  channel_label: string;
  leads: number;
  conversions: number;
  revenue: number;
  contribution_pct: number;
}

export interface AttributionReport {
  date_range: string;
  channels: AttributionChannel[];
  total_revenue: number;
}

export interface FunnelTraceNode {
  stage: string;
  stage_label: string;
  timestamp: string;
  duration_hours?: number;
}

export interface FunnelTraceEdge {
  from_stage: string;
  to_stage: string;
  conversion_rate: number;
}

export interface FunnelTrace {
  customer_id?: number;
  nodes: FunnelTraceNode[];
  edges: FunnelTraceEdge[];
  overall_conversion: number;
}

export interface SalesScriptHint {
  customer_id: number;
  stage: string;
  stage_label: string;
  suggestion: string;
  scripts: string[];
}

// === v4 Content ===
export type ContentType = 'text' | 'image' | 'video_script';
export type ContentStatus = 'draft' | 'published' | 'scheduled';

export interface Content {
  id: string;
  type: ContentType;
  title: string;
  body: string;
  image_url?: string;
  status: ContentStatus;
  platforms: string[];
  created_at: string;
  published_at?: string;
}

export interface AdStrategy {
  recommended_channels: { channel: string; label: string; score: number; best_hours: string[] }[];
  budget_split: { channel: string; pct: number }[];
  reasoning: string;
}

export interface ContentAnalyticsItem {
  content_id: string;
  title: string;
  platform: string;
  views: number;
  likes: number;
  shares: number;
  conversions: number;
  ctr: number;
}

export interface ContentAnalytics {
  items: ContentAnalyticsItem[];
  totals: { views: number; likes: number; conversions: number };
}

export interface ABTestVariant {
  id: string;
  name: string;
  content: string;
  views: number;
  conversions: number;
  win_rate: number;
}

export interface ABTest {
  id: string;
  name: string;
  status: 'running' | 'completed';
  variants: ABTestVariant[];
  winner_id?: string;
}

// === v5 Scout ===
export interface ScoutTarget {
  id: string;
  platform: string;
  post_title: string;
  comment: string;
  author: string;
  intent_score: number;
  intent_level: 'high' | 'medium' | 'low';
  reason: string;
  scanned_at: string;
}

export interface IntentScore {
  comment: string;
  score: number;
  level: 'high' | 'medium' | 'low';
  keywords: string[];
  reason: string;
}

export interface SentimentItem {
  id: string;
  type: 'hotspot' | 'competitor' | 'opportunity';
  title: string;
  summary: string;
  severity: 'high' | 'medium' | 'low';
  timestamp: string;
}

export interface ScoutTrace {
  target_id: string;
  steps: { action: string; timestamp: string; result: string }[];
  converted: boolean;
}

// === v6 Flow ===
export type FlowNodeType = 'acquire' | 'communicate' | 'sales' | 'after_sales' | 'webhook';

export interface FlowNode {
  id: string;
  type: FlowNodeType;
  label: string;
  config: Record<string, unknown>;
  position: { x: number; y: number };
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
}

export interface FlowTemplate {
  id: string;
  name: string;
  industry: string;
  description: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
  automation_rate: number;
}

export interface FlowExecution {
  id: string;
  flow_id: string;
  flow_name: string;
  status: 'running' | 'completed' | 'failed';
  started_at: string;
  completed_at?: string;
  logs: { node_id: string; message: string; timestamp: string }[];
}

export interface Anomaly {
  id: string;
  flow_id: string;
  node_id: string;
  severity: 'critical' | 'warning';
  message: string;
  suggestion: string;
  detected_at: string;
}

export interface Webhook {
  id: string;
  url: string;
  events: string[];
  enabled: boolean;
  created_at: string;
}

export interface FlowDefinition {
  id: string;
  name: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
  created_at: string;
  updated_at: string;
}

// === v7 Finance ===
export interface FinanceDashboardData {
  revenue: number;
  cost: number;
  profit: number;
  profit_margin: number;
  channel_breakdown: { channel: string; revenue: number; cost: number; profit: number }[];
  monthly_trend: { month: string; revenue: number; cost: number; profit: number }[];
}

export interface BudgetSuggestion {
  total_budget: number;
  allocations: { channel: string; amount: number; roi: number; reason: string }[];
}

export interface FinancePerformanceMember {
  user_id: number;
  name: string;
  revenue: number;
  deals: number;
  conversion_rate: number;
  rank: number;
}

export interface FinanceAlert {
  id: string;
  type: 'cost_overrun' | 'profit_drop' | 'channel_anomaly';
  severity: 'high' | 'medium' | 'low';
  title: string;
  message: string;
  timestamp: string;
  read: boolean;
}

export interface FinanceReport {
  id: string;
  title: string;
  period: string;
  generated_at: string;
  download_url: string;
}

export interface DecisionAdvice {
  summary: string;
  actions: { title: string; description: string; priority: 'high' | 'medium' | 'low' }[];
}

// === v8 Open Platform ===
export interface APIKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at?: string;
}

export interface Plugin {
  id: string;
  name: string;
  description: string;
  author: string;
  category: string;
  rating: number;
  installs: number;
  price: number;
  installed: boolean;
}

export interface ISVPartner {
  id: string;
  name: string;
  tier: 'gold' | 'silver' | 'bronze';
  solutions: number;
  certified: boolean;
}

export interface WebhookConfig {
  id: string;
  url: string;
  events: string[];
  secret: string;
  active: boolean;
}

export interface EventSubscription {
  id: string;
  event_type: string;
  description: string;
  subscribed: boolean;
}

export interface AppTemplate {
  id: string;
  name: string;
  description: string;
  fields: { key: string; label: string; type: string }[];
}

export interface ReviewStatus {
  app_id: string;
  app_name: string;
  status: 'pending' | 'approved' | 'rejected';
  submitted_at: string;
  reviewed_at?: string;
  feedback?: string;
}
