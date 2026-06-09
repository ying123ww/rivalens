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
      <div className="fixed left-14 top-3 z-[120] flex max-w-[calc(100vw-4.5rem)] items-center gap-2 sm:left-20 sm:top-4 sm:max-w-none">
        <Link
          href="/monitoring"
          aria-current={isMonitoring ? "page" : undefined}
          className={`rounded-[50px] px-4 py-2 text-[14px] font-[480] leading-[1.40] -tracking-[0.10px] transition-all active:scale-[0.97] ${
            isMonitoring
              ? "bg-[#c5b0f4] text-black"
              : "bg-[#dceeb1] text-black/70 hover:text-black"
          }`}
        >
          Monitoring
        </Link>
        <div className="flex items-center gap-1 rounded-[50px] bg-[#f4ecd6] px-2 py-1.5">
          <button
            type="button"
            onClick={() => setProfileOpen((open) => !open)}
            className="hidden min-w-0 rounded-[50px] px-3 py-1 text-left transition-colors hover:bg-black/[0.04] sm:block"
            aria-expanded={profileOpen}
          >
            <p className="truncate text-[13px] font-[500] -tracking-[0.224px] text-black/80">
              {user.display_name}
            </p>
            <p className="truncate text-[11px] text-black/40">{user.email}</p>
          </button>
          <div className="mx-0.5 h-4 w-px bg-black/10" />
          <button
            type="button"
            onClick={() => setProfileOpen((open) => !open)}
            className={`rounded-[50px] px-3 py-1.5 text-[13px] font-[400] -tracking-[0.224px] transition-all active:scale-[0.97] ${
              profileOpen
                ? "bg-black/10 text-black"
                : "text-black/50 hover:bg-black/[0.04] hover:text-black/80"
            }`}
          >
            资料
          </button>
          <button
            type="button"
            onClick={() => void logout()}
            className="rounded-[50px] px-3 py-1.5 text-[13px] font-[400] -tracking-[0.224px] text-black/50 transition-all hover:bg-black/[0.04] hover:text-black/80 active:scale-[0.97]"
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
    <main className="flex min-h-screen items-center justify-center bg-black px-6">
      <div className="w-full max-w-sm space-y-4">
        <div className="mx-auto h-10 w-10 animate-pulse rounded-[50px] bg-white/10" />
        <div className="mx-auto h-5 w-28 animate-pulse rounded-[50px] bg-white/10" />
        <div className="h-[50px] w-full animate-pulse rounded-[50px] bg-white/5" />
        <div className="h-[50px] w-full animate-pulse rounded-[50px] bg-white/5" />
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
  const [showWorkflow, setShowWorkflow] = useState(false);

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
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-black px-5 py-12">
      {/* Purple block — floating on the right side */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -right-32 top-1/2 -translate-y-1/2 h-[500px] w-[500px] rotate-[-12deg] rounded-[32px] bg-[#5645d4] opacity-[0.12] blur-sm" />
      </div>

      <section className="relative w-full max-w-5xl overflow-hidden rounded-xl border border-white/10 bg-[#1d1d1f] shadow-[0_24px_48px_-8px_rgba(0,0,0,0.5)] lg:grid lg:grid-cols-[1.1fr_0.9fr]">
        {/* Left: Brand panel */}
        <div className="hidden flex-col justify-between bg-[#1d1d1f] p-12 lg:flex">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-white/50">
              Rivalens
            </p>
            <h1 className="mt-8 max-w-md text-4xl font-semibold leading-tight text-white">
              知己知彼，
              <br />
              决策有据。
            </h1>
            <p className="mt-5 max-w-md text-sm leading-7 text-white/40">
              深度竞品洞察，让每一次商业决策都建立在扎实的事实之上。
            </p>
          </div>
          <div className="space-y-3 text-sm text-white/30">
            <p>覆盖功能、定价、市场定位等多维对比</p>
            <p>每条结论绑定原始出处，一键回溯</p>
            <p>AI 驱动的智能分析，人工可随时介入校准</p>
          </div>

          <button
            type="button"
            onClick={() => setShowWorkflow(true)}
            className="mt-10 inline-flex items-center gap-2 self-start rounded-[50px] border border-white/10 bg-white/[0.04] px-5 py-2.5 text-[14px] font-[480] leading-[1.40] -tracking-[0.10px] text-white/60 backdrop-blur-sm transition-all hover:border-[#5645d4]/40 hover:bg-white/[0.08] hover:text-white active:scale-[0.97]"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            了解我们
          </button>
        </div>

        {/* Right: Form */}
        <div className="px-8 py-12 sm:px-12">
          <div className="mb-8 lg:hidden">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-white/50">
              Rivalens
            </p>
          </div>

          {/* Notion-style segmented tabs */}
          <div className="mb-8 flex border-b border-white/10">
            {([
              ["login", "登录"],
              ["register", "注册"],
            ] as [AuthMode, string][]).map(([item, label]) => (
              <button
                key={item}
                type="button"
                onClick={() => switchMode(item)}
                className={`relative px-1 pb-3 text-sm font-medium transition-colors ${
                  mode === item
                    ? "text-white"
                    : "text-white/40 hover:text-white/60"
                } ${item === "login" ? "mr-6" : ""}`}
              >
                {label}
                {mode === item && (
                  <span className="absolute inset-x-0 bottom-0 h-0.5 bg-white" />
                )}
              </button>
            ))}
          </div>

          <h2 className="text-[22px] font-semibold text-white">
            {mode === "login" ? "欢迎回来" : "创建分析账户"}
          </h2>
          <p className="mt-2 text-sm text-white/40">
            {mode === "login"
              ? "使用邮箱继续进入竞品分析工作台。"
              : "只需邮箱、显示名和密码即可开始。"}
          </p>

          <form className="mt-7 space-y-4" onSubmit={submit}>
            {mode === "register" && (
              <AuthField
                label="显示名"
                name="display_name"
                type="text"
                value={displayName}
                onChange={setDisplayName}
                autoComplete="name"
                placeholder="产品分析师"
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
              <p className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">
                {error}
              </p>
            )}

            <div className="pt-1">
              <button
                type="submit"
                disabled={submitting}
                className="w-full rounded-lg bg-[#5645d4] py-3 text-sm font-medium text-white transition-colors hover:bg-[#4534b3] disabled:cursor-not-allowed disabled:bg-white/10"
              >
                {submitting
                  ? "处理中..."
                  : mode === "login"
                    ? "Start"
                    : "创建账户"}
              </button>
            </div>
          </form>

          <p className="mt-6 text-center text-xs text-white/20">
            登录即表示同意我们的服务条款和隐私政策
          </p>
        </div>
      </section>

      {/* Workflow Modal */}
      {showWorkflow && (
        <WorkflowModal onClose={() => setShowWorkflow(false)} />
      )}
    </main>
  );
}

