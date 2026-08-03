"use client";

import Link from "next/link";
import { ChangeEvent, DragEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  BookCheck,
  BookOpenText,
  FileText,
  LoaderCircle,
  LockKeyhole,
  LogIn,
  RotateCw,
  Sparkles,
  Upload,
  Users,
  X,
} from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiRequest, type BookImport, type BookImportSummary } from "@/lib/api";

const stageNames: Record<string, string> = {
  waiting: "等待解析",
  extracting_text: "提取正文",
  detecting_chapters: "识别章节",
  detecting_metadata: "AI 预解析档案信息",
  detecting_tags: "AI 预解析档案信息",
  awaiting_confirmation: "等待选择入库类型",
  structure_review_required: "需要复核章节结构",
  ready_for_analysis: "已进入档案库",
  failed: "解析失败",
};

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

type StructureSegment = {
  source_number: number;
  start_block: number;
  end_block: number;
};

type StructureDraft = {
  title: string;
  parent_path: string[];
  segments: StructureSegment[];
};

function structureDrafts(item: BookImport): StructureDraft[] {
  return item.chapters.flatMap((chapter) => {
    const blockCount = chapter.blocks?.length ?? 0;
    if (blockCount === 0) return [];
    return [{
      title: chapter.title,
      parent_path: (chapter.structural_path ?? []).slice(0, -1),
      segments: [{
        source_number: chapter.number,
        start_block: 0,
        end_block: blockCount,
      }],
    }];
  });
}

