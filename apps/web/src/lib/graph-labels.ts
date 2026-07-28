export type RelationCategory =
  | "family"
  | "romantic"
  | "friendship"
  | "professional"
  | "social"
  | "investigation"
  | "conflict"
  | "crime"
  | "testimony"
  | "action"
  | "suspicion"
  | "care"
  | "financial"
  | "medical"
  | "legal"
  | "unknown";

export const relationCategoryOrder: RelationCategory[] = [
  "family",
  "romantic",
  "friendship",
  "professional",
  "social",
  "investigation",
  "conflict",
  "crime",
  "testimony",
  "action",
  "suspicion",
  "care",
  "financial",
  "medical",
  "legal",
  "unknown",
];

const relationCategoryNames: Record<RelationCategory, string> = {
  family: "亲属",
  romantic: "情感",
  friendship: "朋友",
  professional: "职业",
  social: "社交",
  investigation: "调查",
  conflict: "冲突",
  crime: "犯罪",
  testimony: "证词",
  action: "共同行动",
  suspicion: "嫌疑",
  care: "照护",
  financial: "财务",
  medical: "医患",
  legal: "法律",
  unknown: "其他关系",
};

const relationCategoryAliases: Record<string, RelationCategory> = {
  family: "family",
  parent_child: "family",
  spouse: "family",
  marital: "family",
  marriage: "family",
  aunt_niece: "family",
  engagement: "family",
  former_fiance: "family",
  "former_fiancée": "family",
  家庭: "family",
  家庭关系: "family",
  亲属: "family",
  配偶: "family",
  婚姻: "family",
  婚约: "family",
  过去婚约: "family",

  romantic: "romantic",
  romantic_interest: "romantic",
  "romantic/criminal": "romantic",
  emotional: "romantic",
  past_relationship: "romantic",
  情感关系: "romantic",
  情感纠葛: "romantic",
  情感联系: "romantic",
  浪漫: "romantic",

  friendship: "friendship",
  friend: "friendship",
  ally: "friendship",
  confidant: "friendship",
  support: "friendship",
  friendship_turned_enmity: "friendship",
  朋友: "friendship",
  友谊: "friendship",

  professional: "professional",
  business: "professional",
  partnership: "professional",
  authority: "professional",
  同事: "professional",
  雇佣: "professional",
  雇佣关系: "professional",
  托管人: "professional",

  social: "social",
  acquaintance: "social",
  advisory: "social",
  event: "social",
  sympathy: "social",
  交流: "social",
  信息传递: "social",
  求助关系: "social",

  investigation: "investigation",
  interrogation: "investigation",
  arrest: "investigation",
  accusation: "investigation",
  调查: "investigation",
  调查关系: "investigation",
  调查伙伴: "investigation",
  指控: "investigation",
  推理: "investigation",
  评估: "investigation",

  conflict: "conflict",
  disapproval: "conflict",
  rival: "conflict",
  rivalry: "conflict",
  threat: "conflict",
  violent: "conflict",
  敌意: "conflict",
  敌对: "conflict",
  仇怨: "conflict",
  伤害: "conflict",
  否认关系: "conflict",
  否认相识: "conflict",
  对立关系: "conflict",

  crime: "crime",
  murder: "crime",
  killer_victim: "crime",
  attempted_murder: "crime",
  blackmail: "crime",
  suicide: "crime",
  suspected_murder: "crime",
  "marital/murder": "crime",
  犯罪: "crime",
  犯罪同伙: "crime",
  共谋: "crime",
  盗窃: "crime",

  testimony: "testimony",
  目击: "testimony",
  信息提供: "testimony",

  action: "action",
  合作: "action",
  保护: "action",

  suspicion: "suspicion",

  care: "care",
  caretaker: "care",
  关怀关系: "care",

  financial: "financial",
  财务关系: "financial",

  medical: "medical",
  医患: "medical",

  legal: "legal",

  unknown: "unknown",
};

function normalizedKind(kind: string): string {
  return kind.trim().toLocaleLowerCase("en-US").replace(/\s+/g, "_");
}

export function relationCategory(kind: string): RelationCategory {
  return relationCategoryAliases[normalizedKind(kind)] ?? "unknown";
}

export function relationKindName(kind: string): string {
  return relationCategoryNames[relationCategory(kind)];
}

const graphStatusNames: Record<string, string> = {
  confirmed: "已确认",
  inferred: "推测",
  disputed: "存疑",
  uncertain: "待确认",
};

export function graphStatusName(status: string): string {
  return graphStatusNames[status] ?? "待确认";
}
