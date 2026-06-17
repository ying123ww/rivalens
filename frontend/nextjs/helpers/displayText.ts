const DIMENSION_LABELS: Record<string, string> = {
  strategic_positioning: "战略定位与差异化",
  target_users_segments: "目标用户与细分场景",
  core_product_supply: "核心产品与供给能力",
  product_experience: "交互与产品体验",
  ai_capability_application: "AI 能力与应用",
  business_model_pricing: "商业模式与定价",
  growth_channels: "增长渠道",
  operations_fulfillment: "运营与交付",
  baseline_trust_security_compliance: "基础信任、安全与合规",
  user_reputation: "用户口碑",
  moat_resources_team: "护城河、资源与团队",
  market_trends_opportunities: "市场趋势与机会",
  integrations_ecosystem: "集成与生态",
  migration_switching_cost: "迁移与切换成本",
  sla_reliability: "服务稳定性与可靠性",
};

export function formatTraceTextForDisplay(value: string) {
  let text = value || "";

  Object.entries(DIMENSION_LABELS).forEach(([id, label]) => {
    text = text.replaceAll(id, label);
  });

  return text
    .replace(/\b相关\s*Claim\s*ID\b/gi, "相关结论")
    .replace(/\bClaim\s*ID\b/gi, "结论编号")
    .replace(/\bClaim\s*[_-]\s*(\d+)\b/gi, "第 $1 条结论")
    .replace(/\bclaim_(\d+)\b/gi, "第 $1 条结论")
    .replace(/\bClaim\b/g, "结论")
    .replace(/\bclaim\b/gi, "结论")
    .replace(/\bEvidence\s*ids?\s*:/gi, "关联来源：")
    .replace(/\bEvidence\s*IDs?\b/gi, "引用来源")
    .replace(/无效证据\s*ID/gi, "无效来源")
    .replace(/错位证据\s*ID/gi, "错位来源")
    .replace(/证据\s*ID/gi, "来源记录")
    .replace(/\bev_(\d+)\b/gi, "第 $1 条来源")
    .replace(/另外还有(\d+)条单独低置信度结论：/g, "另外还有 $1 条需要单独复核的低置信度结论：");
}
