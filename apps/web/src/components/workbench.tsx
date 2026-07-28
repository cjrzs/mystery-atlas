"use client";

import Link from "next/link";
import {
  type CSSProperties,
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowLeft,
  BookOpen,
  Bot,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Eye,
  EyeOff,
  FileCheck2,
  Filter,
  Focus,
  GitBranch,
  ListTree,
  Maximize2,
  MessageSquareText,
  Minimize2,
  PanelLeftClose,
  PanelRightClose,
  Search,
  Send,
  SlidersHorizontal,
  Sparkles,
  Users,
} from "lucide-react";
import { CharacterGraph } from "@/components/character-graph";
import { AccountButton, useAuth } from "@/components/auth-provider";
import {
  apiRequest,
  type GraphEdge,
  type GraphNode,
  type LibraryItem,
  type ReaderBook,
  type ReaderBlock,
  type ReaderPreferences,
  type WorkbenchAnalysis,
} from "@/lib/api";
import {
  graphStatusName,
  relationCategory,
  relationCategoryOrder,
  relationKindName,
  type RelationCategory,
} from "@/lib/graph-labels";

type MainView = "graph" | "timeline" | "chapters" | "clues";
type InspectorTab = "details" | "evidence" | "assistant";
type Selection = { type: "node" | "edge"; id: string };
type LoadState = "loading" | "ready" | "error";

const READER_PREFERENCES_KEY = "mystery-atlas:reader-preferences";
const defaultReaderPreferences: ReaderPreferences = {
  font_size: 17,
  line_height: 1.9,
  content_width: 720,
  theme: "sepia",
};

const statusNames: Record<string, string> = {
  waiting_configuration: "等待 AI 配置",
  waiting_structure_review: "等待复核章节结构",
  queued: "等待分析",
  running: "分析中",
  completed: "分析完成",
  failed: "分析失败",
  ready: "分析完成",
};

const stageNames: Record<string, string> = {
  waiting_for_ai_configuration: "等待 AI 配置",
  structure_review: "复核章节结构",
  source_validation: "校验正文",
  segment_analysis: "逐章提取人物、事件与证据",
  chapter_synthesis: "合并章节分析",
  book_synthesis: "生成全书结构",
  evidence_verification: "核验原文证据",
  full_book_reconciliation: "复核全书结论",
  persistence: "保存结构化档案",
  completed: "已完成",
  failed: "失败",
  not_started: "尚未开始",
};

