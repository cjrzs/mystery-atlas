"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  BookMarked,
  BookOpenText,
  BookUp,
  Filter,
  LogIn,
  Search,
  Users,
  Wrench,
} from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { archiveWorks as demoWorks } from "@/lib/demo-data";
import { apiRequest, type ArchiveWork, type LibraryItem } from "@/lib/api";

type Scope = "public" | "private";
const filters = ["全部", "本格", "密室", "叙述性诡计", "时间诡计"];

const fallbackWorks: ArchiveWork[] = demoWorks.map((work) => ({
  id: null,
  slug: work.slug,
  title: work.title,
  author: work.author,
  region: work.region,
  year: Number(work.year),
  tags: work.tags,
  cases: work.cases,
  people: work.people,
  clues: work.clues,
  analysis_progress: work.progress,
  status: work.progress === 100 ? "可用" : "分析中",
  visibility: "public",
  edition_count: 1,
  unresolved_feedback_count: 0,
  maintainer_name: "演示档案",
  updated_at: null,
}));

function formatStatus(status: string): string {
  const names: Record<string, string> = {
    published: "可用",
    analyzing: "分析中",
    unavailable: "暂无版本",
    draft: "准备中",
  };
  return names[status] ?? status;
}

export function ArchiveBrowser({ initialScope = "public" }: { initialScope?: Scope }) {
  const { user, loading } = useAuth();
  const [scope, setScope] = useState<Scope>(initialScope);
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState("全部");
  const [publicWorks, setPublicWorks] = useState<ArchiveWork[]>(fallbackWorks);
  const [privateItems, setPrivateItems] = useState<LibraryItem[]>([]);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let active = true;
    apiRequest<ArchiveWork[]>("/works")
      .then((items) => { if (active) setPublicWorks(items); })
      .catch(() => { if (active) setLoadError("公共档案服务暂时不可用，当前显示演示数据"); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!user) return;
    let active = true;
    apiRequest<LibraryItem[]>("/library")
      .then((items) => { if (active) setPrivateItems(items); })
      .catch(() => { if (active) setLoadError("读取私人档案失败"); });
    return () => { active = false; };
  }, [user]);

  const works = useMemo(() => publicWorks.filter((work) => {
    const text = `${work.title}${work.author}${work.tags.join("")}`.toLowerCase();
    return text.includes(query.toLowerCase())
      && (activeFilter === "全部" || work.tags.includes(activeFilter));
  }), [activeFilter, publicWorks, query]);

  const personal = useMemo(() => privateItems.filter((item) => (
    `${item.title}${item.author}`.toLowerCase().includes(query.toLowerCase())
  )), [privateItems, query]);

  return (
    <main className="archive-page">
      <section className="archive-heading">
        <div>
          <p className="eyebrow">MYSTERY ARCHIVE</p>
          <h1>档案库</h1>
          <p className="archive-description">阅读原文，同时追踪人物、案件、关系与线索。</p>
        </div>
        <div className="archive-stats" aria-label="档案统计">
          <div><strong>{publicWorks.length}</strong><span>公共作品</span></div>
          <div><strong>{user ? privateItems.length : "—"}</strong><span>私人记录</span></div>
          <div><strong>{publicWorks.reduce((sum, item) => sum + item.clues, 0)}</strong><span>线索条目</span></div>
        </div>
      </section>

      <section className="archive-tools" aria-label="档案筛选">
        <div className="archive-scope-tabs" role="tablist" aria-label="档案范围">
          <button className={scope === "public" ? "active" : ""} onClick={() => setScope("public")} type="button" role="tab"><BookOpenText size={16} />公共档案</button>
          <button className={scope === "private" ? "active" : ""} onClick={() => setScope("private")} type="button" role="tab"><BookMarked size={16} />私人档案</button>
          {user && <Link className="secondary-command archive-upload-link" href="/library/import"><BookUp size={15} />上传书籍</Link>}
        </div>
        <label className="archive-search">
          <Search size={18} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索书名、作者、人物或诡计" />
        </label>
        {scope === "public" && <div className="filter-row">
          <Filter size={16} />
          {filters.map((filter) => (
            <button key={filter} className={filter === activeFilter ? "filter-chip active" : "filter-chip"} onClick={() => setActiveFilter(filter)} type="button">
              {filter}
            </button>
          ))}
        </div>}
        {loadError && <p className="archive-inline-note">{loadError}</p>}
      </section>

      {scope === "public" ? (
        <section className="archive-list" aria-label="公共作品列表">
          <div className="list-heading">
            <span>作品</span><span>档案规模</span><span>分析进度</span><span>维护状态</span><span aria-hidden="true" />
          </div>
          {works.map((work, index) => (
            <Link href={`/works/${work.slug}`} className="archive-row" key={work.slug}>
              <div className="work-identity">
                <div className={`book-cover cover-${["teal", "red", "blue", "yellow"][index % 4]}`} aria-hidden="true"><span>{work.title.slice(0, 1)}</span><i /></div>
                <div>
                  <h2>{work.title}</h2>
                  <p>{work.author}{work.region ? ` · ${work.region}` : ""}{work.year ? ` · ${work.year}` : ""} · {work.edition_count} 个版本</p>
                  <div className="tag-line">{work.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
                </div>
              </div>
              <div className="scale-cell">
                <span><BookMarked size={15} />{work.cases} 案</span>
                <span><Users size={15} />{work.people} 人</span>
                <span>{work.clues} 条线索</span>
              </div>
              <div className="progress-cell">
                <div><span>结构化分析</span><strong>{work.analysis_progress}%</strong></div>
                <div className="progress-track"><i style={{ width: `${work.analysis_progress}%` }} /></div>
              </div>
              <div className="archive-maintainer">
                <strong>{formatStatus(work.status)}</strong>
                <small><Wrench size={12} />{work.maintainer_name || "待接管"}</small>
                <small>{work.unresolved_feedback_count} 条待处理反馈</small>
              </div>
              <ArrowUpRight className="row-arrow" size={19} />
            </Link>
          ))}
          {works.length === 0 && <div className="empty-state">没有找到匹配的公共档案。</div>}
        </section>
      ) : loading ? (
        <div className="empty-state">正在读取私人档案…</div>
      ) : !user ? (
        <section className="private-access-card"><LogIn size={24} /><h2>登录后查看私人档案</h2><p>保存阅读进度、私人批注和自己上传的书籍。</p><Link className="primary-command" href="/login"><LogIn size={15} />登录或注册</Link></section>
      ) : (
        <section className="archive-list private-archive-list" aria-label="私人档案列表">
          <div className="list-heading"><span>继续阅读</span><span>来源</span><span>阅读进度</span><span>状态</span><span aria-hidden="true" /></div>
          {personal.map((item, index) => (
            <Link href={item.kind === "private_upload" ? `/library/${item.id}` : `/works/${item.work_slug}`} className="archive-row" key={item.id}>
              <div className="work-identity"><div className={`book-cover cover-${["blue", "teal", "yellow"][index % 3]}`} aria-hidden="true"><span>{item.title.slice(0, 1)}</span><i /></div><div><h2>{item.title}</h2><p>{item.author}</p></div></div>
              <div className="scale-cell"><span>{item.kind === "private_upload" ? "私密上传" : item.kind === "public_owner" ? "我维护的公共档案" : "公共阅读记录"}</span></div>
              <div className="progress-cell"><div><span>第 {item.current_chapter} 章</span><strong>{Math.round(item.progress * 100)}%</strong></div><div className="progress-track"><i style={{ width: `${item.progress * 100}%` }} /></div></div>
              <div className="archive-maintainer"><strong>{item.visibility === "public" ? "公共" : "私人"}</strong><small>分析 {item.analysis_progress}%</small></div>
              <ArrowUpRight className="row-arrow" size={19} />
            </Link>
          ))}
          {personal.length === 0 && <div className="empty-state"><p>还没有私人档案。</p><Link className="secondary-command" href="/library/import"><BookUp size={15} />上传第一本书</Link></div>}
        </section>
      )}
    </main>
  );
}
