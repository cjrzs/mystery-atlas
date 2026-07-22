export type ArchiveWork = {
  slug: string;
  title: string;
  author: string;
  subtitle: string;
  region: string;
  year: string;
  tags: string[];
  cases: number;
  people: number;
  clues: number;
  progress: number;
  status: "已核验" | "审核中" | "待补全";
  updatedAt: string;
  cover: "teal" | "red" | "blue" | "yellow";
};

export const archiveWorks: ArchiveWork[] = [
  {
    slug: "fog-harbor-clocktower",
    title: "雾港钟楼",
    author: "林砚川",
    subtitle: "钟声停止后的第七码头",
    region: "中国",
    year: "2024",
    tags: ["本格", "暴风雪山庄", "时间诡计"],
    cases: 3,
    people: 18,
    clues: 42,
    progress: 100,
    status: "已核验",
    updatedAt: "今天 21:40",
    cover: "teal",
  },
  {
    slug: "silent-gallery",
    title: "无声画廊",
    author: "藤原澄子",
    subtitle: "一幅不存在的遗作",
    region: "日本",
    year: "2019",
    tags: ["艺术犯罪", "叙述性诡计"],
    cases: 2,
    people: 14,
    clues: 31,
    progress: 86,
    status: "审核中",
    updatedAt: "昨天 18:12",
    cover: "red",
  },
  {
    slug: "the-last-alibi",
    title: "最后的不在场证明",
    author: "埃利奥特·格雷",
    subtitle: "所有证人都说了真话",
    region: "英国",
    year: "2016",
    tags: ["黄金时代", "不在场证明"],
    cases: 1,
    people: 12,
    clues: 27,
    progress: 64,
    status: "待补全",
    updatedAt: "7 月 19 日",
    cover: "blue",
  },
  {
    slug: "northbound-night-train",
    title: "北行夜车",
    author: "周荻",
    subtitle: "列车到站前无人可以离开",
    region: "中国",
    year: "2022",
    tags: ["密室", "群像", "社会派"],
    cases: 2,
    people: 21,
    clues: 38,
    progress: 92,
    status: "审核中",
    updatedAt: "7 月 18 日",
    cover: "yellow",
  },
];

export type CharacterNode = {
  id: string;
  name: string;
  role: string;
  group: "investigator" | "family" | "staff" | "outsider" | "victim";
  firstChapter: number;
  x: number;
  y: number;
  description: string;
  knownFacts: string[];
};

export type RelationEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
  kind: "family" | "testimony" | "conflict" | "action" | "suspicion";
  firstChapter: number;
  status: "confirmed" | "inferred" | "disputed";
  evidence: string;
};

export const characters: CharacterNode[] = [
  {
    id: "shen-yan",
    name: "沈砚",
    role: "调查记者",
    group: "investigator",
    firstChapter: 1,
    x: 470,
    y: 300,
    description: "受邀记录钟楼修复工程，却在封港当夜卷入命案。",
    knownFacts: ["熟悉机械钟结构", "案发时位于旧报务室", "主动保管了第二枚钟锤"],
  },
  {
    id: "liang-bingwen",
    name: "梁秉文",
    role: "钟楼所有人 / 死者",
    group: "victim",
    firstChapter: 1,
    x: 470,
    y: 92,
    description: "雾港旧船业家族的掌权者，死于封闭的钟楼机芯室。",
    knownFacts: ["计划在次日公布遗嘱", "死亡时间存在四十分钟误差", "生前停用了东侧升降机"],
  },
  {
    id: "gu-qinghe",
    name: "顾青禾",
    role: "钟表修复师",
    group: "outsider",
    firstChapter: 1,
    x: 210,
    y: 220,
    description: "负责修复停摆二十年的主钟，是最后见到死者的人之一。",
    knownFacts: ["掌握机芯室钥匙", "声称十点整听见钟声", "右手有新鲜灼伤"],
  },
  {
    id: "liang-zhiwei",
    name: "梁知微",
    role: "长女 / 基金会负责人",
    group: "family",
    firstChapter: 2,
    x: 725,
    y: 185,
    description: "负责家族基金会，与父亲在遗产用途上长期冲突。",
    knownFacts: ["反对出售码头", "九点四十分离开餐厅", "收到过匿名船票"],
  },
  {
    id: "liang-jing",
    name: "梁景",
    role: "次子 / 航运经理",
    group: "family",
    firstChapter: 2,
    x: 770,
    y: 400,
    description: "负责濒临破产的家族航运业务，急需遗产周转资金。",
    knownFacts: ["隐瞒公司债务", "熟悉码头监控盲区", "鞋底检出钟楼铜屑"],
  },
  {
    id: "su-man",
    name: "苏蔓",
    role: "管家",
    group: "staff",
    firstChapter: 3,
    x: 230,
    y: 470,
    description: "在梁家工作二十七年，掌握所有房间的备用钥匙。",
    knownFacts: ["负责当晚座次", "证词中遗漏了十一分钟", "知道旧海关暗道"],
  },
  {
    id: "zhou-du",
    name: "周渡",
    role: "港务医生",
    group: "outsider",
    firstChapter: 4,
    x: 520,
    y: 540,
    description: "初步判断死者于十点后死亡，随后修改了死亡时间。",
    knownFacts: ["携带镇静剂", "与死者有旧案纠纷", "检查时未发现左腕针孔"],
  },
  {
    id: "unknown-caller",
    name: "雨衣人",
    role: "身份未明",
    group: "outsider",
    firstChapter: 9,
    x: 85,
    y: 365,
    description: "监控中短暂出现的模糊人影，身份尚未确认。",
    knownFacts: ["身高约一米七", "从东侧栈桥进入", "出现时间早于封港警报"],
  },
];