const WORKFLOW_STEPS = [
  { step: "01", title: "输入分析目标", desc: "输入产品名称或竞品问题，系统自动识别行业并匹配分析方向", color: "#ff64c8" },
  { step: "02", title: "方向规划", desc: "基于行业分类与成功标准，制定精准的分析维度和搜索策略", color: "#7b3ff2" },
  { step: "03", title: "信息采集", desc: "从公开渠道自动搜索、抓取并整理竞品相关信息", color: "#5645d4" },
  { step: "04", title: "智能质检", desc: "自动审查信息质量与覆盖完整度，发现缺口主动补充采集", color: "#2a9d99" },
  { step: "05", title: "知识提炼", desc: "将原始信息提炼为结构化知识，覆盖功能、定价、用户画像等维度", color: "#1aae39" },
  { step: "06", title: "多维度分析", desc: "生成 SWOT 矩阵与功能对比表，每项结论均可追溯到原始出处", color: "#f5d75e" },
  { step: "07", title: "质量复核", desc: "逐条验证分析结论的证据支撑度，自动修正或标记存疑内容", color: "#dd5b00" },
  { step: "08", title: "报告生成", desc: "整合所有分析结果，一键导出 Markdown、PDF、Word 等格式", color: "#ff3d8b" },
];

function WorkflowModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/80 px-4 py-8 backdrop-blur-sm" onClick={onClose}>
      <div
        className="relative max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-white/10 bg-[#1d1d1f] p-8 shadow-[0_24px_48px_-8px_rgba(0,0,0,0.6)] sm:p-10"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded-full p-2 text-white/40 transition-colors hover:bg-white/10 hover:text-white"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        <h2 className="text-[28px] font-semibold leading-[1.25] tracking-[-0.26px] text-white">
          工作流程
        </h2>
        <p className="mt-2 text-[16px] leading-[1.55] text-white/40">
          九大 Agent 协同编排，从输入到报告，全链路透明可追溯
        </p>

        {/* Timeline */}
        <div className="mt-10 space-y-0">
          {WORKFLOW_STEPS.map((item, index) => (
            <div key={item.step} className="relative flex gap-5 pb-8 last:pb-0">
              {/* Timeline line */}
              {index < WORKFLOW_STEPS.length - 1 && (
                <div className="absolute left-[18px] top-10 bottom-0 w-px bg-white/10" />
              )}
              {/* Step dot */}
              <div
                className="relative z-10 mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold text-white"
                style={{ backgroundColor: item.color }}
              >
                {item.step}
              </div>
              {/* Content */}
              <div className="min-w-0 pt-0.5">
                <h3 className="text-[18px] font-semibold leading-[1.40] text-white">
                  {item.title}
                </h3>
                <p className="mt-1 text-[14px] leading-[1.50] text-white/40">
                  {item.desc}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
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
      <span className="mb-1.5 block text-[13px] font-medium text-white/60">
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
        className="h-11 w-full rounded-lg border border-white/10 bg-white/[0.04] px-4 text-sm text-white placeholder-white/20 outline-none transition-all focus:border-[#5645d4] focus:ring-2 focus:ring-[#5645d4]/20"
      />
    </label>
  );
}
