"use client";

import { FormEvent, ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import type { AuthUser } from "./AuthProvider";
import { useAuth } from "./AuthProvider";

type AuthMode = "login" | "register";

export function AuthGate({ children }: { children: ReactNode }) {
  const { user, loading, refreshUser, logout } = useAuth();
  const pathname = usePathname();
  const isMonitoring = pathname === "/monitoring";
  const [profileOpen, setProfileOpen] = useState(false);

  if (loading) {
    return <AuthLoading />;
  }

  if (!user) {
    return <AuthForm onAuthenticated={refreshUser} />;
  }

  return (
    <>
      {children}
      <div className="fixed left-14 top-1.5 z-[120] flex max-w-[calc(100vw-4.5rem)] items-start gap-3 sm:left-20 sm:top-3.5 sm:max-w-none">
        <Link
          href="/monitoring"
          aria-current={isMonitoring ? "page" : undefined}
          className={`rounded-lg border px-4 py-3 text-xs font-semibold shadow-lg shadow-black/20 backdrop-blur-md transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500 ${
            isMonitoring
              ? "border-teal-500/60 bg-teal-500/15 text-teal-100"
              : "border-gray-700 bg-gray-900/80 text-gray-300 hover:border-gray-500 hover:text-gray-100"
          }`}
        >
          Monitoring
        </Link>
        <div className="relative flex items-center gap-3 rounded-lg border border-gray-700 bg-gray-900/80 px-3 py-2 shadow-lg shadow-black/20 backdrop-blur-md">
          <button
            type="button"
            onClick={() => setProfileOpen((open) => !open)}
            className="hidden min-w-0 text-left focus:outline-none focus:ring-2 focus:ring-teal-500 sm:block"
            aria-expanded={profileOpen}
          >
            <p className="truncate text-xs font-semibold text-gray-100">
              {user.display_name}
            </p>
            <p className="truncate text-[11px] text-gray-400">{user.email}</p>
          </button>
          <button
            type="button"
            onClick={() => setProfileOpen((open) => !open)}
            className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500 ${
              profileOpen
                ? "border-teal-500/60 bg-teal-500/10 text-teal-100"
                : "border-gray-700 text-gray-300 hover:border-gray-500 hover:text-gray-100"
            }`}
          >
            资料
          </button>
          <button
            type="button"
            onClick={() => void logout()}
            className="rounded-md border border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-300 transition-colors hover:border-gray-500 hover:text-gray-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
          >
            退出
          </button>
          {profileOpen && (
            <ProfileEditor
              user={user}
              onClose={() => setProfileOpen(false)}
              onSaved={refreshUser}
            />
          )}
        </div>
      </div>
    </>
  );
}

function ProfileEditor({
  user,
  onClose,
  onSaved,
}: {
  user: AuthUser;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [displayName, setDisplayName] = useState(user.display_name);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setDisplayName(user.display_name);
  }, [user.display_name]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setSaved(false);

    const nextDisplayName = displayName.trim();
    if (!nextDisplayName) {
      setError("显示名不能为空");
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch("/api/auth/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: nextDisplayName }),
      });
      const body = (await response.json()) as {
        detail?: string | Array<{ msg?: string }>;
      };

      if (!response.ok) {
        const detail = Array.isArray(body.detail)
          ? body.detail[0]?.msg
          : body.detail;
        throw new Error(detail || "资料保存失败");
      }

      await onSaved();
      setSaved(true);
    } catch (caughtError) {
      setError(
        caughtError instanceof Error ? caughtError.message : "资料保存失败",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="absolute left-0 top-[calc(100%+0.5rem)] w-[min(20rem,calc(100vw-5rem))] rounded-lg border border-gray-700 bg-gray-950 p-4 shadow-2xl shadow-black/40">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-100">个人资料</h2>
          <p className="mt-1 text-xs text-gray-500">更新工作台显示名称</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-gray-800 px-2 py-1 text-xs text-gray-400 transition-colors hover:border-gray-600 hover:text-gray-200 focus:outline-none focus:ring-2 focus:ring-teal-500"
        >
          关闭
        </button>
      </div>

      <form className="space-y-4" onSubmit={submit}>
        <label className="block">
          <span className="mb-2 block text-xs font-medium text-gray-400">
            显示名
          </span>
          <input
            required
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            maxLength={80}
            className="w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-100 outline-none transition-colors placeholder:text-gray-600 hover:border-gray-600 focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
          />
        </label>

        <label className="block">
          <span className="mb-2 block text-xs font-medium text-gray-400">
            邮箱
          </span>
          <input
            readOnly
            value={user.email}
            className="w-full cursor-not-allowed rounded-md border border-gray-800 bg-gray-900/50 px-3 py-2 text-sm text-gray-500 outline-none"
          />
        </label>

        {error && (
          <p className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
            {error}
          </p>
        )}
        {saved && !error && (
          <p className="rounded-md border border-teal-500/30 bg-teal-500/10 px-3 py-2 text-xs text-teal-100">
            已保存
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-teal-600 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-400 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "保存中..." : "保存资料"}
        </button>
      </form>
    </div>
  );
}

function AuthLoading() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-950 px-6">
      <div className="w-full max-w-sm space-y-4">
        <div className="h-7 w-28 animate-pulse rounded bg-gray-800" />
        <div className="h-4 w-full animate-pulse rounded bg-gray-900" />
        <div className="h-11 w-full animate-pulse rounded bg-gray-800" />
        <div className="h-11 w-full animate-pulse rounded bg-gray-800" />
      </div>
    </main>
  );
}

function AuthForm({
  onAuthenticated,
}: {
  onAuthenticated: () => Promise<void>;
}) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      const response = await fetch(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          ...(mode === "register" ? { display_name: displayName } : {}),
        }),
      });
      const body = (await response.json()) as {
        detail?: string | Array<{ msg?: string }>;
      };

      if (!response.ok) {
        const detail = Array.isArray(body.detail)
          ? body.detail[0]?.msg
          : body.detail;
        throw new Error(detail || "认证失败，请稍后重试");
      }
      await onAuthenticated();
    } catch (caughtError) {
      setError(
        caughtError instanceof Error ? caughtError.message : "认证失败，请稍后重试",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const switchMode = (nextMode: AuthMode) => {
    setMode(nextMode);
    setError("");
  };

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gray-950 px-5 py-12 text-gray-100">
      <div className="absolute inset-x-0 top-0 h-px bg-teal-500/50" />
      <section className="relative grid w-full max-w-5xl overflow-hidden rounded-2xl border border-gray-800 bg-gray-900 shadow-2xl shadow-black/30 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="hidden min-h-[620px] flex-col justify-between bg-gray-950 p-12 lg:flex">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-teal-300">
              Rivalens
            </p>
            <h1 className="mt-8 max-w-md text-4xl font-semibold leading-tight text-gray-100">
              让每条竞品结论，都能回到它的证据。
            </h1>
            <p className="mt-5 max-w-md text-sm leading-7 text-gray-400">
              登录后进入可追溯的多 Agent 竞品分析工作台，完成方向确认、公开证据采集、分析与来源复核。
            </p>
          </div>
          <div className="space-y-3 text-sm text-gray-400">
            <p>结构化 Agent 协作</p>
            <p>证据与分析结论绑定</p>
            <p>LangSmith trace 独立观测</p>
          </div>
        </div>

        <div className="px-6 py-9 sm:px-10 sm:py-12">
          <div className="mb-8 lg:hidden">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-teal-300">
              Rivalens
            </p>
          </div>

          <div className="mb-8 flex gap-1 rounded-lg bg-gray-950 p-1">
            {(["login", "register"] as AuthMode[]).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => switchMode(item)}
                className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500 ${
                  mode === item
                    ? "bg-gray-800 text-gray-100"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {item === "login" ? "登录" : "注册"}
              </button>
            ))}
          </div>

          <div className="mb-7">
            <h2 className="text-2xl font-semibold text-gray-100">
              {mode === "login" ? "欢迎回来" : "创建分析账户"}
            </h2>
            <p className="mt-2 text-sm leading-6 text-gray-400">
              {mode === "login"
                ? "使用邮箱继续进入竞品分析工作台。"
                : "只需邮箱、显示名和密码即可开始。"}
            </p>
          </div>

          <form className="space-y-5" onSubmit={submit}>
            {mode === "register" && (
              <AuthField
                label="显示名"
                name="display_name"
                type="text"
                value={displayName}
                onChange={setDisplayName}
                autoComplete="name"
                placeholder="例如：产品分析师"
              />
            )}
            <AuthField
              label="邮箱"
              name="email"
              type="email"
              value={email}
              onChange={setEmail}
              autoComplete="email"
              placeholder="you@example.com"
            />
            <AuthField
              label="密码"
              name="password"
              type="password"
              value={password}
              onChange={setPassword}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              placeholder="至少 8 个字符"
              minLength={8}
            />

            {error && (
              <p
                role="alert"
                className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2.5 text-sm text-red-200"
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-md bg-teal-600 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-400 focus:ring-offset-2 focus:ring-offset-gray-900 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting
                ? "处理中..."
                : mode === "login"
                  ? "登录工作台"
                  : "创建账户"}
            </button>
          </form>

          <p className="mt-7 text-xs leading-5 text-gray-500">
            密码只以加盐摘要形式存储。LangSmith API Key 与 trace 数据不会写入用户表。
          </p>
        </div>
      </section>
    </main>
  );
}

type AuthFieldProps = {
  label: string;
  name: string;
  type: "text" | "email" | "password";
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  placeholder: string;
  minLength?: number;
};

function AuthField({
  label,
  name,
  type,
  value,
  onChange,
  autoComplete,
  placeholder,
  minLength,
}: AuthFieldProps) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-medium text-gray-300">
        {label}
      </span>
      <input
        required
        name={name}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete={autoComplete}
        placeholder={placeholder}
        minLength={minLength}
        className="w-full rounded-md border border-gray-700 bg-gray-950 px-3.5 py-3 text-sm text-gray-100 outline-none transition-colors placeholder:text-gray-600 hover:border-gray-600 focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
      />
    </label>
  );
}