export function Workbench({
  slug,
  libraryItemId,
}: {
  slug?: string;
  libraryItemId?: string;
}) {
  const { user } = useAuth();
  const [readerOpen, setReaderOpen] = useState(true);
  const [readerFocused, setReaderFocused] = useState(false);
  const [readerSettingsOpen, setReaderSettingsOpen] = useState(false);
  const [readerTocOpen, setReaderTocOpen] = useState(false);
  const [readerPreferences, setReaderPreferences] =
    useState<ReaderPreferences>(defaultReaderPreferences);
  const [readerPreferencesOwner, setReaderPreferencesOwner] = useState("");
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [mainView, setMainView] = useState<MainView>("graph");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("details");
  const [chapter, setChapter] = useState(1);
  const [truthMode, setTruthMode] = useState(false);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [visibleKinds, setVisibleKinds] = useState<Set<string>>(new Set());
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<
    { role: "user" | "assistant"; text: string }[]
  >([]);
  const [readerBook, setReaderBook] = useState<ReaderBook | null>(null);
  const [readerState, setReaderState] = useState<LoadState>("loading");
  const [readerError, setReaderError] = useState("");
  const [readerChapterNumber, setReaderChapterNumber] = useState(1);
  const [libraryRecordId, setLibraryRecordId] = useState<string | null>(
    libraryItemId ?? null,
  );
  const [analysis, setAnalysis] = useState<WorkbenchAnalysis | null>(null);
  const [analysisState, setAnalysisState] = useState<LoadState>("loading");
  const [analysisError, setAnalysisError] = useState("");
  const [analysisRefresh, setAnalysisRefresh] = useState(0);
  const [retryingAnalysis, setRetryingAnalysis] = useState(false);
  const analysisWorkId = useRef<string | null>(null);
  const readerCopyRef = useRef<HTMLElement | null>(null);
  const currentPreferencesOwner = user?.id ?? "guest";

  useEffect(() => {
    let active = true;
    const stored = window.localStorage.getItem(READER_PREFERENCES_KEY);
    let localPreferences = defaultReaderPreferences;
    if (stored) {
      try {
        localPreferences = normalizeReaderPreferences(JSON.parse(stored));
      } catch {
        localPreferences = defaultReaderPreferences;
      }
    }
    if (!user) {
      Promise.resolve().then(() => {
        if (!active) return;
        setReaderPreferences(localPreferences);
        setReaderPreferencesOwner("guest");
      });
      return () => {
        active = false;
      };
    }
    apiRequest<ReaderPreferences>("/auth/reader-preferences")
      .then((preferences) => {
        if (!active) return;
        setReaderPreferences(normalizeReaderPreferences(preferences));
        setReaderPreferencesOwner(user.id);
      })
      .catch(() => {
        if (!active) return;
        setReaderPreferences(localPreferences);
        setReaderPreferencesOwner(user.id);
      });
    return () => {
      active = false;
    };
  }, [user]);

  useEffect(() => {
    if (readerPreferencesOwner !== currentPreferencesOwner) return;
    window.localStorage.setItem(
      READER_PREFERENCES_KEY,
      JSON.stringify(readerPreferences),
    );
    if (!user) return;
    const timer = window.setTimeout(() => {
      void apiRequest<ReaderPreferences>("/auth/reader-preferences", {
        method: "PATCH",
        body: JSON.stringify(readerPreferences),
      }).catch(() => undefined);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [
    currentPreferencesOwner,
    readerPreferences,
    readerPreferencesOwner,
    user,
  ]);

  useEffect(() => {
    if (!slug && !libraryItemId) return;
    let active = true;
    const path = libraryItemId
      ? `/library/${libraryItemId}/reader`
      : `/works/${slug}/reader`;
    apiRequest<ReaderBook>(path)
      .then(async (book) => {
        if (!active) return;
        const normalizedBook = normalizeReaderBook(book);
        let startingChapter = 1;
        if (user && normalizedBook.visibility === "public" && !libraryItemId) {
          try {
            const record = await apiRequest<LibraryItem>(
              `/library/public/${normalizedBook.edition_id}`,
              { method: "POST" },
            );
            if (!active) return;
            setLibraryRecordId(record.id);
            startingChapter = record.current_chapter;
          } catch {
            startingChapter = 1;
          }
        }
        const maxChapter = Math.max(normalizedBook.chapters.length, 1);
        const boundedChapter = Math.max(
          1,
          Math.min(startingChapter, maxChapter),
        );
        setReaderBook(normalizedBook);
        setReaderChapterNumber(boundedChapter);
        setChapter(boundedChapter);
        setReaderState("ready");
      })
      .catch((caught) => {
        if (!active) return;
        setReaderBook(null);
        setReaderState("error");
        setReaderError(
          caught instanceof Error ? caught.message : "无法读取这本书的正文",
        );
      });
    return () => {
      active = false;
    };
  }, [libraryItemId, slug, user]);

  useEffect(() => {
    if (!readerBook || (!slug && !libraryItemId)) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const basePath = libraryItemId
      ? `/library/${libraryItemId}`
      : `/works/${slug}`;

    const loadAnalysis = async () => {
      try {
        const payload = await apiRequest<WorkbenchAnalysis>(
          `${basePath}/analysis?through_chapter=${chapter}`,
        );
        if (!active) return;
        if (analysisWorkId.current !== payload.work_id) {
          analysisWorkId.current = payload.work_id;
          setVisibleKinds(
            new Set(payload.graph.edges.map((item) => item.kind)),
          );
          setMessages([]);
        }
        setSelection((current) => {
          const stillExists =
            current?.type === "node"
              ? payload.graph.nodes.some((item) => item.id === current.id)
              : payload.graph.edges.some((item) => item.id === current?.id);
          if (current && stillExists) return current;
          const firstNode = payload.graph.nodes[0];
          return firstNode ? { type: "node", id: firstNode.id } : null;
        });
        setAnalysis(payload);
        setAnalysisState("ready");
        setAnalysisError("");
        if (payload.status === "queued" || payload.status === "running") {
          timer = setTimeout(loadAnalysis, 2000);
        }
      } catch (caught) {
        if (!active) return;
        setAnalysisState("error");
        setAnalysisError(
          caught instanceof Error
            ? caught.message
            : "无法读取这本书的结构化分析",
        );
      }
    };

    void loadAnalysis();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [analysisRefresh, chapter, libraryItemId, readerBook, slug]);

  const readerChapter = readerBook?.chapters.find(
    (item) => item.number === readerChapterNumber,
  );
  const readerMaxChapter = Math.max(readerBook?.chapters.length ?? 0, 1);
  const readerBlocks = readerChapter
    ? normalizedReaderBlocks(readerChapter.blocks, readerChapter.text)
    : [];
  const readerStyle = {
    "--reader-font-size": `${readerPreferences.font_size}px`,
    "--reader-line-height": readerPreferences.line_height,
    "--reader-content-width": `${readerPreferences.content_width}px`,
  } as CSSProperties;

  useEffect(() => {
    readerCopyRef.current?.scrollTo({ top: 0, behavior: "auto" });
  }, [readerChapterNumber]);

  const selectedCharacter =
    selection?.type === "node"
      ? analysis?.graph.nodes.find((item) => item.id === selection.id)
      : undefined;
  const selectedRelation =
    selection?.type === "edge"
      ? analysis?.graph.edges.find((item) => item.id === selection.id)
      : undefined;
  const relationKindGroups = useMemo(() => {
    const grouped = new Map<RelationCategory, Set<string>>();
    for (const edge of analysis?.graph.edges ?? []) {
      const category = relationCategory(edge.kind);
      const kinds = grouped.get(category) ?? new Set<string>();
      kinds.add(edge.kind);
      grouped.set(category, kinds);
    }
    return relationCategoryOrder.flatMap((category) => {
      const kinds = grouped.get(category);
      return kinds ? [{ category, kinds: [...kinds] }] : [];
    });
  }, [analysis]);
  const visibleEvidence = analysis?.evidence ?? [];

  const moveReader = (next: number) => {
    const bounded = Math.max(1, Math.min(readerMaxChapter, next));
    setReaderChapterNumber(bounded);
    setChapter(bounded);
    if (libraryRecordId) {
      void apiRequest(`/library/${libraryRecordId}/progress`, {
        method: "PATCH",
        body: JSON.stringify({
          current_chapter: bounded,
          progress: bounded / readerMaxChapter,
        }),
      });
    }
  };

  const handleGraphSelect = useCallback((nextSelection: Selection) => {
    setSelection(nextSelection);
    setInspectorOpen(true);
    setInspectorTab("details");
  }, []);

  const toggleRelationKinds = (kinds: string[]) => {
    setVisibleKinds((current) => {
      const next = new Set(current);
      const allVisible = kinds.every((kind) => next.has(kind));
      for (const kind of kinds) {
        if (allVisible) next.delete(kind);
        else next.add(kind);
      }
      return next;
    });
  };

  const toggleTruthMode = () => {
    if (!truthMode) {
      const accepted = window.confirm(
        "真相模式会显示全书身份、动机和案件结论。确认进入吗？",
      );
      if (!accepted) return;
      setTruthMode(true);
      setChapter(readerMaxChapter);
    } else {
      setTruthMode(false);
      setChapter(readerChapterNumber);
    }
  };

  const askAssistant = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || !readerBook) return;
    const searchableEvidence = visibleEvidence.filter((item) =>
      `${item.title}${item.summary}${item.excerpt}`.includes(trimmed),
    );
    const sources =
      searchableEvidence.length > 0
        ? searchableEvidence.slice(0, 3)
        : visibleEvidence.slice(0, 3);
    const answer =
      sources.length > 0
        ? `截至第 ${chapter} 章，《${readerBook.work_title}》的当前结构化证据包括：${sources
            .map((item) => `“${item.title}”——${item.summary}`)
            .join("；")}`
        : `《${readerBook.work_title}》目前分析到 ${analysis?.progress ?? 0}%，第 ${chapter} 章之前还没有可供回答的结构化证据。`;
    setMessages((current) => [
      ...current,
      { role: "user", text: trimmed },
      { role: "assistant", text: answer },
    ]);
    setQuestion("");
  };

  const retryAnalysis = async () => {
    if (
      !analysis?.job_id ||
      !analysis.can_manage_retry
    ) {
      return;
    }
    setRetryingAnalysis(true);
    try {
      await apiRequest(`/analysis-jobs/${analysis.job_id}/retry`, {
        method: "POST",
      });
      setAnalysisRefresh((current) => current + 1);
    } catch (caught) {
      setAnalysisError(
        caught instanceof Error ? caught.message : "无法重新启动分析任务",
      );
      setAnalysisState("error");
    } finally {
      setRetryingAnalysis(false);
    }
  };

  const backHref = libraryItemId ? "/?scope=private" : "/";
  const workTitle =
    readerBook?.work_title ??
    (readerState === "loading" ? "正在读取书籍…" : "书籍不可用");

  return (
    <main className="workbench-shell">
      <header className="workbench-topbar">
        <Link
          href={backHref}
          className="icon-button"
          aria-label="返回档案库"
        >
          <ArrowLeft size={18} />
        </Link>
        <div className="work-title">
          <div className="mini-cover cover-teal" aria-hidden="true">
            {workTitle.slice(0, 1)}
          </div>
          <div>
            <strong>{workTitle}</strong>
            <span>
              {readerBook
                ? `${readerBook.visibility === "public" ? "公共" : "私人"}档案 · ${readerBook.edition_title}`
                : readerState === "error"
                  ? "正文读取失败"
                  : "正在连接档案"}
            </span>
          </div>
        </div>
        <div className="topbar-spacer" />
        <label className="chapter-horizon">
          <span>
            <Eye size={15} />
            信息截止
          </span>
          <input
            type="range"
            min="1"
            max={readerMaxChapter}
            value={chapter}
            disabled={!readerBook}
            onChange={(event) => {
              const next = Number(event.target.value);
              if (
                next > readerChapterNumber &&
                !truthMode &&
                !window.confirm(
                  `你的阅读进度是第 ${readerChapterNumber} 章。确定查看第 ${next} 章的信息吗？`,
                )
              )
                return;
              setChapter(next);
            }}
          />
          <strong>第 {chapter} 章</strong>
        </label>
        <button
          className={truthMode ? "truth-toggle active" : "truth-toggle"}
          disabled={!readerBook}
          onClick={toggleTruthMode}
          type="button"
        >
          {truthMode ? <EyeOff size={15} /> : <Eye size={15} />}
          {truthMode ? "退出真相" : "真相模式"}
        </button>
        <button className="icon-button" type="button" aria-label="搜索本书">
          <Search size={18} />
        </button>
        <Link
          className="icon-button"
          href={`/feedback${
            readerBook
              ? `?work_id=${readerBook.work_id}&edition_id=${readerBook.edition_id}&chapter=${chapter}`
              : ""
          }`}
          aria-label="反馈当前内容"
        >
          <MessageSquareText size={18} />
        </Link>
        <AccountButton compact />
      </header>

      <div
        className={`workbench-grid ${
          readerOpen ? "reader-open" : "reader-closed"
        } ${inspectorOpen ? "inspector-open" : "inspector-closed"} ${
          readerFocused ? "reader-focused" : ""
        }`}
      >
        <aside
          className={`reader-panel reader-theme-${readerPreferences.theme}`}
          aria-label="小说阅读器"
          style={readerStyle}
        >
          <div className="panel-heading">
            <div>
              <BookOpen size={17} />
              <strong>阅读器</strong>
              <span>
                {readerState === "ready"
                  ? "真实正文"
                  : readerState === "loading"
                    ? "读取中"
                    : "不可用"}
              </span>
            </div>
            <div className="reader-heading-actions">
              <button
                className={
                  readerTocOpen
                    ? "icon-button compact active"
                    : "icon-button compact"
                }
                onClick={() => {
                  setReaderTocOpen((current) => !current);
                  setReaderSettingsOpen(false);
                }}
                type="button"
                title="目录"
                aria-label="目录"
              >
                <ListTree size={16} />
              </button>
              <button
                className={
                  readerSettingsOpen
                    ? "icon-button compact active"
                    : "icon-button compact"
                }
                onClick={() => {
                  setReaderSettingsOpen((current) => !current);
                  setReaderTocOpen(false);
                }}
                type="button"
                title="阅读设置"
              >
                <SlidersHorizontal size={16} />
              </button>
              <button
                className="icon-button compact"
                onClick={() => {
                  setReaderOpen(true);
                  setReaderFocused((current) => !current);
                }}
                type="button"
                title={readerFocused ? "退出专注阅读" : "进入专注阅读"}
              >
                {readerFocused ? (
                  <Minimize2 size={16} />
                ) : (
                  <Maximize2 size={16} />
                )}
              </button>
              {!readerFocused && (
                <button
                  className="icon-button compact"
                  onClick={() => setReaderOpen(false)}
                  type="button"
                  title="收起阅读器"
                >
                  <PanelLeftClose size={17} />
                </button>
              )}
            </div>
          </div>
          {readerTocOpen ? (
            <nav className="reader-toc" aria-label="目录">
              <header>
                <strong>目录</strong>
                <span>{readerBook?.chapters.length ?? 0} 章</span>
              </header>
              <div className="reader-toc-list">
                {readerBook?.chapters.map((item) => (
                  <button
                    aria-current={
                      item.number === readerChapterNumber ? "page" : undefined
                    }
                    className={
                      item.number === readerChapterNumber ? "active" : ""
                    }
                    key={item.number}
                    onClick={() => {
                      moveReader(item.number);
                      setReaderTocOpen(false);
                    }}
                    type="button"
                  >
                    <span
                      title={
                        item.structural_path.slice(0, -1).join(" › ") ||
                        `第 ${item.number} 章`
                      }
                    >
                      {item.structural_path.slice(0, -1).join(" › ") ||
                        `第 ${item.number} 章`}
                    </span>
                    <strong>{item.title || `第 ${item.number} 章`}</strong>
                  </button>
                ))}
              </div>
            </nav>
          ) : (
            <>
              {readerSettingsOpen && (
                <ReaderSettings
                  preferences={readerPreferences}
                  onChange={setReaderPreferences}
                />
              )}
              <div className="reader-chapter-nav">
                <button
                  disabled={!readerBook || readerChapterNumber <= 1}
                  onClick={() => moveReader(readerChapterNumber - 1)}
                  type="button"
                  aria-label="上一章"
                >
                  <ChevronLeft size={16} />
                </button>
                <div>
                  <span>
                    {readerChapter ? `第 ${readerChapter.number} 章` : "—"}
                  </span>
                  <strong>
                    {readerChapter?.title ??
                      (readerState === "loading" ? "正在读取…" : "无可读章节")}
                  </strong>
                </div>
                <button
                  disabled={
                    !readerBook || readerChapterNumber >= readerMaxChapter
                  }
                  onClick={() => moveReader(readerChapterNumber + 1)}
                  type="button"
                  aria-label="下一章"
                >
                  <ChevronRight size={16} />
                </button>
              </div>
              <article className="reader-copy" ref={readerCopyRef}>
                {readerChapter ? (
                  <>
                    {readerChapter.structural_path.length > 1 && (
                      <p className="reader-structure-path">
                        {readerChapter.structural_path.slice(0, -1).join(" › ")}
                      </p>
                    )}
                    {readerChapter.title && <h1>{readerChapter.title}</h1>}
                    {readerBlocks.map((block, index) => (
                      <ReaderBlockContent
                        block={block}
                        index={index}
                        key={`${block.type}-${index}-${block.text.slice(0, 20)}`}
                      />
                    ))}
                  </>
                ) : (
                  <EmptyMessage
                    title={
                      readerState === "loading"
                        ? "正在读取正文"
                        : "正文暂不可用"
                    }
                    detail={
                      readerState === "loading"
                        ? "正在加载这本书的章节。"
                        : readerError || "这本书还没有可用的正文版本。"
                    }
                  />
                )}
              </article>
            </>
          )}
          <div className="reader-footer">
            <span>
              阅读进度{" "}
              {readerBook
                ? Math.round((readerChapterNumber / readerMaxChapter) * 100)
                : 0}
              %
            </span>
            <span>
              第 {readerBook ? readerChapterNumber : 0} /{" "}
              {readerBook ? readerMaxChapter : 0} 章
            </span>
          </div>
        </aside>

        <section className="database-panel">
          <div className="database-toolbar">
            {!readerOpen && (
              <button
                className="icon-button"
                onClick={() => setReaderOpen(true)}
                type="button"
                title="展开阅读器"
              >
                <BookOpen size={18} />
              </button>
            )}
            <nav className="view-tabs" aria-label="分析视图">
              <button
                className={mainView === "graph" ? "active" : ""}
                onClick={() => setMainView("graph")}
                type="button"
              >
                <Users size={16} />
                人物图谱
              </button>
              <button
                className={mainView === "timeline" ? "active" : ""}
                onClick={() => setMainView("timeline")}
                type="button"
              >
                <Clock3 size={16} />
                时间线
              </button>
              <button
                className={mainView === "chapters" ? "active" : ""}
                onClick={() => setMainView("chapters")}
                type="button"
              >
                <ListTree size={16} />
                章节线
              </button>
              <button
                className={mainView === "clues" ? "active" : ""}
                onClick={() => setMainView("clues")}
                type="button"
              >
                <GitBranch size={16} />
                线索板
              </button>
            </nav>
            <div className="toolbar-spacer" />
            <button
              className="icon-button"
              type="button"
              title="聚焦当前人物"
            >
              <Focus size={18} />
            </button>
            {!inspectorOpen && (
              <button
                className="icon-button"
                onClick={() => setInspectorOpen(true)}
                type="button"
                title="展开分析面板"
              >
                <MessageSquareText size={18} />
              </button>
            )}
          </div>

          <AnalysisStatus
            analysis={analysis}
            state={analysisState}
            retrying={retryingAnalysis}
            onRetry={retryAnalysis}
          />

          {analysisState === "error" && (
            <EmptyMessage title="结构化分析读取失败" detail={analysisError} />
          )}

          {analysisState !== "error" && mainView === "graph" && (
            <div className="graph-view">
              <div className="graph-context">
                <div>
                  <span>当前作品</span>
                  <strong>{readerBook?.work_title ?? "—"}</strong>
                </div>
                {relationKindGroups.length > 0 && (
                  <div className="relation-filters">
                    <Filter size={14} />
                    {relationKindGroups.map(({ category, kinds }) => (
                      <button
                        key={category}
                        className={
                          kinds.every((kind) => visibleKinds.has(kind))
                            ? `relation-${category} active`
                            : ""
                        }
                        onClick={() => toggleRelationKinds(kinds)}
                        type="button"
                      >
                        {relationKindName(category)}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {analysis && analysis.graph.nodes.length > 0 ? (
                <>
                  <CharacterGraph
                    nodes={analysis.graph.nodes}
                    edges={analysis.graph.edges}
                    chapter={chapter}
                    visibleKinds={visibleKinds}
                    selectedId={selection?.id ?? null}
                    onSelect={handleGraphSelect}
                  />
                  <div className="graph-legend">
                    <span>
                      <i className="legend-confirmed" />
                      已确认
                    </span>
                    <span>
                      <i className="legend-inferred" />
                      推测
                    </span>
                    <span>
                      <i className="legend-disputed" />
                      存疑
                    </span>
                  </div>
                </>
              ) : (
                <EmptyMessage
                  title="暂无人物关系"
                  detail={analysisEmptyDetail(analysis)}
                />
              )}
            </div>
          )}

          {analysisState !== "error" && mainView === "timeline" && (
            <TimelineView
              items={analysis?.timeline ?? []}
              detail={analysisEmptyDetail(analysis)}
            />
          )}
          {analysisState !== "error" && mainView === "chapters" && (
            <ChapterView
              items={analysis?.chapters ?? []}
              book={readerBook}
              detail={analysisEmptyDetail(analysis)}
            />
          )}
          {analysisState !== "error" && mainView === "clues" && (
            <ClueView
              items={visibleEvidence}
              detail={analysisEmptyDetail(analysis)}
            />
          )}
        </section>

        <aside className="inspector-panel" aria-label="分析面板">
          <div className="inspector-tabs">
            <button
              className={inspectorTab === "details" ? "active" : ""}
              onClick={() => setInspectorTab("details")}
              type="button"
            >
              详情
            </button>
            <button
              className={inspectorTab === "evidence" ? "active" : ""}
              onClick={() => setInspectorTab("evidence")}
              type="button"
            >
              证据 <span>{visibleEvidence.length}</span>
            </button>
            <button
              className={inspectorTab === "assistant" ? "active" : ""}
              onClick={() => setInspectorTab("assistant")}
              type="button"
            >
              <Sparkles size={14} />
              助手
            </button>
            <button
              className="icon-button compact inspector-close"
              onClick={() => setInspectorOpen(false)}
              type="button"
              title="收起分析面板"
            >
              <PanelRightClose size={17} />
            </button>
          </div>

          {inspectorTab === "details" && (
            <div className="inspector-content">
              {selectedCharacter && analysis ? (
                <CharacterDetails
                  character={selectedCharacter}
                  edges={analysis.graph.edges}
                  nodes={analysis.graph.nodes}
                  chapter={chapter}
                />
              ) : selectedRelation && analysis ? (
                <RelationDetails
                  relation={selectedRelation}
                  nodes={analysis.graph.nodes}
                />
              ) : (
                <EmptyMessage
                  title="暂无可查看对象"
                  detail={analysisEmptyDetail(analysis)}
                />
              )}
            </div>
          )}

          {inspectorTab === "evidence" && (
            <div className="inspector-content evidence-list">
              <div className="section-kicker">
                <FileCheck2 size={15} />
                截至第 {chapter} 章可见
              </div>
              {visibleEvidence.length > 0 ? (
                visibleEvidence.map((evidence) => (
                  <button
                    className="evidence-item"
                    key={evidence.id}
                    type="button"
                  >
                    <div>
                      <span
                        className={`evidence-state state-${evidence.status}`}
                      >
                        {evidence.status}
                      </span>
                      <small>
                        第 {evidence.first_chapter} 章 ·{" "}
                        {evidence.source_type}
                      </small>
                    </div>
                    <strong>{evidence.title}</strong>
                    <p>{evidence.summary}</p>
                  </button>
                ))
              ) : (
                <EmptyMessage
                  title="暂无证据"
                  detail={analysisEmptyDetail(analysis)}
                />
              )}
            </div>
          )}

          {inspectorTab === "assistant" && (
            <div className="assistant-pane">
              <div className="assistant-context">
                <Bot size={16} />
                <div>
                  <strong>{readerBook?.work_title ?? "本书"}助手</strong>
                  <span>只使用第 1 至 {chapter} 章的结构化数据</span>
                </div>
              </div>
              <div className="assistant-messages">
                {messages.length === 0 && (
                  <div className="assistant-message assistant">
                    我会基于这本书当前已经生成的结构化证据回答，不会调用演示档案。
                  </div>
                )}
                {messages.map((message, index) => (
                  <div
                    className={`assistant-message ${message.role}`}
                    key={`${message.role}-${index}`}
                  >
                    {message.text}
                  </div>
                ))}
              </div>
              <form className="assistant-form" onSubmit={askAssistant}>
                <input
                  value={question}
                  disabled={!readerBook}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="询问当前人物、关系或矛盾"
                />
                <button
                  disabled={!readerBook}
                  type="submit"
                  aria-label="发送问题"
                >
                  <Send size={16} />
                </button>
              </form>
            </div>
          )}

          {inspectorTab !== "assistant" && (
            <button
              className="assistant-entry"
              onClick={() => setInspectorTab("assistant")}
              type="button"
            >
              <Sparkles size={15} />
              <span>询问本书助手</span>
              <kbd>⌘ ↵</kbd>
            </button>
          )}
        </aside>
      </div>
    </main>
  );
}

function normalizeReaderPreferences(value: unknown): ReaderPreferences {
  const candidate =
    value && typeof value === "object"
      ? (value as Partial<ReaderPreferences>)
      : {};
  const clamp = (number: unknown, minimum: number, maximum: number, fallback: number) =>
    typeof number === "number" && Number.isFinite(number)
      ? Math.min(maximum, Math.max(minimum, number))
      : fallback;
  const theme =
    candidate.theme === "light" ||
    candidate.theme === "sepia" ||
    candidate.theme === "dark"
      ? candidate.theme
      : defaultReaderPreferences.theme;
  return {
    font_size: Math.round(
      clamp(candidate.font_size, 14, 22, defaultReaderPreferences.font_size),
    ),
    line_height: clamp(
      candidate.line_height,
      1.5,
      2.4,
      defaultReaderPreferences.line_height,
    ),
    content_width: Math.round(
      clamp(
        candidate.content_width,
        520,
        900,
        defaultReaderPreferences.content_width,
      ),
    ),
    theme,
  };
}

function normalizedReaderBlocks(
  blocks: ReaderBlock[] | undefined,
  text: string,
): ReaderBlock[] {
  if (blocks?.length) return blocks;
  return text
    .replace(/\r\n?/g, "\n")
    .split(/\n\s*\n+|\n/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
    .map((paragraph) => ({ type: "paragraph", text: paragraph }));
}

function normalizeReaderBook(book: ReaderBook): ReaderBook {
  return {
    ...book,
    chapters: (book.chapters ?? []).map((item) => ({
      ...item,
      blocks: item.blocks ?? [],
      structural_path: item.structural_path ?? [],
    })),
  };
}

function ReaderBlockContent({
  block,
  index,
}: {
  block: ReaderBlock;
  index: number;
}) {
  if (block.type === "divider") {
    return <hr className="reader-divider" aria-label="原文分隔符" />;
  }
  if (block.type === "heading") {
    return <h2 className="reader-section-heading">{block.text}</h2>;
  }
  if (block.type === "quote") {
    return <blockquote className="reader-quote">{block.text}</blockquote>;
  }
  if (block.type === "pre") {
    return <pre className="reader-preformatted">{block.text}</pre>;
  }
  if (block.type === "figure") {
    return (
      <figure className="reader-figure">
        <div aria-hidden="true">图</div>
        <figcaption>{block.alt || block.text || "原书插图"}</figcaption>
      </figure>
    );
  }
  if (block.type === "pagebreak") {
    return (
      <span
        className="reader-pagebreak"
        data-page-label={block.text}
        aria-hidden="true"
      />
    );
  }
  const languageClass = /[\u3400-\u9fff]/.test(block.text)
    ? `reader-block chinese${block.semantic_type?.includes("note") ? " reader-note" : ""}`
    : `reader-block${block.semantic_type?.includes("note") ? " reader-note" : ""}`;
  return (
    <p className={languageClass} data-reader-block={index + 1}>
      {block.text}
    </p>
  );
}

function ReaderSettings({
  preferences,
  onChange,
}: {
  preferences: ReaderPreferences;
  onChange: (preferences: ReaderPreferences) => void;
}) {
  const update = (change: Partial<ReaderPreferences>) =>
    onChange(normalizeReaderPreferences({ ...preferences, ...change }));
  return (
    <section className="reader-settings" aria-label="阅读设置">
      <label>
        <span>字号</span>
        <input
          type="range"
          min="14"
          max="22"
          value={preferences.font_size}
          onChange={(event) => update({ font_size: Number(event.target.value) })}
        />
        <output>{preferences.font_size}px</output>
      </label>
      <label>
        <span>行距</span>
        <input
          type="range"
          min="1.5"
          max="2.4"
          step="0.1"
          value={preferences.line_height}
          onChange={(event) => update({ line_height: Number(event.target.value) })}
        />
        <output>{preferences.line_height.toFixed(1)}</output>
      </label>
      <label>
        <span>版心</span>
        <input
          type="range"
          min="520"
          max="900"
          step="20"
          value={preferences.content_width}
          onChange={(event) =>
            update({ content_width: Number(event.target.value) })
          }
        />
        <output>{preferences.content_width}px</output>
      </label>
      <div className="reader-theme-options" aria-label="阅读主题">
        {(
          [
            ["light", "浅色"],
            ["sepia", "米色"],
            ["dark", "深色"],
          ] as const
        ).map(([theme, label]) => (
          <button
            className={preferences.theme === theme ? "active" : ""}
            key={theme}
            onClick={() => update({ theme })}
            type="button"
          >
            <i className={`reader-theme-swatch ${theme}`} />
            {label}
          </button>
        ))}
      </div>
    </section>
  );
}

function AnalysisStatus({
  analysis,
  state,
  retrying,
  onRetry,
}: {
  analysis: WorkbenchAnalysis | null;
  state: LoadState;
  retrying: boolean;
  onRetry: () => void;
}) {
  const progress = analysis?.progress ?? 0;
  const status =
    state === "loading"
      ? "读取分析状态"
      : statusNames[analysis?.status ?? ""] ?? analysis?.status ?? "尚未开始";
  const stage =
    stageNames[analysis?.stage ?? ""] ?? analysis?.stage ?? "等待任务信息";
  return (
    <div className="workbench-analysis-status" aria-live="polite">
      <div>
        <span>{status}</span>
        <span className="workbench-analysis-actions">
          {analysis?.status === "waiting_structure_review" &&
            analysis.can_manage_retry && (
              <Link href="/library/import">复核章节结构</Link>
            )}
          {(analysis?.status === "failed" ||
            analysis?.status === "waiting_configuration") &&
            analysis?.can_manage_retry &&
            analysis.job_id && (
              <button
                disabled={retrying}
                onClick={onRetry}
                type="button"
              >
                {retrying
                  ? "正在重新分析…"
                  : "重新分析"}
              </button>
            )}
          <strong>{progress}%</strong>
        </span>
      </div>
      <div className="progress-track">
        <i style={{ width: `${progress}%` }} />
      </div>
      <small>{stage}</small>
      {analysis?.stage_detail && analysis.status === "running" && (
        <small>
          {analysis.stage_detail}
          {analysis.current_call_id
            ? ` · ${analysis.current_call_id}`
            : ""}
          {analysis.response_chars > 0
            ? ` · 已接收 ${analysis.response_chars.toLocaleString()} 字符`
            : ""}
          {analysis.content_idle_seconds > 0
            ? ` · ${analysis.content_idle_seconds} 秒无新增内容`
            : ""}
        </small>
      )}
      {analysis?.retry_hint && (
        <small className="analysis-retry-hint">{analysis.retry_hint}</small>
      )}
    </div>
  );
}

function CharacterDetails({
  character,
  edges,
  nodes,
  chapter,
}: {
  character: GraphNode;
  edges: GraphEdge[];
  nodes: GraphNode[];
  chapter: number;
}) {
  const related = edges.filter(
    (relation) =>
      relation.first_chapter <= chapter &&
      (relation.source === character.id || relation.target === character.id),
  );
  const names = new Map(nodes.map((item) => [item.id, item.name]));
  return (
    <>
      <div className="entity-heading">
        <div className={`entity-avatar avatar-${character.group}`}>
          {character.name.slice(0, 1)}
        </div>
        <div>
          <span>{character.role || "人物"}</span>
          <h2>{character.name}</h2>
        </div>
      </div>
      <p className="entity-description">
        {character.description || "暂无人物描述。"}
      </p>
      <div className="confidence-row">
        <span>身份状态</span>
        <strong>
          <i />
          {graphStatusName(character.group)}
        </strong>
      </div>
      <section className="detail-section">
        <h3>
          直接关系 <span>{related.length}</span>
        </h3>
        {related.map((relation) => {
          const otherId =
            relation.source === character.id
              ? relation.target
              : relation.source;
          return (
            <div className="relation-row" key={relation.id}>
              <span
                className={`relation-mark relation-${relationCategory(relation.kind)}`}
              />
              <div>
                <strong>
                  {relation.label} · {names.get(otherId) ?? "未知人物"}
                </strong>
                <small>
                  {graphStatusName(relation.status)}{" "}
                  · 第 {relation.first_chapter} 章
                </small>
              </div>
            </div>
          );
        })}
      </section>
    </>
  );
}

function RelationDetails({
  relation,
  nodes,
}: {
  relation: GraphEdge;
  nodes: GraphNode[];
}) {
  const source = nodes.find((item) => item.id === relation.source);
  const target = nodes.find((item) => item.id === relation.target);
  return (
    <>
      <div className="section-kicker">
        <GitBranch size={15} />
        人物关系
      </div>
      <div className="relation-title">
        <strong>{source?.name ?? "未知人物"}</strong>
        <span>{relation.label}</span>
        <strong>{target?.name ?? "未知人物"}</strong>
      </div>
      <div className="confidence-row">
        <span>关系状态</span>
        <strong>
          <i />
          {graphStatusName(relation.status)}
        </strong>
      </div>
      <section className="detail-section">
        <h3>证据来源</h3>
        <p className="evidence-quote">
          {relation.evidence || "暂无已核验的直接引文。"}
        </p>
      </section>
    </>
  );
}

function TimelineView({
  items,
  detail,
}: {
  items: WorkbenchAnalysis["timeline"];
  detail: string;
}) {
  return (
    <div className="data-view">
      <div className="data-view-header">
        <div>
          <span>双时间轴</span>
          <h2>案情发生与叙事揭示</h2>
        </div>
      </div>
      {items.length > 0 ? (
        <div className="timeline-list">
          {items.map((item, index) => (
            <div
              className="timeline-row"
              key={`${item.chapter}-${item.sequence}-${index}`}
            >
              <div className="timeline-marker">
                <span>{item.story_time || `顺序 ${item.sequence}`}</span>
                <i />
              </div>
              <div>
                <small>
                  第 {item.chapter} 章
                  {item.narrative_time ? ` · ${item.narrative_time}` : ""}
                </small>
                <strong>{item.summary}</strong>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyMessage title="暂无时间线事件" detail={detail} />
      )}
    </div>
  );
}

function ChapterView({
  items,
  book,
  detail,
}: {
  items: WorkbenchAnalysis["chapters"];
  book: ReaderBook | null;
  detail: string;
}) {
  return (
    <div className="data-view">
      <div className="data-view-header">
        <div>
          <span>章节认知快照</span>
          <h2>读到这里，我们知道什么</h2>
        </div>
      </div>
      {items.length > 0 ? (
        <div className="chapter-grid">
          {items.map((item) => (
            <div className="chapter-item" key={item.chapter}>
              <span>CH. {String(item.chapter).padStart(2, "0")}</span>
              <strong>
                {book?.chapters.find(
                  (chapter) => chapter.number === item.chapter,
                )?.title ?? `第 ${item.chapter} 章`}
              </strong>
              <p>{item.summary}</p>
            </div>
          ))}
        </div>
      ) : (
        <EmptyMessage title="暂无章节快照" detail={detail} />
      )}
    </div>
  );
}

function ClueView({
  items,
  detail,
}: {
  items: WorkbenchAnalysis["evidence"];
  detail: string;
}) {
  return (
    <div className="data-view">
      <div className="data-view-header">
        <div>
          <span>线索生命周期</span>
          <h2>支持、反驳与最终回收</h2>
        </div>
      </div>
      {items.length > 0 ? (
        <div className="clue-board">
          {items.map((item) => (
            <div className="clue-record" key={item.id}>
              <div>
                <span>第 {item.first_chapter} 章</span>
                <b className={`evidence-state state-${item.status}`}>
                  {item.status}
                </b>
              </div>
              <h3>{item.title}</h3>
              <p>{item.summary}</p>
              <footer>
                <span>来源：{item.source_type}</span>
              </footer>
            </div>
          ))}
        </div>
      ) : (
        <EmptyMessage title="暂无线索" detail={detail} />
      )}
    </div>
  );
}

function EmptyMessage({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="workbench-empty">
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

function analysisEmptyDetail(analysis: WorkbenchAnalysis | null): string {
  if (!analysis) return "正在读取这本书的分析状态。";
  if (analysis.status === "waiting_configuration") {
    return "分析任务正在等待模型配置，配置可用后会自动继续。";
  }
  if (analysis.status === "failed") {
    return analysis.error || "分析任务失败，请检查任务日志后重试。";
  }
  if (analysis.status === "queued" || analysis.status === "running") {
    return `结构化分析当前为 ${analysis.progress}%，数据生成后会自动显示在这里。`;
  }
  return "这本书在当前阅读章节之前还没有对应的结构化数据。";
}
