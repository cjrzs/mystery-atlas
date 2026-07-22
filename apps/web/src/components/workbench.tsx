"use client";

import Link from "next/link";
import { FormEvent, useCallback, useMemo, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  Bot,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Clock3,
  Eye,
  EyeOff,
  FileCheck2,
  Filter,
  Focus,
  GitBranch,
  ListTree,
  Menu,
  MessageSquareText,
  PanelLeftClose,
  PanelRightClose,
  Search,
  Send,
  Sparkles,
  Users,
} from "lucide-react";
import { CharacterGraph } from "@/components/character-graph";
import { AccountButton } from "@/components/auth-provider";
import { characters, chapterSummaries, evidenceItems, relations, type RelationEdge } from "@/lib/demo-data";

type MainView = "graph" | "timeline" | "chapters" | "clues";
type InspectorTab = "details" | "evidence" | "assistant";
type Selection = { type: "node" | "edge"; id: string };

const relationFilters: { kind: RelationEdge["kind"]; label: string }[] = [
  { kind: "family", label: "亲属" },
  { kind: "testimony", label: "证词" },
  { kind: "conflict", label: "冲突" },
  { kind: "action", label: "共同行动" },
  { kind: "suspicion", label: "嫌疑" },
];

const readerParagraphs = [
  "潮声隔着厚重的石墙传来，像某种迟到的回音。沈砚把手电贴近机芯底座，第二道新鲜划痕从固定栓一直延伸到报时连杆。",
  "“主钟停了，不代表钟锤不能响。”顾青禾蹲在另一侧，声音比平时更低。她没有碰那枚铜制插销，只用铅笔尖指出它与旧图纸不一致的角度。",
  "如果有人提前释放配重，十点的钟声就不再是死亡时间的证明。它只证明，有人希望所有人相信梁秉文在十点仍然活着。",
];

