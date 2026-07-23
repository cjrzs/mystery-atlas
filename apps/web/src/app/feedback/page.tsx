"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AlertCircle, CheckCircle2, LogIn, MessageSquareText, Send, Users } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { useAuth } from "@/components/auth-provider";
import { apiRequest, type ArchiveFeedback } from "@/lib/api";

export default function FeedbackPage() {
  return <Suspense fallback={<div className="site-shell"><AppHeader /><main className="access-gate"><span className="account-loading" /></main></div>}><FeedbackContent /></Suspense>;
}

function FeedbackContent() {
  const { user, loading } = useAuth();
  const params = useSearchParams();
  const workId = params.get("work_id");
  const editionId = params.get("edition_id");
  const initialChapter = Number(params.get("chapter") || 0) || null;
  const [category, setCategory] = useState(workId ? "content" : "system");
  const [entityType, setEntityType] = useState(workId ? "work" : "interface");
  const [chapter, setChapter] = useState(initialChapter?.toString() ?? "");
  const [content, setContent] = useState("");
  const [existing, setExisting] = useState<ArchiveFeedback[]>([]);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const query = workId ? `?work_id=${workId}${chapter ? `&through_chapter=${chapter}` : ""}` : "";
    apiRequest<ArchiveFeedback[]>(`/feedback${query}`).then(setExisting).catch(() => setExisting([]));
  }, [chapter, workId]);

  const submit = async () => {
    if (content.trim().length < 3) {
      setError("请具体描述问题");
      return;
    }
    try {
      await apiRequest("/feedback", { method: "POST", body: JSON.stringify({ work_id: workId, edition_id: editionId, entity_type: entityType, category, chapter: chapter ? Number(chapter) : null, content }) });
      setContent("");
      setSent(true);
      setError("");
    } catch {
      setError("反馈提交失败，请稍后重试");
    }
  };

  if (loading) return <div className="site-shell"><AppHeader /><main className="access-gate"><span className="account-loading" /></main></div>;
  if (!user) return <div className="site-shell"><AppHeader /><main className="access-gate"><LogIn size={24} /><h1>登录后提交反馈</h1><p>公开反馈会进入对应维护者的问题队列。</p><Link className="primary-command" href="/login?next=/feedback">登录</Link></main></div>;

  return <div className="site-shell"><AppHeader /><main className="feedback-page">
    <header><p className="eyebrow">PUBLIC FEEDBACK</p><h1>{workId ? "反馈档案内容" : "反馈网站问题"}</h1><p>反馈会公开展示，请不要写出当前章节之后的剧情或最终答案。</p></header>
    <section className="feedback-layout">
      <div className="feedback-form">
        <div className="feedback-fields"><label><span>反馈类型</span><select value={category} onChange={(event) => setCategory(event.target.value)}><option value="content">内容错误</option><option value="version">版本或正文</option><option value="system">界面与功能</option></select></label><label><span>反馈对象</span><select value={entityType} onChange={(event) => setEntityType(event.target.value)}><option value="work">作品</option><option value="person">人物</option><option value="relation">关系</option><option value="case">案件</option><option value="clue">线索</option><option value="interface">界面</option></select></label><label><span>涉及章节</span><input min="1" type="number" value={chapter} onChange={(event) => setChapter(event.target.value)} placeholder="无剧透可留空" /></label></div>
        <label className="feedback-copy"><span>问题描述</span><textarea value={content} onChange={(event) => { setContent(event.target.value); setSent(false); }} placeholder="说明哪里有问题，并尽量提供证据位置。不要包含后续剧情。" /></label>
        {error && <p className="form-error"><AlertCircle size={14} />{error}</p>}{sent && <p className="form-success"><CheckCircle2 size={14} />反馈已提交给维护者</p>}
        <button className="primary-command" onClick={() => void submit()} type="button"><Send size={15} />提交公开反馈</button>
      </div>
      <aside className="similar-feedback"><div className="section-title"><MessageSquareText size={17} /><div><strong>已有相似反馈</strong><span>提交前请先查看</span></div></div>{existing.slice(0, 8).map((item) => <article key={item.id}><header><span>{item.entity_type} · {item.chapter ? `第 ${item.chapter} 章` : "全局"}</span><small>{item.status}</small></header><p>{item.content}</p><button onClick={() => void apiRequest(`/feedback/${item.id}/same`, { method: "POST" }).then(() => setExisting((current) => current.map((entry) => entry.id === item.id ? { ...entry, same_issue_count: entry.same_issue_count + 1 } : entry)))} type="button"><Users size={13} />我也遇到 · {item.same_issue_count}</button></article>)}{existing.length === 0 && <div className="empty-state">没有相似反馈。</div>}</aside>
    </section>
  </main></div>;
}
