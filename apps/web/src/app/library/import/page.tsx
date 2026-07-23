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
  Upload,
  Users,
  X,
} from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiRequest, type BookImport } from "@/lib/api";

const stageNames: Record<string, string> = {
  waiting: "等待解析",
  extracting_text: "提取正文",
  detecting_chapters: "识别章节",
  awaiting_confirmation: "等待确认档案信息",
  ready_for_analysis: "已进入档案库",
  failed: "解析失败",
};

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function ImportPage() {
  const { user, loading } = useAuth();
  const fileInput = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [imports, setImports] = useState<BookImport[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");

  const refreshImports = useCallback(async () => {
    if (!user) return;
    try {
      setImports(await apiRequest<BookImport[]>("/imports"));
    } catch (caught) {
      if (!(caught instanceof ApiError && caught.status === 401)) {
        setError(caught instanceof ApiError ? caught.message : "读取上传记录失败");
      }
    }
  }, [user]);

  useEffect(() => {
    if (!user) return;
    let active = true;
    apiRequest<BookImport[]>("/imports")
      .then((items) => { if (active) setImports(items); })
      .catch((caught: unknown) => {
        if (active && !(caught instanceof ApiError && caught.status === 401)) {
          setError(caught instanceof ApiError ? caught.message : "读取上传记录失败");
        }
      });
    return () => { active = false; };
  }, [user]);

  useEffect(() => {
    if (!imports.some((item) => item.status === "queued" || item.status === "parsing")) return;
    const timer = window.setInterval(() => void refreshImports(), 1500);
    return () => window.clearInterval(timer);
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
          <div><p className="eyebrow">ARCHIVE IMPORT</p><h1>上传书籍</h1><p>{user.display_name} · 先解析，再确认档案信息与公开范围</p></div>
          <button className="secondary-command" onClick={() => void refreshImports()} type="button"><RotateCw size={15} />刷新</button>
        </header>

        <section className="import-workspace">
          <div className="upload-panel">
            <div className="section-title"><Upload size={17} /><div><strong>第一步：选择文件</strong><span>EPUB / TXT / PDF，最大 50 MB</span></div></div>
            <input ref={fileInput} className="visually-hidden" accept=".epub,.txt,.pdf" onChange={handleFileInput} type="file" />
            <div className={dragging ? "file-dropzone dragging" : "file-dropzone"} onDragEnter={(event) => { event.preventDefault(); setDragging(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={handleDrop}>
              <BookOpenText size={28} /><strong>拖入小说文件</strong><span>系统会先提取章节和基本信息</span><button className="secondary-command" onClick={() => fileInput.current?.click()} type="button"><FileText size={15} />选择文件</button>
            </div>
            {selectedFile && <div className="selected-file"><FileText size={18} /><div><strong>{selectedFile.name}</strong><span>{formatBytes(selectedFile.size)}</span></div><button className="icon-button compact" onClick={() => setSelectedFile(null)} type="button" title="移除文件"><X size={16} /></button></div>}
            {error && <p className="form-error" role="alert"><AlertCircle size={15} />{error}</p>}
            <button className="primary-command upload-command" disabled={!selectedFile || uploading} onClick={() => void upload()} type="button">{uploading ? <LoaderCircle className="spin" size={16} /> : <Upload size={16} />}{uploading ? "正在上传" : "上传并提取信息"}</button>
          </div>

          <div className="import-history">
            <div className="section-title"><BookCheck size={17} /><div><strong>第二步：确认并入库</strong><span>{imports.length} 条上传记录</span></div></div>
            {imports.length === 0 ? <div className="empty-imports"><BookOpenText size={24} /><p>还没有上传记录</p></div> : <div className="import-list">{imports.map((item) => <ImportRecord key={item.id} item={item} onChanged={refreshImports} />)}</div>}
          </div>
        </section>
      </main>
    </div>
  );
}

function ImportRecord({ item, onChanged }: { item: BookImport; onChanged: () => Promise<void> }) {
  const active = item.status === "queued" || item.status === "parsing";
  const awaiting = item.status === "completed" && !item.work_id;
  const [title, setTitle] = useState(item.detected_title || item.original_name.replace(/\.[^.]+$/, ""));
  const [author, setAuthor] = useState(item.detected_author || "");
  const [publisher, setPublisher] = useState(item.publisher || "");
  const [translator, setTranslator] = useState(item.translator || "");
  const [isbn, setIsbn] = useState(item.isbn || "");
  const [visibility, setVisibility] = useState<"private" | "public">("private");
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const finalize = async () => {
    if (!title.trim() || !author.trim()) {
      setError("请填写书名和作者");
      return;
    }
    if (visibility === "public" && !rightsConfirmed) {
      setError("公开上传前必须确认拥有公开传播授权");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await apiRequest<BookImport>(`/imports/${item.id}/finalize`, {
        method: "POST",
        body: JSON.stringify({ title, author, publisher: publisher || null, translator: translator || null, isbn: isbn || null, visibility, rights_confirmed: rightsConfirmed }),
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
      {active && <p><LoaderCircle className="spin" size={14} />正在建立章节结构</p>}
      {awaiting && <div className="archive-confirmation">
        <div className="metadata-grid">
          <label><span>书名</span><input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
          <label><span>作者</span><input value={author} onChange={(event) => setAuthor(event.target.value)} placeholder="必填" /></label>
          <label><span>出版社</span><input value={publisher} onChange={(event) => setPublisher(event.target.value)} /></label>
          <label><span>译者</span><input value={translator} onChange={(event) => setTranslator(event.target.value)} /></label>
          <label><span>ISBN</span><input value={isbn} onChange={(event) => setIsbn(event.target.value)} /></label>
        </div>
        <div className="visibility-options">
          <button className={visibility === "private" ? "active" : ""} onClick={() => setVisibility("private")} type="button"><LockKeyhole size={16} /><strong>私人档案</strong><span>只有你能阅读和查看分析</span></button>
          <button className={visibility === "public" ? "active" : ""} onClick={() => setVisibility("public")} type="button"><Users size={16} /><strong>公共档案</strong><span>所有人可阅读，你负责维护</span></button>
        </div>
        {visibility === "public" && <label className="rights-confirm"><input checked={rightsConfirmed} onChange={(event) => setRightsConfirmed(event.target.checked)} type="checkbox" /><span>我确认拥有该版本的公开传播授权，或该作品允许公开传播。</span></label>}
        {error && <p className="form-error"><AlertCircle size={14} />{error}</p>}
        <button className="primary-command" disabled={saving} onClick={() => void finalize()} type="button">{saving ? <LoaderCircle className="spin" size={15} /> : <BookCheck size={15} />}{saving ? "正在入库" : "确认并进入档案库"}</button>
      </div>}
      {item.work_id && <div className="import-result"><span>{item.chapter_count} 个章节 · {item.visibility === "public" ? "公共档案" : "私人档案"}</span><p>阅读器已经可用，结构化分析将在后台继续。</p><Link className="secondary-command" href={item.visibility === "public" ? "/" : "/?scope=private"}>查看档案</Link></div>}
      {item.status === "failed" && <p className="record-error"><AlertCircle size={14} />{item.error || "无法解析该文件"}</p>}
    </article>
  );
}
