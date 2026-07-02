import { buildOnboardingSpeechText } from "../utils/onboardingSpeech";

export const ONBOARDING_WELCOME_TITLE = "欢迎使用客来来";

export const ONBOARDING_WELCOME_DESCRIPTION =
  "接下来会先创建一批真实入库的模拟客户，再按实际使用顺序演示核心功能：\n\n<b>1.</b> 客户进线 → 消息入库 → 漏斗推进\n<b>2.</b> 接入渠道 → 配置 AI\n<b>3.</b> 工作台、漏斗、消息\n<b>4.</b> 自动销售流程与开放平台\n\n严格 LLM 成交链路仍在工作台高级功能里单独验收。";

export const ONBOARDING_WELCOME_SPEECH_TEXT = buildOnboardingSpeechText(
  ONBOARDING_WELCOME_TITLE,
  ONBOARDING_WELCOME_DESCRIPTION
);

export const ONBOARDING_WELCOME_CACHE_KEY = "onboarding:welcome";
