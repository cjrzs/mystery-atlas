"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpenText, BookUp, Search, ShieldCheck } from "lucide-react";
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
        <Link className={pathname.startsWith("/library") ? "nav-link active" : "nav-link"} href="/library/import"><BookUp size={15} />私人书库</Link>
        {user?.role === "admin" && <Link className={pathname.startsWith("/admin") ? "nav-link active" : "nav-link"} href="/admin/review"><ShieldCheck size={15} />审核台</Link>}
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
