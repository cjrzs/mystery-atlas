"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { ArrowLeft, BookOpenText, LogIn, UserPlus } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { useAuth } from "@/components/auth-provider";
import { ApiError } from "@/lib/api";

type Mode = "login" | "register";

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="site-shell"><AppHeader /><main className="access-gate"><span className="account-loading" /></main></div>}>
      <LoginContent />
    </Suspense>
  );
}

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading, login, register } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const nextPath = searchParams.get("next");
  const destination = nextPath?.startsWith("/") && !nextPath.startsWith("//")
    ? nextPath
    : "/library/import";

  useEffect(() => {
    if (!loading && user) router.replace(destination);
  }, [destination, loading, router, user]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      if (mode === "login") {
        await login({ email, password });
      } else {
        await register({ email, password, display_name: displayName });
      }
      router.replace(destination);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "无法连接服务器，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="site-shell">
      <AppHeader />
      <main className="auth-page">
        <section className="auth-tool" aria-labelledby="auth-title">
          <header>
            <Link href="/" className="icon-button" aria-label="返回公共档案"><ArrowLeft size={18} /></Link>
            <span className="auth-mark"><BookOpenText size={22} /></span>
            <div><p className="eyebrow">MYSTERY ATLAS ACCOUNT</p><h1 id="auth-title">{mode === "login" ? "登录谜案经纬" : "创建读者账户"}</h1></div>
          </header>

          <div className="mode-tabs" role="tablist" aria-label="账户操作">
            <button className={mode === "login" ? "active" : ""} onClick={() => { setMode("login"); setError(""); }} type="button" role="tab">登录</button>
            <button className={mode === "register" ? "active" : ""} onClick={() => { setMode("register"); setError(""); }} type="button" role="tab">注册</button>
          </div>

          <form className="auth-form" onSubmit={submit}>
            {mode === "register" && (
              <label><span>显示名称</span><input autoComplete="name" required maxLength={120} value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="用于站内显示" /></label>
            )}
            <label><span>邮箱</span><input autoComplete="email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="reader@example.com" /></label>
            <label><span>密码</span><input autoComplete={mode === "login" ? "current-password" : "new-password"} required minLength={8} maxLength={128} type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="至少 8 位" /></label>
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="primary-command auth-submit" disabled={submitting} type="submit">
              {mode === "login" ? <LogIn size={16} /> : <UserPlus size={16} />}
              {submitting ? "正在提交" : mode === "login" ? "登录" : "创建账户"}
            </button>
          </form>
        </section>
      </main>
    </div>
  );
}