export default function ImportPage() {
  const { user, loading } = useAuth();
  const fileInput = useRef<HTMLInputElement>(null);
  const refreshGeneration = useRef(0);
  const optimisticImports = useRef(new Map<string, BookImportSummary>());
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [imports, setImports] = useState<BookImportSummary[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");

  const refreshImports = useCallback(async () => {
    if (!user) return;
    const requestId = ++refreshGeneration.current;
    try {
      const items = await apiRequest<BookImportSummary[]>("/imports");
      if (requestId !== refreshGeneration.current) return;
      const serverIds = new Set(items.map((item) => item.id));
      for (const itemId of serverIds) optimisticImports.current.delete(itemId);
      const pending = [...optimisticImports.current.values()].filter(
        (item) => !serverIds.has(item.id),
      );
      setImports([...pending, ...items]);
    } catch (caught) {
      if (requestId !== refreshGeneration.current) return;
      if (!(caught instanceof ApiError && caught.status === 401)) {
        setError(caught instanceof ApiError ? caught.message : "读取上传记录失败");
      }
    }
  }, [user]);

  useEffect(() => {
    if (!user) return;
    void refreshImports();
    return () => { refreshGeneration.current += 1; };
  }, [user, refreshImports]);

  useEffect(() => {
    if (!imports.some((item) => item.status === "queued" || item.status === "parsing")) return;
    let active = true;
    let timer = 0;
    const poll = async (): Promise<void> => {
      await refreshImports();
      if (active) timer = window.setTimeout(() => void poll(), 1500);
    };
    timer = window.setTimeout(() => void poll(), 1500);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [imports, refreshImports]);

  const chooseFile = (file?: File) => {
    if (!file) return;
    if (!/\.(epub|txt|pdf)$/i.test(file.name)) {
      setError("请选择 EPUB、TXT 或 PDF 文件");
      return;
    }
    setSelectedFile(file);
    setError("");
  };

  const handleFileInput = (event: ChangeEvent<HTMLInputElement>) => chooseFile(event.target.files?.[0]);
  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files[0]);
  };

  const upload = async () => {
    if (!selectedFile) return;
    setUploading(true);
    setError("");
    const body = new FormData();
    body.append("file", selectedFile);
    try {
      const created = await apiRequest<BookImport>("/imports", { method: "POST", body });
      optimisticImports.current.set(created.id, created);
      setImports((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setSelectedFile(null);
      if (fileInput.current) fileInput.current.value = "";
      await refreshImports();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "上传失败，请稍后重试");
    } finally {
      setUploading(false);
    }
  };

  if (loading) {
    return <div className="site-shell"><AppHeader /><main className="access-gate"><span className="account-loading" /><p>正在读取档案</p></main></div>;
  }

  if (!user) {
    return <div className="site-shell"><AppHeader /><main className="access-gate"><LogIn size={24} /><h1>登录后上传书籍</h1><p>私人文件只属于你的账户；公开文件会进入公共档案。</p><Link className="primary-command" href="/login?next=/library/import">登录或注册</Link></main></div>;
  }

  return (
    <div className="site-shell">
      <AppHeader />
      <main className="library-page">
        <header className="library-heading">
          <div><p className="eyebrow">ARCHIVE IMPORT</p><h1>上传书籍</h1><p>{user.display_name} · AI 先预解析书籍信息，你只需要选择入库类型</p></div>
          <button className="secondary-command" onClick={() => void refreshImports()} type="button"><RotateCw size={15} />刷新</button>
        </header>

        <section className="import-workspace">
          <div className="upload-panel">
            <div className="section-title"><Upload size={17} /><div><strong>第一步：选择文件</strong><span>EPUB / TXT / PDF，最大 50 MB</span></div></div>
            <input ref={fileInput} className="visually-hidden" accept=".epub,.txt,.pdf" onChange={handleFileInput} type="file" />
            <div className={dragging ? "file-dropzone dragging" : "file-dropzone"} onDragEnter={(event) => { event.preventDefault(); setDragging(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={handleDrop}>
              <BookOpenText size={28} /><strong>拖入小说文件</strong><span>系统会结合封面、序章或目录预解析书籍信息</span><button className="secondary-command" onClick={() => fileInput.current?.click()} type="button"><FileText size={15} />选择文件</button>
            </div>
            {selectedFile && <div className="selected-file"><FileText size={18} /><div><strong>{selectedFile.name}</strong><span>{formatBytes(selectedFile.size)}</span></div><button className="icon-button compact" onClick={() => setSelectedFile(null)} type="button" title="移除文件"><X size={16} /></button></div>}
            {error && <p className="form-error" role="alert"><AlertCircle size={15} />{error}</p>}
            <button className="primary-command upload-command" disabled={!selectedFile || uploading} onClick={() => void upload()} type="button">{uploading ? <LoaderCircle className="spin" size={16} /> : <Upload size={16} />}{uploading ? "正在上传" : "上传并提取信息"}</button>
          </div>

          <div className="import-history">
            <div className="section-title"><BookCheck size={17} /><div><strong>第二步：选择入库类型</strong><span>{imports.length} 条上传记录</span></div></div>
            {imports.length === 0 ? <div className="empty-imports"><BookOpenText size={24} /><p>还没有上传记录</p></div> : <div className="import-list">{imports.map((item) => <ImportRecord key={`${item.id}:${item.stage}`} item={item} onChanged={refreshImports} />)}</div>}
          </div>
        </section>
      </main>
    </div>
  );
}

function ImportRecord({ item, onChanged }: { item: BookImportSummary; onChanged: () => Promise<void> }) {
  const active = item.status === "queued" || item.status === "parsing";
  const awaiting = item.status === "completed" && !item.work_id && !item.structure_requires_review;
  const [visibility, setVisibility] = useState<"private" | "public" | null>(null);
  const [saving, setSaving] = useState(false);
  const [savingStructure, setSavingStructure] = useState(false);
  const [structureDetail, setStructureDetail] = useState<BookImport | null>(null);
  const [drafts, setDrafts] = useState<StructureDraft[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!item.structure_requires_review) return;
    let active = true;
    apiRequest<BookImport>(`/imports/${item.id}`)
      .then((detail) => {
        if (!active) return;
        setStructureDetail(detail);
        setDrafts(structureDrafts(detail));
      })
      .catch((caught: unknown) => {
        if (active && !(caught instanceof ApiError && caught.status === 401)) {
          setError(caught instanceof ApiError ? caught.message : "无法读取章节结构");
        }
      });
    return () => { active = false; };
  }, [item.id, item.structure_requires_review]);

  const updateDraft = (index: number, patch: Partial<StructureDraft>) => {
    setDrafts((current) => current.map((draft, draftIndex) => (
      draftIndex === index ? { ...draft, ...patch } : draft
    )));
  };

  const mergeWithPrevious = (index: number) => {
    if (index === 0) return;
    setDrafts((current) => current.flatMap((draft, draftIndex) => {
      if (draftIndex === index - 1) {
        return [{
          ...draft,
          segments: [...draft.segments, ...current[index].segments],
        }];
      }
      return draftIndex === index ? [] : [draft];
    }));
  };

  const splitAtHeading = (index: number, blockIndex: number, title: string) => {
    setDrafts((current) => current.flatMap((draft, draftIndex) => {
      if (draftIndex !== index || draft.segments.length !== 1) return [draft];
      const segment = draft.segments[0];
      if (blockIndex <= segment.start_block || blockIndex >= segment.end_block) return [draft];
      return [
        {
          ...draft,
          segments: [{ ...segment, end_block: blockIndex }],
        },
        {
          title,
          parent_path: draft.parent_path,
          segments: [{ ...segment, start_block: blockIndex }],
        },
      ];
    }));
  };

  const saveStructure = async () => {
    setSavingStructure(true);
    setError("");
    try {
      await apiRequest<BookImport>(`/imports/${item.id}/structure`, {
        method: "PUT",
        body: JSON.stringify({ chapters: drafts }),
      });
      await onChanged();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "无法保存章节结构");
    } finally {
      setSavingStructure(false);
    }
  };

  const finalize = async () => {
    if (!visibility) {
      setError("请选择私人档案或公共档案");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await apiRequest<BookImport>(`/imports/${item.id}/finalize`, {
        method: "POST",
        body: JSON.stringify({
          visibility,
          rights_confirmed: visibility === "public",
        }),
      });
      await onChanged();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "无法完成入库");
    } finally {
      setSaving(false);
    }
  };

  return (
    <article className={`import-record status-${item.status}`}>
      <header><div><FileText size={17} /><div><strong>{item.detected_title || item.original_name}</strong><span>{item.source_format.toUpperCase()} · {formatBytes(item.size_bytes)}</span></div></div><span className="import-status">{stageNames[item.stage] ?? item.stage}</span></header>
      <div className="import-progress" aria-label={`解析进度 ${item.progress}%`}><i><b style={{ width: `${item.progress}%` }} /></i><span>{item.progress}%</span></div>
      {active && <p><LoaderCircle className="spin" size={14} />{item.stage === "detecting_metadata" ? "正在根据封面、序章或目录预解析书籍信息" : "正在建立章节结构"}</p>}
      {item.structure_requires_review && <div className="structure-review">
        <div className="structure-review-heading">
          <AlertCircle size={16} />
          <div><strong>请复核章节结构</strong><span>系统发现异常偏长章节。可改名和层级、合并相邻章节，或从内部标题处分拆；保存时会校验正文不丢失、不重复。</span></div>
        </div>
        {item.structure_warnings.length > 0 && <ul>{item.structure_warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
        {!structureDetail && !error && <p><LoaderCircle className="spin" size={14} />正在读取章节结构</p>}
        {structureDetail && <div className="structure-chapter-list">
          {drafts.map((draft, index) => {
            const segment = draft.segments.length === 1 ? draft.segments[0] : null;
            const source = segment
              ? structureDetail.chapters.find((chapter) => chapter.number === segment.source_number)
              : null;
            const headings = (source?.blocks ?? []).flatMap((block, blockIndex) => (
              block.type === "heading" && segment && blockIndex > segment.start_block && blockIndex < segment.end_block
                ? [{ blockIndex, title: block.text || `章节 ${index + 2}` }]
                : []
            ));
            return <div className="structure-chapter-row" key={`${draft.segments.map((part) => `${part.source_number}:${part.start_block}-${part.end_block}`).join("+")}:${index}`}>
              <span>{index + 1}</span>
              <label>章节名<input value={draft.title} onChange={(event) => updateDraft(index, { title: event.target.value })} /></label>
              <label>上级层级<input placeholder="例如：第一部 / 第一卷" value={draft.parent_path.join(" / ")} onChange={(event) => updateDraft(index, { parent_path: event.target.value.split("/").map((part) => part.trim()).filter(Boolean) })} /></label>
              <div className="structure-chapter-actions">
                {index > 0 && <button onClick={() => mergeWithPrevious(index)} type="button">并入上一章</button>}
                {headings.map((heading) => <button key={heading.blockIndex} onClick={() => splitAtHeading(index, heading.blockIndex, heading.title)} type="button">从“{heading.title}”处分拆</button>)}
              </div>
            </div>;
          })}
        </div>}
        {error && <p className="form-error"><AlertCircle size={14} />{error}</p>}
        {structureDetail && <button className="primary-command" disabled={drafts.length === 0 || savingStructure} onClick={() => void saveStructure()} type="button">{savingStructure ? <LoaderCircle className="spin" size={15} /> : <BookCheck size={15} />}{savingStructure ? "正在保存" : "保存结构并继续"}</button>}
      </div>}
      {awaiting && <div className="archive-confirmation">
        <div className="metadata-preview">
          <div className="metadata-preview-heading"><Sparkles size={16} /><div><strong>AI 预解析结果</strong><span>来自文件元数据、封面、序章或目录；无需手动填写</span></div></div>
          <dl>
            <div><dt>书名</dt><dd>{item.detected_title || "未识别"}</dd></div>
            <div><dt>作者</dt><dd>{item.detected_author || "待后续补充"}</dd></div>
            <div><dt>出版社</dt><dd>{item.publisher || "未识别"}</dd></div>
            <div><dt>译者</dt><dd>{item.translator || "未识别"}</dd></div>
            <div><dt>ISBN</dt><dd>{item.isbn || "未识别"}</dd></div>
            <div><dt>标签</dt><dd>{item.detected_tags.join("、") || "未识别"}</dd></div>
          </dl>
        </div>
        <p className="visibility-prompt">选择这本书要放入哪类档案：</p>
        <div className="visibility-options">
          <button className={visibility === "private" ? "active" : ""} onClick={() => { setVisibility("private"); setError(""); }} type="button"><LockKeyhole size={16} /><strong>私人档案</strong><span>只有你能阅读和查看分析</span></button>
          <button className={visibility === "public" ? "active" : ""} onClick={() => { setVisibility("public"); setError(""); }} type="button"><Users size={16} /><strong>公共档案</strong><span>所有人可阅读；选择即确认拥有公开传播授权</span></button>
        </div>
        {error && <p className="form-error"><AlertCircle size={14} />{error}</p>}
        <button className="primary-command" disabled={!visibility || saving} onClick={() => void finalize()} type="button">{saving ? <LoaderCircle className="spin" size={15} /> : <BookCheck size={15} />}{saving ? "正在入库" : "确认入库"}</button>
      </div>}
      {item.work_id && <div className="import-result"><span>{item.chapter_count} 个章节 · {item.visibility === "public" ? "公共档案" : "私人档案"}</span><p>阅读器已经可用，结构化分析将在后台继续。</p><Link className="secondary-command" href={item.visibility === "public" ? "/" : "/?scope=private"}>查看档案</Link></div>}
      {item.status === "failed" && <p className="record-error"><AlertCircle size={14} />{item.error || "无法解析该文件"}</p>}
    </article>
  );
}
