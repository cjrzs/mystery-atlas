"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  GitCompareArrows,
  History,
  RotateCcw,
  Search,
  Sparkles,
  X,
} from "lucide-react";

type ReviewStatus = "pending" | "approved" | "rejected";

type ReviewRecord = {
  id: string;
  type: string;
  title: string;
  chapter: number;
  confidence: number;
  evidenceCount: number;
  risk: "冲突" | "低置信度" | "新增";
  status: ReviewStatus;
};

const seedItems: ReviewRecord[] = [
  { id: "RV-031", type: "人物关系", title: "顾青禾可能提前设置报时连杆", chapter: 8, confidence: 71, evidenceCount: 3, risk: "新增", status: "pending" },
  { id: "RV-032", type: "证据", title: "周渡的尸检记录遗漏左腕针孔", chapter: 7, confidence: 56, evidenceCount: 2, risk: "冲突", status: "pending" },
  { id: "RV-033", type: "身份推论", title: "雨衣人与修复师身份可能重合", chapter: 14, confidence: 42, evidenceCount: 2, risk: "低置信度", status: "pending" },
  { id: "RV-034", type: "时间线", title: "备用配重最晚于九点二十分释放", chapter: 8, confidence: 86, evidenceCount: 4, risk: "新增", status: "pending" },
  { id: "RV-035", type: "人物别名", title: "港务日志中的 L.Z.W. 指向梁知微", chapter: 6, confidence: 78, evidenceCount: 3, risk: "新增", status: "pending" },
];

export function ReviewConsole() {
  const [items, setItems] = useState(seedItems);
  const [selectedId, setSelectedId] = useState(seedItems[0].id);
  const [filter, setFilter] = useState<"全部" | "待审核" | "冲突">("全部");

  const selected = items.find((item) => item.id === selectedId) ?? items[0];
  const visibleItems = useMemo(() => items.filter((item) => {
    if (filter === "待审核") return item.status === "pending";
    if (filter === "冲突") return item.risk === "冲突";
    return true;
  }), [filter, items]);
  const approvedCount = items.filter((item) => item.status === "approved").length;
  const pendingCount = items.filter((item) => item.status === "pending").length;

  const updateStatus = (status: ReviewStatus) => {
    setItems((current) => current.map((item) => item.id === selected.id ? { ...item, status } : item));
  };

  return (
    <main className="review-page">
      <header className="review-header">
        <div>
          <p className="eyebrow">ADMIN REVIEW CONSOLE</p>
          <h1>公共档案审核台</h1>
          <p>《雾港钟楼》· AI 分析批次 #MA-20260721-04</p>
        </div>
        <div className="review-header-actions">
          <button className="secondary-command" type="button"><History size={15} />版本历史</button>
          <button className="publish-command" disabled={pendingCount > 0} type="button"><CheckCircle2 size={15} />发布版本 1.5</button>
        </div>
      </header>

      <section className="review-summary" aria-label="审核进度">
        <div><span>本批次变更</span><strong>{items.length}</strong></div>
        <div><span>已批准</span><strong>{approvedCount}</strong></div>
        <div><span>仍待处理</span><strong>{pendingCount}</strong></div>
        <div className="review-progress"><div><span>审核完成度</span><strong>{Math.round(approvedCount / items.length * 100)}%</strong></div><i><b style={{ width: `${approvedCount / items.length * 100}%` }} /></i></div>
      </section>

      <section className="review-console">
        <aside className="review-queue">
          <div className="review-queue-tools">
            <label><Search size={14} /><input placeholder="搜索变更" /></label>
            <div>{(["全部", "待审核", "冲突"] as const).map((item) => <button className={filter === item ? "active" : ""} onClick={() => setFilter(item)} type="button" key={item}>{item}</button>)}</div>
          </div>
          <div className="review-items">
            {visibleItems.map((item) => (
              <button className={`review-item ${item.id === selected.id ? "active" : ""}`} onClick={() => setSelectedId(item.id)} type="button" key={item.id}>
                <div><span>{item.type}</span><small>第 {item.chapter} 章</small></div>
                <strong>{item.title}</strong>
                <footer>
                  <span className={`risk risk-${item.risk}`}>{item.risk}</span>
                  <span>{item.evidenceCount} 条证据</span>
                  {item.status === "approved" && <Check size={13} />}
                  {item.status === "rejected" && <X size={13} />}
                </footer>
              </button>
            ))}
          </div>
        </aside>

        <section className="review-diff">
          <div className="review-panel-title"><div><GitCompareArrows size={16} /><span>图谱变更</span></div><button type="button">认知截止：第 {selected.chapter} 章 <ChevronDown size={13} /></button></div>
          <div className="diff-canvas">
            <div className="diff-node node-gu">顾青禾<small>钟表修复师</small></div>
            <div className="diff-relation"><span>{selected.type === "人物关系" ? "可能设置" : "关联证据"}</span><i /></div>
            <div className="diff-node node-clock">独立报时装置<small>线索 C-29</small></div>
            <div className="diff-note"><Sparkles size={13} /><span>AI 新增</span><strong>置信度 {selected.confidence}%</strong></div>
          </div>
          <div className="change-rationale">
            <span>AI 修改说明</span>
            <h2>{selected.title}</h2>
            <p>本次分析把人物陈述、门锁记录和报时装置状态建立了新的关联。该结论仍属于阶段性推测，发布后会在第 {selected.chapter} 章认知快照中显示。</p>
            <div className="reasoning-chain"><span>顾青禾掌握钥匙</span><i /><span>连杆存在新划痕</span><i /><strong>可能提前设置</strong></div>
          </div>
        </section>

        <aside className="review-evidence">
          <div className="review-panel-title"><div><CircleDashed size={16} /><span>证据核验</span></div><span>{selected.evidenceCount} 项</span></div>
          <div className="review-evidence-list">
            <article>
              <header><span>客观描写</span><small>第 8 章 · 位置 1284</small></header>
              <p>第二道新鲜划痕从固定栓一直延伸到报时连杆。</p>
              <footer><CheckCircle2 size={13} />版本定位已匹配</footer>
            </article>
            <article>
              <header><span>人物陈述</span><small>第 4 章 · 顾青禾</small></header>
              <p>“主钟停了，不代表钟锤不能响。”</p>
              <footer className="warning"><AlertTriangle size={13} />陈述不能单独作为事实</footer>
            </article>
            <article>
              <header><span>反驳证据</span><small>第 7 章 · 门锁日志</small></header>
              <p>九点二十分后没有修复师钥匙进入机芯室的记录。</p>
              <footer><CheckCircle2 size={13} />结构化记录已确认</footer>
            </article>
          </div>
          <div className="review-actions">
            <button className="reject-action" onClick={() => updateStatus("rejected")} type="button"><X size={16} />驳回</button>
            <button className="reset-action" onClick={() => updateStatus("pending")} type="button" aria-label="恢复待审核"><RotateCcw size={16} /></button>
            <button className="approve-action" onClick={() => updateStatus("approved")} type="button"><Check size={16} />批准</button>
          </div>
        </aside>
      </section>
    </main>
  );
}

