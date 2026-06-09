"use client";

import { MouseEvent, useEffect, useRef } from "react";

import "./landing-green.css";

type TimelineStep = {
  title: string;
  body: string;
  tag: string;
  focal?: boolean;
};

const STEPS: TimelineStep[] = [
  {
    title: "方向确认",
    body: "把模糊的“看看竞品”收敛成可执行的调研问题——明确对象、维度与边界，避免后续 Agent 跑偏。",
    tag: "Scope Agent",
  },
  {
    title: "公开证据采集",
    body: "只抓公开可核验的来源：官网、定价页、财报、新闻与社区讨论。每条证据都带原始链接与抓取时间戳。",
    tag: "Evidence Agent",
    focal: true,
  },
  {
    title: "分析与推理",
    body: "在证据之上做结构化对比与推理，每条结论都强制绑定支撑它的证据条目——没有出处的判断不会输出。",
    tag: "Analysis Agent",
  },
  {
    title: "来源复核",
    body: "对引用逐条回查：链接是否仍有效、是否被断章取义、时效是否过期，给每条结论标注可信度。",
    tag: "Review Agent",
  },
];

export function Landing({ onEnter }: { onEnter: () => void }) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    const reveals = Array.from(
      root.querySelectorAll<HTMLElement>("[data-reveal]"),
    );
    const items = Array.from(root.querySelectorAll<HTMLElement>(".rl-tl-item"));
    const fill = root.querySelector<HTMLElement>(".rl-timeline__fill");

    const reduce = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    // Without arming, everything stays visible (CSS hides only under .is-armed),
    // so reduced-motion / no-IO environments simply show the full content.
    if (reduce || typeof IntersectionObserver === "undefined") {
      if (fill) fill.style.height = "100%";
      return;
    }

    // Arm: hide reveal targets so the scroll entrance can play.
    root.classList.add("is-armed");

    const revealAll = () => {
      root.classList.remove("is-armed");
      if (fill) fill.style.height = "100%";
    };

    let ioFired = false;

    const revealIO = new IntersectionObserver(
      (entries) => {
        ioFired = true;
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            revealIO.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -15% 0px" },
    );
    reveals.forEach((el) => revealIO.observe(el));

    const timelineIO = new IntersectionObserver(
      (entries) => {
        ioFired = true;
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const el = entry.target as HTMLElement;
          el.classList.add("is-visible");
          const index = items.indexOf(el);
          if (fill && index >= 0) {
            fill.style.height = `${((index + 1) / items.length) * 100}%`;
          }
          timelineIO.unobserve(el);
        });
      },
      { rootMargin: "0px 0px -22% 0px" },
    );
    items.forEach((el) => timelineIO.observe(el));

    // IntersectionObserver always emits an initial callback shortly after
    // observe(). If none arrives, scroll-reveal isn't working here — fail open
    // and show all content rather than leaving it hidden.
    const fallback = window.setTimeout(() => {
      if (!ioFired) revealAll();
    }, 600);

    return () => {
      window.clearTimeout(fallback);
      revealIO.disconnect();
      timelineIO.disconnect();
    };
  }, []);

  const enterWorkbench = (event: MouseEvent) => {
    event.preventDefault();
    onEnter();
  };

  const scrollToFlow = (event: MouseEvent) => {
    event.preventDefault();
    rootRef.current
      ?.querySelector("#flow")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="rl-landing" ref={rootRef}>
      {/* ===== HERO ===== */}
      <header className="rl-hero" id="top">
        <svg
          className="rl-hero__grid"
          viewBox="0 0 1200 600"
          preserveAspectRatio="xMidYMid slice"
          aria-hidden="true"
        >
          <defs>
            <pattern
              id="rl-dots"
              width="34"
              height="34"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="2" cy="2" r="1.3" fill="rgba(0,179,113,0.18)" />
            </pattern>
          </defs>
          <rect width="1200" height="600" fill="url(#rl-dots)" />
        </svg>

        <span className="rl-hero__brand">RIVALENS</span>

        <div className="rl-hero__inner">
          <div className="rl-hero__eyebrow">
            <span className="eyebrow">
              <span className="rule" />
              可追溯的多 Agent 竞品分析
            </span>
          </div>
          <h1 className="rl-hero__title">
            <span className="line-wrap">
              <span className="line-inner">让每条竞品结论，</span>
            </span>
            <span className="line-wrap">
              <span className="line-inner">
                <i>都能回到</i>它的证据。
              </span>
            </span>
          </h1>
          <p className="rl-hero__desc">
            登录后进入可追溯的多 Agent 竞品分析工作台，完成方向确认、公开证据采集、分析与来源复核——每个判断都能点开它背后的出处。
          </p>
          <div className="rl-hero__actions">
            <a href="#login" className="btn-primary" onClick={enterWorkbench}>
              进入工作台
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="5" y1="12" x2="19" y2="12" />
                <polyline points="12 5 19 12 12 19" />
              </svg>
            </a>
            <a href="#flow" className="btn-ghost" onClick={scrollToFlow}>
              看分析流程
            </a>
          </div>
        </div>

        <a
          href="#flow"
          className="rl-hero__cue"
          aria-label="向下滚动"
          onClick={scrollToFlow}
        >
          <span>Scroll</span>
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </a>
      </header>

      {/* ===== FLOW ===== */}
      <section className="rl-flow" id="flow">
        <div className="rl-container">
          <div className="rl-flow__head">
            <span className="eyebrow">
              <span className="rule" />
              多 Agent 工作流
            </span>
            <h2 data-reveal>四步走完，每一步都留痕</h2>
            <p>
              从你确认方向，到结论落地，RIVALENS 把过程拆成可观测的四个 Agent 环节。任何一条 LangSmith trace 都能独立回放。
            </p>
          </div>

          <div className="rl-timeline">
            <div className="rl-timeline__track">
              <div className="rl-timeline__fill" />
            </div>

            {STEPS.map((step, index) => (
              <div
                key={step.tag}
                className={`rl-tl-item${step.focal ? " focal" : ""}`}
              >
                <div className="rl-tl-node">{index + 1}</div>
                <div className="rl-tl-content">
                  <h4>{step.title}</h4>
                  <p>{step.body}</p>
                  <span className="rl-tl-tag">{step.tag}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ===== FOOTER ===== */}
      <footer className="rl-foot">
        <span className="rl-foot__logo">RIVALENS</span>
        <span className="rl-foot__meta">让每条竞品结论，都能回到它的证据。</span>
        <div className="rl-foot__links">
          <button type="button" onClick={enterWorkbench}>
            进入工作台
          </button>
          <button type="button" onClick={scrollToFlow}>
            分析流程
          </button>
        </div>
      </footer>
    </div>
  );
}
