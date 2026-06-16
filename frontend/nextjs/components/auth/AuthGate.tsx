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
  const [showAuthForm, setShowAuthForm] = useState(pathname !== "/");

  useEffect(() => {
    if (pathname !== "/") {
      setShowAuthForm(true);
    }
  }, [pathname]);

  if (loading) {
    return <AuthLoading />;
  }

  if (!user) {
    return showAuthForm ? (
      <AuthForm
        onAuthenticated={refreshUser}
        onBackHome={() => setShowAuthForm(false)}
      />
    ) : (
      <BrandLanding onEnterWorkspace={() => setShowAuthForm(true)} />
    );
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
    <main className="rivalens-cosmos flex min-h-screen items-center justify-center px-6">
      <CosmosBackdrop />
      <div className="w-full max-w-sm space-y-4">
        <div className="mx-auto h-10 w-10 animate-pulse rounded-[50px] bg-white/10" />
        <div className="mx-auto h-5 w-28 animate-pulse rounded-[50px] bg-white/10" />
        <div className="h-[50px] w-full animate-pulse rounded-[50px] bg-white/5" />
        <div className="h-[50px] w-full animate-pulse rounded-[50px] bg-white/5" />
      </div>
    </main>
  );
}

function CosmosBackdrop() {
  return (
    <div className="rivalens-cosmos-backdrop" aria-hidden="true">
      <span className="rivalens-stars" />
      <span className="rivalens-orbit rivalens-orbit-left" />
      <span className="rivalens-orbit rivalens-orbit-right" />
      <span className="rivalens-plane rivalens-plane-left" />
      <span className="rivalens-plane rivalens-plane-right" />
      <span className="rivalens-node rivalens-node-left" />
      <span className="rivalens-node rivalens-node-right" />
      <span className="rivalens-node rivalens-node-violet" />
    </div>
  );
}

