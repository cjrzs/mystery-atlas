import Link from "next/link";
import { BookOpenText, Search, ShieldCheck } from "lucide-react";

export function AppHeader() {
  return (
    <header className="app-header">
      <Link className="brand" href="/" aria-label="谜案经纬首页">
        <span className="brand-mark"><BookOpenText size={18} /></span>
        <span>谜案经纬</span>
      </Link>
      <nav className="primary-nav" aria-label="主导航">
        <Link className="nav-link active" href="/">档案库</Link>
        <Link className="nav-link" href="/admin/review"><ShieldCheck size={15} />审核台</Link>
      </nav>
      <button className="global-search" type="button" aria-label="搜索全部档案">
        <Search size={16} />
        <span>搜索作品、人物、线索</span>
        <kbd>Ctrl K</kbd>
      </button>
      <button className="user-chip" type="button" aria-label="登录账户">登</button>
    </header>
  );
}