export function Workbench() {
  const [readerOpen, setReaderOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [mainView, setMainView] = useState<MainView>("graph");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("details");
  const [chapter, setChapter] = useState(8);
  const [truthMode, setTruthMode] = useState(false);
  const [selection, setSelection] = useState<Selection>({ type: "node", id: "shen-yan" });
  const [visibleKinds, setVisibleKinds] = useState(() => new Set(relationFilters.map((item) => item.kind)));
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; text: string }[]>([
    { role: "assistant", text: "我只会使用第 1 至 8 章已公开的信息。你可以询问当前人物、证词矛盾或某条线索。" },
  ]);

  const selectedCharacter = selection.type === "node" ? characters.find((item) => item.id === selection.id) : undefined;
  const selectedRelation = selection.type === "edge" ? relations.find((item) => item.id === selection.id) : undefined;

  const visibleEvidence = useMemo(() => evidenceItems.filter((item) => item.chapter <= chapter), [chapter]);

  const handleGraphSelect = useCallback((nextSelection: Selection) => {
    setSelection(nextSelection);
    setInspectorOpen(true);
    setInspectorTab("details");
  }, []);

  const toggleRelationKind = (kind: RelationEdge["kind"]) => {
    setVisibleKinds((current) => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  };

  const toggleTruthMode = () => {
    if (!truthMode) {
      const accepted = window.confirm("真相模式会显示全书身份、动机和案件结论。确认进入吗？");
      if (!accepted) return;
      setTruthMode(true);
      setChapter(18);
    } else {
      setTruthMode(false);
      setChapter(8);
    }
  };

  const askAssistant = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;
    setMessages((current) => [
      ...current,
      { role: "user", text: trimmed },
      { role: "assistant", text: `截至第 ${chapter} 章，钟声只能证明独立报时装置被触发，不能直接证明梁秉文十点仍然活着。支持证据：第 3 章秒轮状态；第 8 章独立报时连杆。` },
    ]);
    setQuestion("");
  };

  return (
    <main className="workbench-shell">
      <header className="workbench-topbar">
        <Link href="/" className="icon-button" aria-label="返回公共档案"><ArrowLeft size={18} /></Link>
        <div className="work-title">
          <div className="mini-cover cover-teal" aria-hidden="true">雾</div>
          <div><strong>雾港钟楼</strong><span>公共档案 · 已核验版本 1.4</span></div>
        </div>
        <div className="topbar-spacer" />
        <label className="chapter-horizon">
          <span><Eye size={15} />信息截止</span>
          <input
            type="range"
            min="1"
            max="18"
            value={chapter}
            onChange={(event) => {
              const next = Number(event.target.value);
              if (next > 8 && !truthMode && !window.confirm(`你的阅读进度是第 8 章。确定查看第 ${next} 章的信息吗？`)) return;
              setChapter(next);
            }}
          />
          <strong>第 {chapter} 章</strong>
        </label>
        <button className={truthMode ? "truth-toggle active" : "truth-toggle"} onClick={toggleTruthMode} type="button">
          {truthMode ? <EyeOff size={15} /> : <Eye size={15} />}{truthMode ? "退出真相" : "真相模式"}
        </button>
        <button className="icon-button" type="button" aria-label="搜索本书"><Search size={18} /></button>
        <AccountButton compact />
      </header>

      <div className={`workbench-grid ${readerOpen ? "reader-open" : "reader-closed"} ${inspectorOpen ? "inspector-open" : "inspector-closed"}`}>
        <aside className="reader-panel" aria-label="小说阅读器">
          <div className="panel-heading">
            <div><BookOpen size={17} /><strong>阅读器</strong><span>私人版本已绑定</span></div>
            <button className="icon-button compact" onClick={() => setReaderOpen(false)} type="button" title="收起阅读器"><PanelLeftClose size={17} /></button>
          </div>
          <div className="reader-chapter-nav">
            <button type="button" aria-label="上一章"><ChevronLeft size={16} /></button>
            <div><span>第 8 章</span><strong>第二枚钟锤</strong></div>
            <button type="button" aria-label="下一章"><ChevronRight size={16} /></button>
          </div>
          <article className="reader-copy">
            <h1>第二枚钟锤</h1>
            {readerParagraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
          </article>
          <div className="reader-footer"><span>阅读进度 44%</span><span>位置 1,284 / 2,903</span></div>
        </aside>

        <section className="database-panel">
          <div className="database-toolbar">
            {!readerOpen && <button className="icon-button" onClick={() => setReaderOpen(true)} type="button" title="展开阅读器"><BookOpen size={18} /></button>}
            <nav className="view-tabs" aria-label="分析视图">
              <button className={mainView === "graph" ? "active" : ""} onClick={() => setMainView("graph")} type="button"><Users size={16} />人物图谱</button>
              <button className={mainView === "timeline" ? "active" : ""} onClick={() => setMainView("timeline")} type="button"><Clock3 size={16} />时间线</button>
              <button className={mainView === "chapters" ? "active" : ""} onClick={() => setMainView("chapters")} type="button"><ListTree size={16} />章节线</button>
              <button className={mainView === "clues" ? "active" : ""} onClick={() => setMainView("clues")} type="button"><GitBranch size={16} />线索板</button>
            </nav>
            <div className="toolbar-spacer" />
            <button className="icon-button" type="button" title="聚焦当前人物"><Focus size={18} /></button>
            {!inspectorOpen && <button className="icon-button" onClick={() => setInspectorOpen(true)} type="button" title="展开分析面板"><MessageSquareText size={18} /></button>}
          </div>

          {mainView === "graph" && (
            <div className="graph-view">
              <div className="graph-context">
                <div><span>主案</span><strong>钟楼机芯室死亡事件</strong></div>
                <div className="relation-filters"><Filter size={14} />{relationFilters.map((item) => (
                  <button key={item.kind} className={visibleKinds.has(item.kind) ? `relation-${item.kind} active` : ""} onClick={() => toggleRelationKind(item.kind)} type="button">{item.label}</button>
                ))}</div>
              </div>
              <CharacterGraph nodes={characters} edges={relations} chapter={chapter} visibleKinds={visibleKinds} selectedId={selection.id} onSelect={handleGraphSelect} />
              <div className="graph-legend">
                <span><i className="legend-confirmed" />已确认</span>
                <span><i className="legend-inferred" />推测</span>
                <span><i className="legend-disputed" />存疑</span>
              </div>
            </div>
          )}

          {mainView === "timeline" && <TimelineView chapter={chapter} />}
          {mainView === "chapters" && <ChapterView chapter={chapter} />}
          {mainView === "clues" && <ClueView chapter={chapter} />}
        </section>

        <aside className="inspector-panel" aria-label="分析面板">
          <div className="inspector-tabs">
            <button className={inspectorTab === "details" ? "active" : ""} onClick={() => setInspectorTab("details")} type="button">详情</button>
            <button className={inspectorTab === "evidence" ? "active" : ""} onClick={() => setInspectorTab("evidence")} type="button">证据 <span>{visibleEvidence.length}</span></button>
            <button className={inspectorTab === "assistant" ? "active" : ""} onClick={() => setInspectorTab("assistant")} type="button"><Sparkles size={14} />助手</button>
            <button className="icon-button compact inspector-close" onClick={() => setInspectorOpen(false)} type="button" title="收起分析面板"><PanelRightClose size={17} /></button>
          </div>

          {inspectorTab === "details" && (
            <div className="inspector-content">
              {selectedCharacter && <CharacterDetails character={selectedCharacter} chapter={chapter} />}
              {selectedRelation && <RelationDetails relation={selectedRelation} />}
            </div>
          )}

          {inspectorTab === "evidence" && (
            <div className="inspector-content evidence-list">
              <div className="section-kicker"><FileCheck2 size={15} />截至第 {chapter} 章可见</div>
              {visibleEvidence.map((evidence) => (
                <button className="evidence-item" key={evidence.id} type="button">
                  <div><span className={`evidence-state state-${evidence.state}`}>{evidence.state}</span><small>第 {evidence.chapter} 章 · {evidence.type}</small></div>
                  <strong>{evidence.title}</strong>
                  <p>{evidence.detail}</p>
                </button>
              ))}
            </div>
          )}

          {inspectorTab === "assistant" && (
            <div className="assistant-pane">
              <div className="assistant-context"><Bot size={16} /><div><strong>侦探助手</strong><span>严格限制在第 1 至 {chapter} 章</span></div></div>
              <div className="assistant-messages">
                {messages.map((message, index) => <div className={`assistant-message ${message.role}`} key={`${message.role}-${index}`}>{message.text}</div>)}
              </div>
              <form className="assistant-form" onSubmit={askAssistant}>
                <input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="询问当前人物、关系或矛盾" />
                <button type="submit" aria-label="发送问题"><Send size={16} /></button>
              </form>
            </div>
          )}

          {inspectorTab !== "assistant" && (
            <button className="assistant-entry" onClick={() => setInspectorTab("assistant")} type="button"><Sparkles size={15} /><span>询问侦探助手</span><kbd>⌘ ↵</kbd></button>
          )}
        </aside>
      </div>
    </main>
  );
}

function CharacterDetails({ character, chapter }: { character: (typeof characters)[number]; chapter: number }) {
  const related = relations.filter((relation) => relation.firstChapter <= chapter && (relation.source === character.id || relation.target === character.id));
  return (
    <>
      <div className="entity-heading"><div className={`entity-avatar avatar-${character.group}`}>{character.name.slice(0, 1)}</div><div><span>{character.role}</span><h2>{character.name}</h2></div></div>
      <p className="entity-description">{character.description}</p>
      <div className="confidence-row"><span>身份状态</span><strong><i />已确认</strong></div>
      <section className="detail-section"><h3>当前已知</h3>{character.knownFacts.map((fact) => <div className="fact-row" key={fact}><CircleHelp size={14} /><span>{fact}</span></div>)}</section>
      <section className="detail-section"><h3>直接关系 <span>{related.length}</span></h3>{related.map((relation) => <div className="relation-row" key={relation.id}><span className={`relation-mark relation-${relation.kind}`} /><div><strong>{relation.label}</strong><small>{relation.status === "confirmed" ? "已确认" : relation.status === "inferred" ? "推测" : "存疑"} · 第 {relation.firstChapter} 章</small></div></div>)}</section>
    </>
  );
}

function RelationDetails({ relation }: { relation: RelationEdge }) {
  const source = characters.find((item) => item.id === relation.source);
  const target = characters.find((item) => item.id === relation.target);
  return (
    <>
      <div className="section-kicker"><GitBranch size={15} />人物关系</div>
      <div className="relation-title"><strong>{source?.name}</strong><span>{relation.label}</span><strong>{target?.name}</strong></div>
      <div className="confidence-row"><span>关系状态</span><strong><i />{relation.status === "confirmed" ? "已确认" : relation.status === "inferred" ? "推测" : "存疑"}</strong></div>
      <section className="detail-section"><h3>证据来源</h3><p className="evidence-quote">{relation.evidence}</p></section>
    </>
  );
}

function TimelineView({ chapter }: { chapter: number }) {
  return <div className="data-view"><div className="data-view-header"><div><span>双时间轴</span><h2>案情发生与叙事揭示</h2></div><button type="button"><Menu size={16} />按案情时间</button></div><div className="timeline-list">{chapterSummaries.filter((item) => item.chapter <= chapter).map((item, index) => <div className="timeline-row" key={item.chapter}><div className="timeline-marker"><span>{String(21 + index).padStart(2, "0")}: {index % 2 ? "15" : "40"}</span><i /></div><div><small>第 {item.chapter} 章首次揭示</small><strong>{item.title}</strong><p>{item.change}</p></div></div>)}</div></div>;
}

function ChapterView({ chapter }: { chapter: number }) {
  return <div className="data-view"><div className="data-view-header"><div><span>章节认知快照</span><h2>读到这里，我们知道什么</h2></div></div><div className="chapter-grid">{chapterSummaries.filter((item) => item.chapter <= chapter).map((item) => <button className="chapter-item" key={item.chapter} type="button"><span>CH. {String(item.chapter).padStart(2, "0")}</span><strong>{item.title}</strong><p>{item.change}</p><small>查看本章变化 <ChevronRight size={13} /></small></button>)}</div></div>;
}

function ClueView({ chapter }: { chapter: number }) {
  return <div className="data-view"><div className="data-view-header"><div><span>线索生命周期</span><h2>支持、反驳与最终回收</h2></div></div><div className="clue-board">{evidenceItems.filter((item) => item.chapter <= chapter).map((item) => <div className="clue-record" key={item.id}><div><span>{item.id}</span><b className={`evidence-state state-${item.state}`}>{item.state}</b></div><h3>{item.title}</h3><p>{item.detail}</p><footer><span>首次出现：第 {item.chapter} 章</span><button type="button">查看证据链</button></footer></div>)}</div></div>;
}