function BrandLanding({
  onEnterWorkspace,
}: {
  onEnterWorkspace: () => void;
}) {
  const scrollToWorkflow = () => {
    document
      .getElementById("landing-workflow")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <main className="rivalens-cosmos rivalens-landing-screen">
      <CosmosBackdrop />
      <header className="rivalens-public-nav">
        <nav className="rivalens-public-links" aria-label="公开导航">
          <button type="button" onClick={onEnterWorkspace}>
            RIVALENS
          </button>
          <button type="button" onClick={scrollToWorkflow}>
            分析流程
          </button>
        </nav>
        <button
          type="button"
          onClick={onEnterWorkspace}
          className="rivalens-wordmark"
          aria-label="进入 Rivalens 登录页"
        >
          RIVALENS
        </button>
        <div className="rivalens-public-actions">
          <Link href="/monitoring" className="rivalens-status-pill">
            <span />
            Monitoring
          </Link>
          <button
            type="button"
            onClick={onEnterWorkspace}
            className="rivalens-top-action"
          >
            开启分析之旅
          </button>
        </div>
      </header>

      <section className="rivalens-hero-stage">
        <p className="rivalens-eyebrow">
          <span />
          可追溯的多 Agent 竞品分析
        </p>
        <h1>
          让每条竞品结论，
          <br />
          <strong>都能回到</strong>它的证据。
        </h1>
        <p className="rivalens-hero-copy">
          登录后进入可追溯的多 Agent 竞品分析工作台，
          <br />
          完成方向确认、公开证据采集、分析与来源复核。
        </p>
        <div className="rivalens-hero-actions">
          <button
            type="button"
            onClick={onEnterWorkspace}
            className="rivalens-primary-action"
          >
            let's start
            <span aria-hidden="true">→</span>
          </button>
          <button
            type="button"
            onClick={scrollToWorkflow}
            className="rivalens-secondary-action"
          >
            了解我们
          </button>
        </div>
        <button
          type="button"
          onClick={scrollToWorkflow}
          className="rivalens-scroll-cue"
        >
          <span>SCROLL</span>
          <span aria-hidden="true">⌄</span>
        </button>
      </section>

      <section id="landing-workflow" className="rivalens-workflow-section">
        <div className="rivalens-workflow-heading">
          <p>TRACEABLE WORKFLOW</p>
          <h2>从问题到结论，每一步都留下证据链。</h2>
        </div>
        <div className="rivalens-workflow-grid">
          {WORKFLOW_STEPS.slice(0, 6).map((item) => (
            <article key={item.step} className="rivalens-workflow-card">
              <span>{item.step}</span>
              <h3>{item.title}</h3>
              <p>{item.desc}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

function ProofItem({ title, text }: { title: string; text: string }) {
  return (
    <div className="rivalens-proof-item">
      <span aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none">
          <path d="M12 3.5v17M3.5 12h17" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="12" cy="12" r="5.4" stroke="currentColor" strokeWidth="1.6" />
        </svg>
      </span>
      <div>
        <h3>{title}</h3>
        <p>{text}</p>
      </div>
    </div>
  );
}

function AuthForm({
  onAuthenticated,
  onBackHome,
}: {
  onAuthenticated: () => Promise<void>;
  onBackHome: () => void;
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
    <main className="rivalens-cosmos rivalens-auth-screen">
      <CosmosBackdrop />
      <header className="rivalens-auth-nav">
        <button type="button" onClick={onBackHome} className="rivalens-wordmark">
          RIVALENS
        </button>
        <div className="rivalens-public-actions">
          <Link href="/monitoring" className="rivalens-status-pill">
            <span />
            Monitoring
          </Link>
          <button
            type="button"
            onClick={onBackHome}
            className="rivalens-nav-text-action"
          >
            返回首页
          </button>
        </div>
      </header>

      <section className="rivalens-auth-card">
        <aside className="rivalens-auth-brand-panel">
          <div>
            <p className="rivalens-panel-kicker">RIVALENS</p>
            <h1>
              知己知彼，
              <br />
              决策<strong>有据</strong>。
            </h1>
            <p>
              RIVALENS 以可追溯的多 Agent 竞品分析，让每一次商业决策都建立在真实、可靠的证据之上。
            </p>
          </div>
          <div className="rivalens-proof-list">
            <ProofItem title="多源数据交叉验证" text="覆盖全网数据，交叉校验，确保真实可靠" />
            <ProofItem title="智能分析驱动洞察" text="AI 多 Agent 协同分析，深挖关键机会与风险" />
            <ProofItem title="可追溯的证据链" text="每项结论均可回溯来源，透明可信" />
          </div>
        </aside>

        <div className="rivalens-auth-form-panel">
          <div className="rivalens-auth-tabs">
            {([
              ["login", "登录"],
              ["register", "注册"],
            ] as [AuthMode, string][]).map(([item, label]) => (
              <button
                key={item}
                type="button"
                onClick={() => switchMode(item)}
                className={mode === item ? "is-active" : ""}
              >
                {label}
              </button>
            ))}
          </div>

          <h2>
            {mode === "login" ? "欢迎回来" : "创建分析账户"}
          </h2>
          <p className="rivalens-auth-intro">
            {mode === "login"
              ? "使用邮箱继续进入竞品分析工作台。"
              : "只需邮箱、显示名和密码即可开始。"}
          </p>

          <form className="rivalens-auth-form" onSubmit={submit}>
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
              <p className="rivalens-auth-error">
                {error}
              </p>
            )}

            {mode === "login" && (
              <div className="rivalens-auth-options">
                <label>
                  <input type="checkbox" defaultChecked />
                  <span>记住我</span>
                </label>
                <button type="button">忘记密码?</button>
              </div>
            )}

            <div>
              <button type="submit" disabled={submitting} className="rivalens-primary-action">
                {submitting ? "处理中..." : mode === "login" ? "开始探索" : "创建账户"}
                <span aria-hidden="true">→</span>
              </button>
            </div>
          </form>

          <p className="rivalens-auth-footnote">
            登录即表示同意我们的 <button type="button">服务条款</button> 和{" "}
            <button type="button">隐私政策</button>
          </p>
        </div>
      </section>
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
    <label className="rivalens-auth-field">
      <span>{label}</span>
      <input
        required
        name={name}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete={autoComplete}
        placeholder={placeholder}
        minLength={minLength}
      />
    </label>
  );
}
