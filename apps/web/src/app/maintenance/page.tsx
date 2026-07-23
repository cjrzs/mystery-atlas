"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  BookOpenText,
  CheckCircle2,
  CircleDot,
  History,
  LoaderCircle,
  LogIn,
  MessageSquareText,
  RotateCw,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { useAuth } from "@/components/auth-provider";
import { apiRequest, type ArchiveFeedback, type MaintenanceOverview } from "@/lib/api";

export default function MaintenancePage() {
  const { user, loading } = useAuth();
  const [overview, setOverview] = useState<MaintenanceOverview | null>(null);
  const [feedback, setFeedback] = useState<ArchiveFeedback[]>([]);
  const [selected, setSelected] = useState<ArchiveFeedback | null>(null);
  const [resolution, setResolution] = useState("");
  const [changeSummary, setChangeSummary] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!user) return;
    try {
      const [nextOverview, nextFeedback] = await Promise.all([
        apiRequest<MaintenanceOverview>("/maintenance/overview"),
        apiRequest<ArchiveFeedback[]>("/maintenance/feedback"),
      ]);
      setOverview(nextOverview);
      setFeedback(nextFeedback);
      setSelected((current) => current ? nextFeedback.find((item) => item.id === current.id) ?? null : nextFeedback[0] ?? null);
      setError("");
    } catch {
      setError("读取维护任务失败");
    }
  }, [user]);

  useEffect(() => {
    if (!user) return;
    let active = true;
    Promise.all([
      apiRequest<MaintenanceOverview>("/maintenance/overview"),
      apiRequest<ArchiveFeedback[]>("/maintenance/feedback"),
    ]).then(([nextOverview, nextFeedback]) => {
      if (!active) return;
      setOverview(nextOverview);
      setFeedback(nextFeedback);
      setSelected(nextFeedback[0] ?? null);
    }).catch(() => { if (active) setError("读取维护任务失败"); });
    return () => { active = false; };
  }, [user]);

  const resolve = async (status: "resolved" | "closed" | "duplicate") => {
    if (!selected) return;
    setSaving(true);
    try {
      await apiRequest(`/maintenance/feedback/${selected.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status, resolution, change_summary: changeSummary }),
      });
      setResolution("");
      setChangeSummary("");
      await refresh();
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="site-shell"><AppHeader /><main className="access-gate"><span className="account-loading" /></main></div>;
  if (!user) return <div className="site-shell"><AppHeader /><main className="access-gate"><LogIn size={24} /><h1>登录后维护档案</h1><p>上传者负责处理自己作品和版本的反馈。</p><Link className="primary-command" href="/login?next=/maintenance">登录</Link></main></div>;

  return <div className="site-shell"><AppHeader /><main className="maintenance-page">
    <header className="maintenance-heading"><div><p className="eyebrow">ARCHIVE MAINTENANCE</p><h1>档案维护中心</h1><p>直接修正内容并保留版本记录，不设发布前审核。</p></div><button className="secondary-command" onClick={() => void refresh()} type="button"><RotateCw size={15} />刷新</button></header>
    {error && <p className="form-error"><AlertCircle size={15} />{error}</p>}
    <section className="maintenance-stats">
      <article><BookOpenText size={18} /><strong>{overview?.works.length ?? 0}</strong><span>维护作品</span></article>
      <article><Wrench size={18} /><strong>{overview?.editions.length ?? 0}</strong><span>维护版本</span></article>
      <article><MessageSquareText size={18} /><strong>{overview?.open_feedback ?? 0}</strong><span>待处理反馈</span></article>
      {overview?.is_super_admin && <article><ShieldCheck size={18} /><strong>全局</strong><span>超级管理员</span></article>}
    </section>
    <section className="maintenance-grid">
      <aside className="maintenance-queue">
        <div className="section-title"><CircleDot size={17} /><div><strong>反馈队列</strong><span>公开问题单</span></div></div>
        {feedback.map((item) => <button className={selected?.id === item.id ? "active" : ""} key={item.id} onClick={() => { setSelected(item); setResolution(item.resolution); setChangeSummary(""); }} type="button"><span>{item.status === "open" ? <CircleDot size={14} /> : <CheckCircle2 size={14} />}{item.entity_type} · {item.chapter ? `第 ${item.chapter} 章` : "全局"}</span><strong>{item.content}</strong><small>{item.same_issue_count} 人遇到 · {item.reporter_name}</small></button>)}
        {feedback.length === 0 && <div className="empty-state">暂时没有反馈任务。</div>}
      </aside>
      <section className="maintenance-editor">
        {!selected ? <div className="empty-state">选择一条反馈开始处理。</div> : <>
          <header><div><p className="eyebrow">FEEDBACK ISSUE</p><h2>{selected.entity_type}反馈</h2></div><span className={`feedback-state state-${selected.status}`}>{selected.status}</span></header>
          <blockquote>{selected.content}</blockquote>
          <dl><div><dt>反馈者</dt><dd>{selected.reporter_name}</dd></div><div><dt>处理人</dt><dd>{selected.assignee_name}</dd></div><div><dt>范围</dt><dd>{selected.chapter ? `第 ${selected.chapter} 章以内` : "全局"}</dd></div></dl>
          <label><span>处理说明</span><textarea value={resolution} onChange={(event) => setResolution(event.target.value)} placeholder="说明如何修复，或为什么关闭" /></label>
          <label><span>档案修改摘要</span><input value={changeSummary} onChange={(event) => setChangeSummary(event.target.value)} placeholder="填写后会生成新的版本记录" /></label>
          <div className="maintenance-actions"><button disabled={saving} onClick={() => void resolve("duplicate")} type="button">标记重复</button><button disabled={saving} onClick={() => void resolve("closed")} type="button">说明后关闭</button><button className="primary-command" disabled={saving || !resolution.trim()} onClick={() => void resolve("resolved")} type="button">{saving ? <LoaderCircle className="spin" size={15} /> : <CheckCircle2 size={15} />}修正并完成</button></div>
          {selected.resolution && <div className="revision-note"><History size={15} /><span>{selected.resolution}</span></div>}
        </>}
      </section>
    </section>
  </main></div>;
}
