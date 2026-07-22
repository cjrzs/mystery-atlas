"use client";

import Link from "next/link";
import { ChangeEvent, DragEvent, useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, BookCheck, BookOpenText, FileText, LoaderCircle, LogIn, RotateCw, Upload, X } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiRequest, BookImport } from "@/lib/api";

const stageNames: Record<string, string> = {
  waiting: "等待解析",
  extracting_text: "提取正文",
  detecting_chapters: "识别章节",
  ready_for_analysis: "解析完成",
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
        setError(caught instanceof ApiError ? caught.message : "读取导入记录失败");
      }
    }
  }, [user]);

  useEffect(() => {
    if (!user) return;
    let active = true;
    apiRequest<BookImport[]>("/imports")
      .then((records) => { if (active) setImports(records); })
      .catch((caught: unknown) => {
        if (active && !(caught instanceof ApiError && caught.status === 401)) {
          setError(caught instanceof ApiError ? caught.message : "读取导入记录失败");
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
    return <div className="site-shell"><AppHeader /><main className="access-gate"><span className="account-loading" /><p>正在读取私人书库</p></main></div>;
  }

  if (!user) {
    return (
      <div className="site-shell"><AppHeader /><main className="access-gate">
        <LogIn size={24} /><h1>登录后导入书籍</h1><p>上传文件和解析结果只属于你的账户。</p>
        <Link className="primary-command" href="/login?next=/library/import">登录或注册</Link>
      </main></div>
    );
  }

  return (
    <div className="site-shell">
      <AppHeader />
      <main className="library-page">
        <header className="library-heading">
          <div><p className="eyebrow">PRIVATE LIBRARY</p><h1>私人书库</h1><p>{user.display_name} · {user.email}</p></div>
          <button className="secondary-command" onClick={() => void refreshImports()} type="button"><RotateCw size={15} />刷新</button>
        </header>

        <section className="import-workspace">
          <div className="upload-panel">
            <div className="section-title"><Upload size={17} /><div><strong>导入小说</strong><span>EPUB / TXT / PDF，最大 50 MB</span></div></div>
            <input ref={fileInput} className="visually-hidden" accept=".epub,.txt,.pdf" onChange={handleFileInput} type="file" />
            <div
              className={dragging ? "file-dropzone dragging" : "file-dropzone"}
              onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
            >
              <BookOpenText size={28} />
              <strong>拖入小说文件</strong>
              <span>或从本机选择一个文件</span>
              <button className="secondary-command" onClick={() => fileInput.current?.click()} type="button"><FileText size={15} />选择文件</button>
            </div>

            {selectedFile && <div className="selected-file"><FileText size={18} /><div><strong>{selectedFile.name}</strong><span>{formatBytes(selectedFile.size)}</span></div><button className="icon-button compact" onClick={() => setSelectedFile(null)} type="button" title="移除文件"><X size={16} /></button></div>}
            {error && <p className="form-error" role="alert"><AlertCircle size={15} />{error}</p>}
            <button className="primary-command upload-command" disabled={!selectedFile || uploading} onClick={() => void upload()} type="button">
              {uploading ? <LoaderCircle className="spin" size={16} /> : <Upload size={16} />}{uploading ? "正在上传" : "上传并解析"}
            </button>
          </div>

          <div className="import-history">
            <div className="section-title"><BookCheck size={17} /><div><strong>解析记录</strong><span>{imports.length} 本书</span></div></div>
            {imports.length === 0 ? <div className="empty-imports"><BookOpenText size={24} /><p>还没有导入记录</p></div> : (
              <div className="import-list">{imports.map((item) => <ImportRecord key={item.id} item={item} />)}</div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function ImportRecord({ item }: { item: BookImport }) {
  const active = item.status === "queued" || item.status === "parsing";
  return (
    <article className={`import-record status-${item.status}`}>
      <header><div><FileText size={17} /><div><strong>{item.detected_title || item.original_name}</strong><span>{item.source_format.toUpperCase()} · {formatBytes(item.size_bytes)}</span></div></div><span className="import-status">{stageNames[item.stage] ?? item.stage}</span></header>
      <div className="import-progress" aria-label={`解析进度 ${item.progress}%`}><i><b style={{ width: `${item.progress}%` }} /></i><span>{item.progress}%</span></div>
      {active && <p><LoaderCircle className="spin" size={14} />正在建立章节结构</p>}
      {item.status === "completed" && <div className="import-result"><span>{item.chapter_count} 个章节</span>{item.preview && <p>{item.preview}</p>}</div>}
      {item.status === "failed" && <p className="record-error"><AlertCircle size={14} />{item.error || "无法解析该文件"}</p>}
    </article>
  );
}