export const relations: RelationEdge[] = [
  { id: "e1", source: "liang-bingwen", target: "liang-zhiwei", label: "父女", kind: "family", firstChapter: 2, status: "confirmed", evidence: "第 2 章，晚宴座次与遗嘱争论" },
  { id: "e2", source: "liang-bingwen", target: "liang-jing", label: "父子", kind: "family", firstChapter: 2, status: "confirmed", evidence: "第 2 章，梁景当众索要航运注资" },
  { id: "e3", source: "gu-qinghe", target: "liang-bingwen", label: "最后见面", kind: "testimony", firstChapter: 3, status: "disputed", evidence: "第 3 章，顾青禾口供；第 7 章门锁记录与其冲突" },
  { id: "e4", source: "shen-yan", target: "gu-qinghe", label: "共同查钟", kind: "action", firstChapter: 4, status: "confirmed", evidence: "第 4 章，两人拆检报时连杆" },
  { id: "e5", source: "liang-zhiwei", target: "liang-jing", label: "遗产冲突", kind: "conflict", firstChapter: 5, status: "confirmed", evidence: "第 5 章，书房争执录音" },
  { id: "e6", source: "su-man", target: "liang-bingwen", label: "隐瞒旧事", kind: "testimony", firstChapter: 6, status: "inferred", evidence: "第 6 章，管家删改过的值班簿" },
  { id: "e7", source: "zhou-du", target: "liang-bingwen", label: "死亡时间矛盾", kind: "conflict", firstChapter: 7, status: "disputed", evidence: "第 7 章，尸温记录与医生补充证词" },
  { id: "e8", source: "liang-jing", target: "unknown-caller", label: "疑似接应", kind: "suspicion", firstChapter: 10, status: "inferred", evidence: "第 10 章，栈桥脚印与未登记车票" },
  { id: "e9", source: "su-man", target: "unknown-caller", label: "可能认识", kind: "suspicion", firstChapter: 11, status: "inferred", evidence: "第 11 章，苏蔓对雨衣人的异常反应" },
  { id: "e10", source: "gu-qinghe", target: "unknown-caller", label: "身份重合？", kind: "suspicion", firstChapter: 14, status: "disputed", evidence: "第 14 章，修复间留下的同型号雨衣扣" },
];

export const chapterSummaries = [
  { chapter: 1, title: "停摆的钟", change: "沈砚抵达雾港；钟楼将在午夜重新启用。" },
  { chapter: 2, title: "遗嘱晚宴", change: "梁家成员首次完整出场；遗产冲突公开。" },
  { chapter: 3, title: "第十声", change: "梁秉文被发现死于反锁机芯室。" },
  { chapter: 4, title: "断裂的连杆", change: "钟声并非由主钟正常敲响。" },
  { chapter: 5, title: "书房录音", change: "梁知微与梁景的争执时间得到确认。" },
  { chapter: 6, title: "被撕掉的值班页", change: "苏蔓的证词出现十一分钟空白。" },
  { chapter: 7, title: "四十分钟", change: "死亡时间被重新评估，顾青禾证词受质疑。" },
  { chapter: 8, title: "第二枚钟锤", change: "沈砚发现报时系统存在独立触发装置。" },
  { chapter: 9, title: "雨衣人", change: "东侧栈桥监控中出现未知人物。" },
  { chapter: 10, title: "未登记船票", change: "梁景可能与外部人员协作。" },
  { chapter: 11, title: "旧海关暗道", change: "钟楼并非完全密闭。" },
  { chapter: 12, title: "潮位表", change: "暗道在案发时是否可通行产生新矛盾。" },
];

export const evidenceItems = [
  { id: "c-17", title: "停止摆动的秒轮", chapter: 3, type: "客观描写", state: "已确认", detail: "秒轮停在 9:24，但主钟在十点仍发出十次钟声。" },
  { id: "c-21", title: "顾青禾的十点证词", chapter: 3, type: "人物陈述", state: "存疑", detail: "她声称十点整在修复间听见完整钟声，门锁日志未支持其位置。" },
  { id: "c-29", title: "独立报时连杆", chapter: 8, type: "客观描写", state: "已确认", detail: "备用连杆可绕过停止的机芯，在预设时间单独触发钟锤。" },
  { id: "c-34", title: "东栈桥铜屑", chapter: 10, type: "AI 推断", state: "推测", detail: "铜屑成分与钟楼检修梯一致，但也可能来自船厂旧零件。" },
];

