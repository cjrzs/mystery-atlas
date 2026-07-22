"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowUpRight, BookMarked, CheckCircle2, Filter, Search, Users } from "lucide-react";
import { archiveWorks } from "@/lib/demo-data";

const filters = ["全部", "本格", "密室", "叙述性诡计", "时间诡计"];

export function ArchiveBrowser() {
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState("全部");

  const works = useMemo(() => archiveWorks.filter((work) => {
    const matchesQuery = `${work.title}${work.author}${work.subtitle}${work.tags.join("")}`.toLowerCase().includes(query.toLowerCase());
    const matchesFilter = activeFilter === "全部" || work.tags.includes(activeFilter);
    return matchesQuery && matchesFilter;
  }), [activeFilter, query]);

  return (
    <main className="archive-page">
      <section className="archive-heading">
        <div>
          <p className="eyebrow">PUBLIC CASE ARCHIVE</p>
          <h1>公共案件档案库</h1>
          <p>由 AI 整理、管理员逐条核验的推理小说结构化档案。</p>
        </div>
        <div className="archive-stats" aria-label="档案统计">
          <div><strong>128</strong><span>已收录作品</span></div>
          <div><strong>2,416</strong><span>人物档案</span></div>
          <div><strong>7,903</strong><span>证据条目</span></div>
        </div>
      </section>

      <section className="archive-tools" aria-label="档案筛选">
        <label className="archive-search">
          <Search size={18} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索书名、作者、人物或诡计" />
        </label>
        <div className="filter-row">
          <Filter size={16} />
          {filters.map((filter) => (
            <button key={filter} className={filter === activeFilter ? "filter-chip active" : "filter-chip"} onClick={() => setActiveFilter(filter)} type="button">
              {filter}
            </button>
          ))}
        </div>
      </section>

      <section className="archive-list" aria-label="作品列表">
        <div className="list-heading">
          <span>作品</span><span>档案规模</span><span>核验进度</span><span>状态</span><span aria-hidden="true" />
        </div>
        {works.map((work) => (
          <Link href={`/works/${work.slug}`} className="archive-row" key={work.slug}>
            <div className="work-identity">
              <div className={`book-cover cover-${work.cover}`} aria-hidden="true">
                <span>{work.title.slice(0, 1)}</span>
                <i />
              </div>
              <div>
                <h2>{work.title}</h2>
                <p>{work.author} · {work.region} · {work.year}</p>
                <div className="tag-line">{work.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
              </div>
            </div>
            <div className="scale-cell">
              <span><BookMarked size={15} />{work.cases} 案</span>
              <span><Users size={15} />{work.people} 人</span>
              <span>{work.clues} 条线索</span>
            </div>
            <div className="progress-cell">
              <div><span>结构化分析</span><strong>{work.progress}%</strong></div>
              <div className="progress-track"><i style={{ width: `${work.progress}%` }} /></div>
            </div>
            <div className={`status-label status-${work.status}`}>
              {work.status === "已核验" && <CheckCircle2 size={14} />}{work.status}
              <small>{work.updatedAt}</small>
            </div>
            <ArrowUpRight className="row-arrow" size={19} />
          </Link>
        ))}
        {works.length === 0 && <div className="empty-state">没有找到匹配的公共档案。</div>}
      </section>
    </main>
  );
}

