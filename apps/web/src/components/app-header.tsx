"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpenText, MessageSquareText, Search, Wrench } from "lucide-react";
import { AccountButton, useAuth } from "@/components/auth-provider";

export function AppHeader() {
  const pathname = usePathname();
  const { user } = useAuth();
  return (
    <header className="app-header">
      <Link className="brand" href="/" aria-label="谜案经纬首页">
        <span className="brand-mark"><BookOpenText size={18} /></span>
        <span>谜案经纬</span>
      </Link>
      <nav className="primary-nav" aria-label="主导航">
        <Link className={pathname === "/" ? "nav-link active" : "nav-link"} href="/">档案库</Link>
        {user && <Link className={pathname.startsWith("/maintenance") ? "nav-link active" : "nav-link"} href="/maintenance"><Wrench size={15} />维护中心</Link>}
        {user && <Link className={pathname.startsWith("/feedback") ? "nav-link active" : "nav-link"} href="/feedback"><MessageSquareText size={15} />反馈</Link>}
      </nav>
      <button className="global-search" type="button" aria-label="搜索全部档案">
        <Search size={16} />
        <span>搜索作品、人物、线索</span>
        <kbd>Ctrl K</kbd>
      </button>
      <AccountButton />
    </header>
  );
}
