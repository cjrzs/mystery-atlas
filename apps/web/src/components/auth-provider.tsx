"use client";

import Link from "next/link";
import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { BookUp, LogOut, ShieldCheck, UserRound } from "lucide-react";
import { apiRequest, CurrentUser } from "@/lib/api";

type Credentials = { email: string; password: string };
type Registration = Credentials & { display_name: string };

type AuthContextValue = {
  user: CurrentUser | null;
  loading: boolean;
  login: (credentials: Credentials) => Promise<CurrentUser>;
  register: (registration: Registration) => Promise<CurrentUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    try {
      setUser(await apiRequest<CurrentUser>("/auth/me"));
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    apiRequest<CurrentUser>("/auth/me")
      .then((currentUser) => { if (active) setUser(currentUser); })
      .catch(() => { if (active) setUser(null); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const login = async (credentials: Credentials) => {
    const nextUser = await apiRequest<CurrentUser>("/auth/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    });
    setUser(nextUser);
    return nextUser;
  };

  const register = async (registration: Registration) => {
    const nextUser = await apiRequest<CurrentUser>("/auth/register", {
      method: "POST",
      body: JSON.stringify(registration),
    });
    setUser(nextUser);
    return nextUser;
  };

  const logout = async () => {
    await apiRequest<void>("/auth/logout", { method: "POST" });
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

export function AccountButton({ compact = false }: { compact?: boolean }) {
  const { user, loading, logout } = useAuth();

  if (loading) return <span className={compact ? "account-loading compact" : "account-loading"} />;
  if (!user) {
    return <Link className={compact ? "login-command compact" : "login-command"} href="/login"><UserRound size={15} />登录</Link>;
  }

  return (
    <details className={compact ? "account-menu compact" : "account-menu"}>
      <summary title={user.email}>
        <span>{user.display_name.slice(0, 1)}</span>
        {!compact && <strong>{user.display_name}</strong>}
      </summary>
      <div className="account-popover">
        <header><strong>{user.display_name}</strong><span>{user.email}</span></header>
        <Link href="/library/import"><BookUp size={14} />私人书库</Link>
        {user.role === "admin" && <Link href="/admin/review"><ShieldCheck size={14} />管理员审核台</Link>}
        <button type="button" onClick={() => void logout()}><LogOut size={14} />退出登录</button>
      </div>
    </details>
  );
}
