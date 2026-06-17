"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { EChartsOption } from "echarts";
import dynamic from "next/dynamic";
import Link from "next/link";

import { useResearchHistoryContext } from "@/hooks/ResearchHistoryContext";
import { ResearchHistoryItem } from "@/types/data";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

type ReportRecord = ResearchHistoryItem & Record<string, any>;
type Row = Record<string, any>;

type StatusSegment = {
  label: string;
  key: string;
  value: number;
  color: string;
};

type RunDiffData = {
  previousRun: ReportRecord | null;
  summaries: Array<{
    label: string;
    value: string;
    detail: string;
    tone: "teal" | "blue" | "amber" | "gray";
  }>;
  addedSources: SourceDiffItem[];
  addedClaims: ClaimDiffItem[];
  changedClaims: ClaimChangeItem[];
};

type SourceDiffItem = {
  key: string;
  title: string;
  url: string;
  sourceType: string;
};

type ClaimDiffItem = {
  key: string;
  text: string;
  dimension: string;
  competitors: string[];
};

type ClaimChangeItem = ClaimDiffItem & {
  previousStatus: string;
  currentStatus: string;
  previousConfidence: number | null;
  currentConfidence: number | null;
};

type ClaimExplorerItem = {
  id: string;
  text: string;
  dimension: string;
  competitors: string[];
  status: string;
  statusLabel: string;
  confidence: number | null;
  evidenceCount: number;
  sourceCount: number;
};

type TraceGraphEvidence = {
  id: string;
  title: string;
  url: string;
  sourceType: string;
};

type TraceGraphClaim = {
  id: string;
  text: string;
  statusLabel: string;
  evidence: TraceGraphEvidence[];
};

type TraceGraphDimension = {
  dimension: string;
  claims: TraceGraphClaim[];
};

type TraceGraphGroup = {
  competitor: string;
  dimensions: TraceGraphDimension[];
};

const SOURCE_COLORS = [
  "#2dd4bf",
  "#60a5fa",
  "#f59e0b",
  "#34d399",
  "#a78bfa",
  "#6b7280",
];

const SOURCE_TYPE_COLORS: Record<string, string> = {
  official_site: "#2dd4bf",
  pricing_page: "#60a5fa",
  docs: "#f87171",
  financial_filing: "#34d399",
  public_registry: "#a78bfa",
  other: "#60a5fa",
};

const STATUS_COLORS: Record<string, string> = {
  supported: "#2dd4bf",
  supported_with_limitations: "#38bdf8",
  weak: "#f59e0b",
  contradicted: "#f87171",
  unverifiable: "#a78bfa",
  unreviewed: "#6b7280",
};

const STATUS_LABELS: Record<string, string> = {
  supported: "已支持",
  supported_with_limitations: "有限支持",
  weak: "弱支持",
  contradicted: "冲突",
  unverifiable: "不可验证",
  unreviewed: "未复核",
};

const DIRECTION_LABELS: Record<string, string> = {
  strategic_positioning: "战略定位与差异化",
  target_users_segments: "目标用户与细分场景",
  core_product_supply: "核心产品与供给能力",
  product_experience: "交互与产品体验",
  ai_capability_application: "AI 能力与应用",
  business_model_pricing: "商业模式与定价",
  growth_channels: "增长渠道",
  operations_fulfillment: "运营与交付",
  baseline_trust_security_compliance: "基础信任、安全与合规",
  user_reputation: "用户口碑",
  moat_resources_team: "护城河、资源与团队",
  market_trends_opportunities: "市场趋势与机会",
  integrations_ecosystem: "集成与生态",
  migration_switching_cost: "迁移与切换成本",
  sla_reliability: "服务稳定性与可靠性",
};

const PIPELINE_STEPS = [
  "Planning",
  "Collection",
  "Structuring",
  "Analysis",
  "Claim Review",
  "Writing",
  "Publishing",
];

export default function MonitoringPage() {
  const { history, loading } = useResearchHistoryContext();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selectedRun = useMemo(() => {
    if (history.length === 0) {
      return null;
    }
    return (
      history.find((item) => item.id === selectedId) ??
      history[0]
    ) as ReportRecord;
  }, [history, selectedId]);

  const dashboard = useMemo(
    () => (selectedRun ? buildDashboard(selectedRun) : null),
    [selectedRun],
  );
  const previousRun = useMemo(
    () =>
      selectedRun
        ? findPreviousRun(history as ReportRecord[], selectedRun)
        : null,
    [history, selectedRun],
  );
  const runDiff = useMemo(
    () => (selectedRun ? buildRunDiff(selectedRun, previousRun) : null),
    [previousRun, selectedRun],
  );
  const claimExplorerItems = useMemo(
    () => (selectedRun ? buildClaimExplorerItems(selectedRun) : []),
    [selectedRun],
  );
  const traceGraphGroups = useMemo(
    () => (selectedRun ? buildTraceGraphGroups(selectedRun) : []),
    [selectedRun],
  );

  return (
    <main className="min-h-screen bg-[#0C111F] px-4 py-24 text-gray-100 sm:px-6 lg:px-10">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
        <header className="flex flex-col gap-4 border-b border-gray-800 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-300">
              Rivalens Monitoring
            </p>
            <h1 className="mt-2 text-2xl font-semibold text-gray-50 sm:text-3xl">
              每次运行看板
            </h1>
          </div>
          <Link
            href="/"
            className="inline-flex w-fit items-center rounded-md border border-gray-700 px-4 py-2 text-sm font-medium text-gray-300 transition-colors hover:border-gray-500 hover:text-gray-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
          >
            返回
          </Link>
        </header>

        {loading ? (
          <LoadingDashboard />
        ) : history.length === 0 || !selectedRun || !dashboard ? (
          <EmptyDashboard />
        ) : (
          <div className="grid gap-5 xl:grid-cols-[320px_1fr]">
            <aside className="rounded-lg border border-gray-800 bg-gray-900/60 p-4">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-100">运行记录</h2>
                <span className="text-xs text-gray-500">{history.length} 次运行</span>
              </div>
              <div className="max-h-[calc(100vh-220px)] space-y-2 overflow-y-auto pr-1">
                {history.map((run) => {
                  const isActive = run.id === selectedRun.id;
                  return (
                    <button
                      key={run.id}
                      type="button"
                      onClick={() => setSelectedId(run.id)}
                      className={`w-full rounded-md border p-3 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500 ${
                        isActive
                          ? "border-teal-500/60 bg-teal-500/10"
                          : "border-gray-800 bg-gray-950/30 hover:border-gray-700 hover:bg-gray-950/60"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <p className="min-w-0 truncate text-sm font-medium text-gray-100">
                          {run.question || run.id}
                        </p>
                        <StatusBadge status={run.status} />
                      </div>
                      <p className="mt-2 truncate text-xs text-gray-500">
                        记录编号：{formatRunReference(run.id)}
                      </p>
                      <p className="mt-1 text-xs text-gray-500">
                        {formatDate(run.timestamp)}
                      </p>
                    </button>
                  );
                })}
              </div>
            </aside>

            <section className="flex min-w-0 flex-col gap-5">
              <RunHeader run={selectedRun} dashboard={dashboard} />

              <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {dashboard.metrics.map((metric) => (
                  <MetricCard key={metric.label} {...metric} />
                ))}
              </section>

              {runDiff && <RunDiffPanel diff={runDiff} />}

              <section className="grid gap-5 xl:grid-cols-[1.4fr_0.9fr]">
                <EvidenceStackedBars dashboard={dashboard} />
                <ClaimStatusDonut dashboard={dashboard} />
              </section>

              <section className="grid gap-5 xl:grid-cols-[1.2fr_0.9fr]">
                <ConfidenceHeatmap dashboard={dashboard} />
                <PipelineFunnel dashboard={dashboard} />
              </section>

              <ClaimExplorer items={claimExplorerItems} />
              <EvidenceTraceGraph groups={traceGraphGroups} />
            </section>
          </div>
        )}
      </div>
    </main>
  );
}

function RunHeader({
  run,
  dashboard,
}: {
  run: ReportRecord;
  dashboard: DashboardData;
}) {
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={run.status} />
            <span className="rounded-full border border-gray-700 px-2.5 py-1 text-xs text-gray-400">
              {dashboard.hasStructuredData ? "结构化数据" : "基础报告"}
            </span>
          </div>
          <h2 className="mt-3 line-clamp-2 text-lg font-semibold text-gray-50">
            {run.question || "未命名运行"}
          </h2>
          <p className="mt-2 break-all text-xs text-gray-500">
            运行编号：{formatRunReference(run.id)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href={`/research/${run.id}`}
            className="rounded-md border border-gray-700 px-3 py-2 text-sm font-medium text-gray-300 transition-colors hover:border-gray-500 hover:text-gray-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
          >
            查看报告
          </Link>
          <span className="rounded-md border border-gray-800 px-3 py-2 text-sm text-gray-500">
            {formatDate(run.timestamp)}
          </span>
        </div>
      </div>
    </section>
  );
}

function MetricCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-4">
      <p className="text-sm text-gray-400">{label}</p>
      <p className="mt-3 text-3xl font-semibold text-gray-100">{value}</p>
      <p className="mt-2 text-xs text-gray-500">{detail}</p>
    </div>
  );
}

function EvidenceStackedBars({ dashboard }: { dashboard: DashboardData }) {
  const option = useMemo(() => buildEvidenceOption(dashboard), [dashboard]);
  return (
    <ChartPanel
      title="证据来源分布"
      subtitle="按竞品对比来源类型，一眼看出一手来源是否充足。"
    >
      {dashboard.evidenceByCompetitor.length === 0 ? (
        <EmptyPanelText text="当前运行暂无可用于绘图的证据来源数据。" />
      ) : (
        <EChart option={option} height={320} />
      )}
    </ChartPanel>
  );
}

function ClaimStatusDonut({ dashboard }: { dashboard: DashboardData }) {
  const option = useMemo(() => buildClaimStatusOption(dashboard), [dashboard]);
  return (
    <ChartPanel
      title="声明验证状态"
      subtitle="质量复核结果越集中在已支持，报告越适合直接交付。"
    >
      {dashboard.claimStatusSegments.length === 0 ? (
        <EmptyPanelText text="当前运行暂无声明复核结果。" />
      ) : (
        <EChart option={option} height={320} />
      )}
    </ChartPanel>
  );
}

function ConfidenceHeatmap({ dashboard }: { dashboard: DashboardData }) {
  const columns = dashboard.heatmapDimensions;
  const rows = dashboard.heatmapRows;
  const option = useMemo(() => buildHeatmapOption(dashboard), [dashboard]);
  return (
    <ChartPanel
      title="竞品 x 维度信心"
      subtitle="按 evidence confidence 汇总，帮助定位需要补充采集的薄弱维度。"
    >
      {rows.length === 0 || columns.length === 0 ? (
        <EmptyPanelText text="当前运行缺少竞品、维度或 confidence 字段。" />
      ) : (
        <EChart option={option} height={340} />
      )}
    </ChartPanel>
  );
}

function PipelineFunnel({ dashboard }: { dashboard: DashboardData }) {
  const option = useMemo(() => buildPipelineOption(dashboard), [dashboard]);
  return (
    <ChartPanel
      title="Agent 流水线"
      subtitle="从计划、采集、结构化到发布，检查每一段是否有真实产出。"
    >
      <EChart option={option} height={320} />
    </ChartPanel>
  );
}

function RunDiffPanel({ diff }: { diff: RunDiffData }) {
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-100">运行对比 Diff</h2>
          <p className="mt-1 text-sm text-gray-500">
            自动对比上一轮运行，查看新增来源、结论变化和可信度波动。
          </p>
        </div>
        <span className="w-fit rounded-full border border-gray-700 px-2.5 py-1 text-xs text-gray-400">
          {diff.previousRun ? `对比 ${formatRunReference(diff.previousRun.id)}` : "暂无上一轮"}
        </span>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {diff.summaries.map((item) => (
          <div
            key={item.label}
            className={`rounded-lg border p-4 ${diffToneClassName(item.tone)}`}
          >
            <p className="text-xs font-medium text-gray-400">{item.label}</p>
            <p className="mt-2 text-2xl font-semibold text-gray-100">{item.value}</p>
            <p className="mt-1 text-xs text-gray-500">{item.detail}</p>
          </div>
        ))}
      </div>

      {!diff.previousRun ? (
        <div className="mt-5">
          <EmptyPanelText text="至少需要两次运行后，才能生成运行对比。" />
        </div>
      ) : (
        <div className="mt-5 grid gap-4 xl:grid-cols-3">
          <DiffList
            title="新增来源"
            emptyText="本轮没有新增来源。"
            items={diff.addedSources.slice(0, 6).map((item) => ({
              key: item.key,
              title: item.title,
              meta: item.sourceType,
              detail: sourceNameFromUrl(item.url),
            }))}
          />
          <DiffList
            title="新增结论"
            emptyText="本轮没有新增结论。"
            items={diff.addedClaims.slice(0, 6).map((item) => ({
              key: item.key,
              title: item.text,
              meta: item.dimension,
              detail: item.competitors.join("、") || "整体",
            }))}
          />
          <DiffList
            title="变化结论"
            emptyText="未发现明显状态或信心变化。"
            items={diff.changedClaims.slice(0, 6).map((item) => ({
              key: item.key,
              title: item.text,
              meta: `${item.previousStatus} → ${item.currentStatus}`,
              detail: confidenceChangeText(item.previousConfidence, item.currentConfidence),
            }))}
          />
        </div>
      )}
    </section>
  );
}

function DiffList({
  title,
  emptyText,
  items,
}: {
  title: string;
  emptyText: string;
  items: Array<{ key: string; title: string; meta: string; detail: string }>;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-gray-800 bg-gray-950/40 p-4">
      <h3 className="text-sm font-semibold text-gray-100">{title}</h3>
      {items.length === 0 ? (
        <p className="mt-4 rounded-md border border-dashed border-gray-800 px-3 py-4 text-sm text-gray-500">
          {emptyText}
        </p>
      ) : (
        <div className="mt-4 space-y-3">
          {items.map((item) => (
            <article key={item.key} className="min-w-0 rounded-md bg-gray-900/70 p-3">
              <p className="line-clamp-2 text-sm font-medium leading-5 text-gray-100">
                {item.title}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-gray-800 px-2 py-0.5 text-[11px] text-gray-400">
                  {item.meta}
                </span>
                <span className="truncate text-[11px] text-gray-500">{item.detail}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function ClaimExplorer({ items }: { items: ClaimExplorerItem[] }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [dimension, setDimension] = useState("all");
  const dimensions = useMemo(
    () => uniqueStrings(items.map((item) => item.dimension)).slice(0, 18),
    [items],
  );
  const statuses = useMemo(
    () =>
      Array.from(
        new Map(items.map((item) => [item.status, item.statusLabel])).entries(),
      ),
    [items],
  );
  const filteredItems = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return items.filter((item) => {
      const matchesQuery =
        !keyword ||
        [item.text, item.dimension, item.statusLabel, ...item.competitors]
          .join(" ")
          .toLowerCase()
          .includes(keyword);
      const matchesStatus = status === "all" || item.status === status;
      const matchesDimension = dimension === "all" || item.dimension === dimension;
      return matchesQuery && matchesStatus && matchesDimension;
    });
  }, [dimension, items, query, status]);

  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-100">Claim Explorer 结论库</h2>
          <p className="mt-1 text-sm text-gray-500">
            查看全部结论，按竞品、维度、证据状态和关键词快速筛选。
          </p>
        </div>
        <span className="w-fit rounded-full border border-gray-700 px-2.5 py-1 text-xs text-gray-400">
          {filteredItems.length}/{items.length} 条结论
        </span>
      </div>

      <div className="mt-5 grid gap-3 lg:grid-cols-[1fr_180px_220px]">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索结论、竞品或维度"
          className="h-10 rounded-md border border-gray-800 bg-gray-950/70 px-3 text-sm text-gray-100 outline-none transition-colors placeholder:text-gray-600 focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
        />
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="h-10 rounded-md border border-gray-800 bg-gray-950/70 px-3 text-sm text-gray-200 outline-none transition-colors focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
        >
          <option value="all">全部状态</option>
          {statuses.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <select
          value={dimension}
          onChange={(event) => setDimension(event.target.value)}
          className="h-10 rounded-md border border-gray-800 bg-gray-950/70 px-3 text-sm text-gray-200 outline-none transition-colors focus:border-teal-500 focus:ring-1 focus:ring-teal-500"
        >
          <option value="all">全部维度</option>
          {dimensions.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </div>

      {items.length === 0 ? (
        <div className="mt-5">
          <EmptyPanelText text="当前运行暂无可浏览的分析结论。" />
        </div>
      ) : (
        <div className="mt-5 max-h-[520px] overflow-y-auto pr-1">
          <div className="grid gap-3">
            {filteredItems.slice(0, 80).map((item) => (
              <article
                key={item.id}
                className="rounded-lg border border-gray-800 bg-gray-950/40 p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-teal-500/40 bg-teal-500/10 px-2.5 py-1 text-[11px] text-teal-200">
                    {item.statusLabel}
                  </span>
                  <span className="rounded-full border border-gray-700 px-2.5 py-1 text-[11px] text-gray-400">
                    {item.dimension}
                  </span>
                  <span className="text-[11px] text-gray-500">
                    {item.competitors.join("、") || "整体"}
                  </span>
                </div>
                <p className="mt-3 line-clamp-3 text-sm leading-6 text-gray-100">
                  {item.text}
                </p>
                <div className="mt-3 grid gap-2 text-xs text-gray-500 sm:grid-cols-3">
                  <span>信心：{formatConfidence(item.confidence)}</span>
                  <span>关联证据：{item.evidenceCount} 条</span>
                  <span>来源站点：{item.sourceCount} 个</span>
                </div>
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function EvidenceTraceGraph({ groups }: { groups: TraceGraphGroup[] }) {
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-100">证据关系图谱</h2>
          <p className="mt-1 text-sm text-gray-500">
            从竞品到维度、结论和来源，展示一条结论背后的可追溯路径。
          </p>
        </div>
        <span className="w-fit rounded-full border border-gray-700 px-2.5 py-1 text-xs text-gray-400">
          {groups.length} 个竞品节点
        </span>
      </div>

      {groups.length === 0 ? (
        <div className="mt-5">
          <EmptyPanelText text="当前运行缺少结论与证据的关联数据，暂无法绘制关系图谱。" />
        </div>
      ) : (
        <div className="mt-5 overflow-x-auto">
          <div className="min-w-[960px] space-y-4">
            <div className="grid grid-cols-[150px_180px_1fr_230px] gap-3 px-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              <span>竞品</span>
              <span>分析维度</span>
              <span>结论</span>
              <span>证据来源</span>
            </div>
            {groups.map((group) => (
              <div
                key={group.competitor}
                className="grid grid-cols-[150px_180px_1fr_230px] gap-3 rounded-lg border border-gray-800 bg-gray-950/40 p-3"
              >
                <div className="flex items-center">
                  <div className="w-full rounded-md border border-teal-500/40 bg-teal-500/10 px-3 py-3 text-sm font-semibold text-teal-100">
                    {group.competitor}
                  </div>
                </div>
                <div className="space-y-3">
                  {group.dimensions.map((dimension) => (
                    <div
                      key={`${group.competitor}-${dimension.dimension}`}
                      className="rounded-md border border-gray-800 bg-gray-900/70 px-3 py-3 text-sm text-gray-200"
                    >
                      {dimension.dimension}
                    </div>
                  ))}
                </div>
                <div className="space-y-3">
                  {group.dimensions.map((dimension) => (
                    <div key={`${dimension.dimension}-claims`} className="space-y-2">
                      {dimension.claims.map((claim) => (
                        <div
                          key={claim.id}
                          className="rounded-md border border-gray-800 bg-gray-900/70 p-3"
                        >
                          <div className="mb-2 flex items-center gap-2">
                            <span className="rounded-full bg-gray-800 px-2 py-0.5 text-[11px] text-gray-400">
                              {claim.statusLabel}
                            </span>
                            <span className="text-[11px] text-gray-600">
                              {formatClaimReference(claim.id)}
                            </span>
                          </div>
                          <p className="line-clamp-2 text-sm leading-5 text-gray-100">
                            {claim.text}
                          </p>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
                <div className="space-y-3">
                  {group.dimensions.map((dimension) => (
                    <div key={`${dimension.dimension}-evidence`} className="space-y-2">
                      {dimension.claims.flatMap((claim) => claim.evidence).slice(0, 4).map((evidence) => (
                        <a
                          key={`${dimension.dimension}-${evidence.id}-${evidence.url}`}
                          href={evidence.url || undefined}
                          target="_blank"
                          rel="noreferrer"
                          className="block rounded-md border border-gray-800 bg-gray-900/70 p-3 transition-colors hover:border-teal-500/50 hover:bg-gray-900"
                        >
                          <p className="line-clamp-2 text-xs font-medium leading-5 text-gray-200">
                            {evidence.title}
                          </p>
                          <p className="mt-1 truncate text-[11px] text-gray-500">
                            {evidence.sourceType}
                          </p>
                        </a>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function EChart({
  option,
  height,
}: {
  option: EChartsOption;
  height: number;
}) {
  return (
    <ReactECharts
      option={option}
      notMerge
      lazyUpdate
      style={{ height, width: "100%" }}
      opts={{ renderer: "canvas" }}
    />
  );
}

function ChartPanel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-[360px] rounded-lg border border-gray-800 bg-gray-900/60 p-5">
      <div className="mb-6">
        <h2 className="text-base font-semibold text-gray-100">{title}</h2>
        <p className="mt-1 text-sm text-gray-500">{subtitle}</p>
      </div>
      {children}
    </div>
  );
}

function StatusBadge({ status }: { status?: string }) {
  const normalized = (status || "unknown").toLowerCase();
  const label =
    normalized === "completed"
      ? "已完成"
      : normalized === "running"
        ? "运行中"
        : normalized === "failed" || normalized === "error"
          ? "运行失败"
          : "状态未知";
  const className =
    normalized === "completed"
      ? "border-teal-500/50 bg-teal-500/10 text-teal-200"
      : normalized === "running"
        ? "border-blue-500/50 bg-blue-500/10 text-blue-200"
        : normalized === "failed" || normalized === "error"
          ? "border-red-500/50 bg-red-500/10 text-red-200"
          : "border-gray-700 bg-gray-800/60 text-gray-400";

  return (
    <span className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] ${className}`}>
      {label}
    </span>
  );
}

function EmptyDashboard() {
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-10 text-center">
      <h2 className="text-lg font-semibold text-gray-100">暂无运行数据</h2>
      <p className="mx-auto mt-2 max-w-xl text-sm text-gray-500">
        完成一次竞品分析后，这里会自动出现对应运行的证据、声明、质量复核和 Agent 流水线看板。
      </p>
      <Link
        href="/"
        className="mt-6 inline-flex rounded-md bg-teal-500 px-4 py-2 text-sm font-medium text-gray-950 transition-colors hover:bg-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-500"
      >
        开始分析
      </Link>
    </section>
  );
}

function LoadingDashboard() {
  return (
    <div className="grid gap-5 xl:grid-cols-[320px_1fr]">
      <div className="h-[520px] animate-pulse rounded-lg bg-gray-900/60" />
      <div className="space-y-5">
        <div className="h-32 animate-pulse rounded-lg bg-gray-900/60" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[1, 2, 3, 4].map((item) => (
            <div key={item} className="h-32 animate-pulse rounded-lg bg-gray-900/60" />
          ))}
        </div>
        <div className="grid gap-5 xl:grid-cols-2">
          <div className="h-96 animate-pulse rounded-lg bg-gray-900/60" />
          <div className="h-96 animate-pulse rounded-lg bg-gray-900/60" />
        </div>
      </div>
    </div>
  );
}

function EmptyPanelText({ text }: { text: string }) {
  return (
    <div className="flex min-h-[220px] items-center justify-center rounded-lg border border-dashed border-gray-800 bg-gray-950/30 px-6 text-center text-sm text-gray-500">
      {text}
    </div>
  );
}

type DashboardData = {
  hasStructuredData: boolean;
  metrics: Array<{ label: string; value: string; detail: string }>;
  evidenceByCompetitor: Array<{
    competitor: string;
    total: number;
    sources: Record<string, number>;
  }>;
  sourceTypes: string[];
  claimStatusSegments: StatusSegment[];
  supportRate: number;
  heatmapDimensions: string[];
  heatmapRows: Array<{
    competitor: string;
    scores: Record<string, number | null>;
  }>;
  pipeline: Array<{ label: string; value: number }>;
};

const tooltipStyle = {
  backgroundColor: "rgba(17, 24, 39, 0.96)",
  borderColor: "#374151",
  textStyle: { color: "#e5e7eb" },
};

function buildEvidenceOption(dashboard: DashboardData): EChartsOption {
  const competitors = dashboard.evidenceByCompetitor.map((row) => row.competitor);
  return {
    color: dashboard.sourceTypes.map((source) => SOURCE_TYPE_COLORS[source] ?? SOURCE_COLORS[dashboard.sourceTypes.indexOf(source) % SOURCE_COLORS.length]),
    tooltip: { ...tooltipStyle, trigger: "axis", axisPointer: { type: "shadow" } },
    legend: {
      top: 0,
      textStyle: { color: "#9ca3af", fontSize: 11 },
      itemWidth: 10,
      itemHeight: 10,
    },
    grid: { left: 104, right: 18, top: 44, bottom: 26 },
    xAxis: {
      type: "value",
      axisLabel: { color: "#6b7280" },
      splitLine: { lineStyle: { color: "rgba(75, 85, 99, 0.28)" } },
    },
    yAxis: {
      type: "category",
      data: competitors,
      axisLabel: { color: "#d1d5db", width: 90, overflow: "truncate" },
      axisLine: { lineStyle: { color: "#374151" } },
      axisTick: { show: false },
    },
    series: dashboard.sourceTypes.map((source) => ({
      name: source,
      type: "bar",
      stack: "evidence",
      emphasis: { focus: "series" },
      data: dashboard.evidenceByCompetitor.map((row) => row.sources[source] ?? 0),
    })),
  };
}

function buildClaimStatusOption(dashboard: DashboardData): EChartsOption {
  return {
    color: dashboard.claimStatusSegments.map((segment) => segment.color),
    tooltip: { ...tooltipStyle, trigger: "item" },
    legend: {
      orient: "vertical",
      right: 0,
      top: "middle",
      textStyle: { color: "#9ca3af", fontSize: 12 },
    },
    graphic: [
      {
        type: "text",
        left: "29%",
        top: "44%",
        style: {
          text: `${dashboard.supportRate}%`,
          fill: "#f3f4f6",
          fontSize: 28,
          fontWeight: 700,
          textAlign: "center",
        },
      },
      {
        type: "text",
        left: "29%",
        top: "55%",
        style: {
          text: "可采纳",
          fill: "#6b7280",
          fontSize: 12,
          textAlign: "center",
        },
      },
    ],
    series: [
      {
        name: "声明验证",
        type: "pie",
        radius: ["46%", "72%"],
        center: ["34%", "52%"],
        avoidLabelOverlap: true,
        label: { color: "#d1d5db", formatter: "{b}: {c}" },
        labelLine: { lineStyle: { color: "#4b5563" } },
        data: dashboard.claimStatusSegments.map((segment) => ({
          name: segment.label,
          value: segment.value,
        })),
      },
    ],
  };
}

function buildHeatmapOption(dashboard: DashboardData): EChartsOption {
  const data = dashboard.heatmapRows.flatMap((row, rowIndex) =>
    dashboard.heatmapDimensions.map((dimension, columnIndex) => {
      const score = row.scores[dimension];
      return [columnIndex, rowIndex, score == null ? 0 : Math.round(score * 100)];
    }),
  );

  return {
    tooltip: {
      ...tooltipStyle,
      position: "top",
      formatter: (params: any) => {
        const value = Array.isArray(params.value) ? params.value : [];
        const dimension = dashboard.heatmapDimensions[value[0]] ?? "";
        const competitor = dashboard.heatmapRows[value[1]]?.competitor ?? "";
        return `${competitor}<br/>${dimension}: ${value[2]}%`;
      },
    },
    grid: { left: 112, right: 24, top: 28, bottom: 62 },
    xAxis: {
      type: "category",
      data: dashboard.heatmapDimensions,
      axisLabel: { color: "#9ca3af", interval: 0, rotate: 24 },
      axisLine: { lineStyle: { color: "#374151" } },
      axisTick: { show: false },
    },
    yAxis: {
      type: "category",
      data: dashboard.heatmapRows.map((row) => row.competitor),
      axisLabel: { color: "#d1d5db", width: 96, overflow: "truncate" },
      axisLine: { lineStyle: { color: "#374151" } },
      axisTick: { show: false },
    },
    visualMap: {
      min: 0,
      max: 100,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      inRange: { color: ["#111827", "#0f766e", "#5eead4"] },
      textStyle: { color: "#9ca3af" },
    },
    series: [
      {
        name: "信心",
        type: "heatmap",
        data,
        label: { show: true, color: "#f9fafb", formatter: ({ value }: any) => `${value[2]}%` },
        emphasis: {
          itemStyle: {
            shadowBlur: 12,
            shadowColor: "rgba(45, 212, 191, 0.35)",
          },
        },
      },
    ],
  };
}

function buildPipelineOption(dashboard: DashboardData): EChartsOption {
  return {
    color: ["#2dd4bf"],
    tooltip: { ...tooltipStyle, trigger: "item", formatter: "{b}: {c}" },
    series: [
      {
        name: "Agent 流水线",
        type: "funnel",
        left: "4%",
        top: 8,
        bottom: 8,
        width: "88%",
        minSize: "18%",
        maxSize: "100%",
        sort: "none",
        gap: 3,
        label: { color: "#e5e7eb", formatter: "{b}  {c}" },
        labelLine: { show: false },
        itemStyle: { borderColor: "#0C111F", borderWidth: 1 },
        data: dashboard.pipeline.map((item) => ({
          name: item.label,
          value: item.value,
        })),
      },
    ],
  };
}

function diffToneClassName(tone: "teal" | "blue" | "amber" | "gray") {
  const classes = {
    teal: "border-teal-500/30 bg-teal-500/10",
    blue: "border-sky-500/30 bg-sky-500/10",
    amber: "border-amber-500/30 bg-amber-500/10",
    gray: "border-gray-800 bg-gray-950/40",
  };
  return classes[tone];
}

function findPreviousRun(history: ReportRecord[], selectedRun: ReportRecord) {
  const hasTimestamps = history.some((item) => typeof item.timestamp === "number");
  const ordered = hasTimestamps
    ? [...history].sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0))
    : history;
  const index = ordered.findIndex((item) => item.id === selectedRun.id);
  if (index < 0) {
    return ordered.find((item) => item.id !== selectedRun.id) ?? null;
  }
  return (ordered[index + 1] as ReportRecord | undefined) ?? null;
}

function buildRunDiff(currentRun: ReportRecord, previousRun: ReportRecord | null): RunDiffData {
  const currentSources = buildSourceDiffItems(currentRun);
  const currentClaims = buildNormalizedClaimMap(currentRun);

  if (!previousRun) {
    return {
      previousRun: null,
      summaries: [
        {
          label: "当前来源",
          value: String(currentSources.length),
          detail: "等待下一次运行后对比",
          tone: "teal",
        },
        {
          label: "当前结论",
          value: String(currentClaims.size),
          detail: "等待下一次运行后对比",
          tone: "blue",
        },
        {
          label: "变化结论",
          value: "0",
          detail: "暂无历史基线",
          tone: "gray",
        },
        {
          label: "平均信心变化",
          value: "--",
          detail: "暂无历史基线",
          tone: "gray",
        },
      ],
      addedSources: [],
      addedClaims: [],
      changedClaims: [],
    };
  }

  const previousSources = new Map(
    buildSourceDiffItems(previousRun).map((source) => [source.key, source]),
  );
  const previousClaims = buildNormalizedClaimMap(previousRun);
  const addedSources = currentSources.filter((source) => !previousSources.has(source.key));
  const addedClaims = Array.from(currentClaims.values())
    .filter((claim) => !previousClaims.has(claim.key))
    .map(toClaimDiffItem);
  const changedClaims = Array.from(currentClaims.values()).flatMap((claim) => {
    const previous = previousClaims.get(claim.key);
    if (!previous) {
      return [];
    }
    const confidenceChanged =
      claim.confidence !== null &&
      previous.confidence !== null &&
      Math.abs(claim.confidence - previous.confidence) >= 0.05;
    const statusChanged = claim.status !== previous.status;
    const evidenceChanged = claim.evidenceCount !== previous.evidenceCount;
    if (!confidenceChanged && !statusChanged && !evidenceChanged) {
      return [];
    }
    return [
      {
        ...toClaimDiffItem(claim),
        previousStatus: statusLabel(previous.status),
        currentStatus: statusLabel(claim.status),
        previousConfidence: previous.confidence,
        currentConfidence: claim.confidence,
      },
    ];
  });
  const currentAvgConfidence = average(Array.from(currentClaims.values()).map((claim) => claim.confidence));
  const previousAvgConfidence = average(Array.from(previousClaims.values()).map((claim) => claim.confidence));
  const confidenceDelta =
    currentAvgConfidence !== null && previousAvgConfidence !== null
      ? currentAvgConfidence - previousAvgConfidence
      : null;

  return {
    previousRun,
    summaries: [
      {
        label: "新增来源",
        value: `+${addedSources.length}`,
        detail: `${currentSources.length} 条当前来源`,
        tone: "teal",
      },
      {
        label: "新增结论",
        value: `+${addedClaims.length}`,
        detail: `${currentClaims.size} 条当前结论`,
        tone: "blue",
      },
      {
        label: "变化结论",
        value: String(changedClaims.length),
        detail: "状态、信心或证据数量变化",
        tone: changedClaims.length ? "amber" : "gray",
      },
      {
        label: "平均信心变化",
        value: confidenceDelta === null ? "--" : formatSignedPercent(confidenceDelta),
        detail: previousAvgConfidence === null ? "上一轮缺少信心数据" : "相对上一轮",
        tone: confidenceDelta !== null && confidenceDelta < 0 ? "amber" : "teal",
      },
    ],
    addedSources,
    addedClaims,
    changedClaims,
  };
}

function buildClaimExplorerItems(report: ReportRecord): ClaimExplorerItem[] {
  const { claims, dimensions, reviews, evidenceById } = collectTraceableRows(report);
  const reviewByClaimId = buildReviewByClaimId(reviews);

  return claims.map((claim, index) => {
    const claimId = getClaimId(claim) || `claim-${index}`;
    const review = reviewByClaimId.get(claimId);
    const evidenceIds = getClaimEvidenceIds(claim, review);
    const sourceUrls = uniqueStrings(
      evidenceIds
        .map((id) => evidenceById.get(id))
        .map((evidence) => getEvidenceUrl(evidence || {})),
    );
    const status = getClaimStatus(claim, review);
    return {
      id: claimId,
      text: getClaimText(claim),
      dimension: toDisplayDimension(getDimensionName(claim, dimensions)),
      competitors: getClaimCompetitors(claim),
      status,
      statusLabel: statusLabel(status),
      confidence: getClaimConfidence(claim, review),
      evidenceCount: evidenceIds.length,
      sourceCount: sourceUrls.length,
    };
  });
}

function buildTraceGraphGroups(report: ReportRecord): TraceGraphGroup[] {
  const { claims, dimensions, reviews, evidence, evidenceById } = collectTraceableRows(report);
  const reviewByClaimId = buildReviewByClaimId(reviews);
  const grouped = new Map<string, Map<string, TraceGraphClaim[]>>();

  claims.forEach((claim, index) => {
    const claimId = getClaimId(claim) || `claim-${index}`;
    const review = reviewByClaimId.get(claimId);
    const competitors = getClaimCompetitors(claim);
    const competitor = competitors[0] || "整体";
    const dimension = toDisplayDimension(getDimensionName(claim, dimensions));
    const evidenceIds = getClaimEvidenceIds(claim, review);
    const relatedEvidence = evidenceIds
      .map((id) => evidenceById.get(id))
      .filter((item): item is Row => Boolean(item));
    const fallbackEvidence = relatedEvidence.length
      ? []
      : evidence
          .filter(
            (item) =>
              getCompetitor(item) === competitor &&
              toDisplayDimension(getDimensionName(item, dimensions)) === dimension,
          )
          .slice(0, 2);
    const graphClaim: TraceGraphClaim = {
      id: claimId,
      text: getClaimText(claim),
      statusLabel: statusLabel(getClaimStatus(claim, review)),
      evidence: [...relatedEvidence, ...fallbackEvidence].slice(0, 3).map(toTraceGraphEvidence),
    };
    const dimensionMap = grouped.get(competitor) ?? new Map<string, TraceGraphClaim[]>();
    const dimensionClaims = dimensionMap.get(dimension) ?? [];
    dimensionClaims.push(graphClaim);
    dimensionMap.set(dimension, dimensionClaims);
    grouped.set(competitor, dimensionMap);
  });

  return Array.from(grouped.entries())
    .slice(0, 5)
    .map(([competitor, dimensionMap]) => ({
      competitor,
      dimensions: Array.from(dimensionMap.entries())
        .slice(0, 4)
        .map(([dimension, dimensionClaims]) => ({
          dimension,
          claims: dimensionClaims.slice(0, 3),
        })),
    }));
}

function collectTraceableRows(report: ReportRecord) {
  const evidence = collectRows(report, ["evidence_index", "evidence_items"]);
  const claims = collectRows(report, ["analysis_claims"]);
  const reviews = collectRows(report, ["claim_support_reviews"]);
  const dimensions = collectRows(report, ["analysis_dimensions"]);
  const evidenceById = new Map(
    evidence.map((item, index) => [getEvidenceId(item) || `evidence-${index}`, item]),
  );

  return { evidence, claims, reviews, dimensions, evidenceById };
}

function buildSourceDiffItems(report: ReportRecord): SourceDiffItem[] {
  const evidence = collectRows(report, ["evidence_index", "evidence_items"]);
  const items = evidence.map((item, index) => {
    const url = getEvidenceUrl(item);
    const key = normalizeKey(url || getEvidenceId(item) || String(index));
    return {
      key,
      title: getEvidenceTitle(item),
      url,
      sourceType: formatSourceType(getSourceType(item)),
    };
  });
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.key)) {
      return false;
    }
    seen.add(item.key);
    return true;
  });
}

function buildNormalizedClaimMap(report: ReportRecord) {
  const { claims, dimensions, reviews } = collectTraceableRows(report);
  const reviewByClaimId = buildReviewByClaimId(reviews);
  const result = new Map<
    string,
    ClaimDiffItem & {
      status: string;
      confidence: number | null;
      evidenceCount: number;
    }
  >();

  claims.forEach((claim, index) => {
    const claimId = getClaimId(claim) || `claim-${index}`;
    const review = reviewByClaimId.get(claimId);
    const text = getClaimText(claim);
    const key = normalizeClaimKey(text);
    result.set(key, {
      key,
      text,
      dimension: toDisplayDimension(getDimensionName(claim, dimensions)),
      competitors: getClaimCompetitors(claim),
      status: getClaimStatus(claim, review),
      confidence: getClaimConfidence(claim, review),
      evidenceCount: getClaimEvidenceIds(claim, review).length,
    });
  });

  return result;
}

function toClaimDiffItem(
  item: ClaimDiffItem & { status?: string; confidence?: number | null; evidenceCount?: number },
): ClaimDiffItem {
  return {
    key: item.key,
    text: item.text,
    dimension: item.dimension,
    competitors: item.competitors,
  };
}

function buildReviewByClaimId(reviews: Row[]) {
  return new Map(
    reviews
      .map((review) => [stringValue(review.claim_id || review.claimId), review] as const)
      .filter(([claimId]) => Boolean(claimId)),
  );
}

function buildDashboard(report: ReportRecord): DashboardData {
  const evidence = collectRows(report, ["evidence_index", "evidence_items"]);
  const claims = collectRows(report, ["analysis_claims"]);
  const reviews = collectRows(report, ["claim_support_reviews"]);
  const knowledge = collectRows(report, ["competitor_knowledge"]);
  const dimensions = collectRows(report, ["analysis_dimensions"]);
  const branches = collectRows(report, ["research_branches"]);
  const tasks = collectRows(report, ["research_tasks"]);
  const facts = collectRows(report, ["knowledge_facts", "knowledge_fact_packages"]);
  const artifacts = objectSize(report.report_artifacts ?? report.artifacts);

  const competitors = uniqueStrings([
    ...evidence.map(getCompetitor),
    ...knowledge.map(getCompetitor),
    ...claims.flatMap((claim) =>
      Array.isArray(claim.competitors) ? claim.competitors : [getCompetitor(claim)],
    ),
  ]).filter((item) => item !== "整体");

  const supportCounts = countSupportStatuses(reviews);
  const reviewedCount = reviews.length;
  const acceptedCount =
    (supportCounts.supported ?? 0) +
    (supportCounts.supported_with_limitations ?? 0);
  const supportRate =
    reviewedCount > 0 ? Math.round((acceptedCount / reviewedCount) * 100) : 0;
  const avgConfidence = average([
    ...evidence.map((item) => toScore(item.confidence)),
    ...claims.map((item) => toScore(item.confidence)),
    ...reviews.map((item) => toScore(item.confidence)),
  ]);

  return {
    hasStructuredData:
      evidence.length + claims.length + reviews.length + knowledge.length + dimensions.length > 0,
    metrics: [
      {
        label: "证据",
        value: String(evidence.length),
        detail: `${countPrimarySources(evidence)} 个一手来源`,
      },
      {
        label: "声明",
        value: String(claims.length),
        detail: `${reviewedCount} 条完成质量复核`,
      },
      {
        label: "可采纳率",
        value: `${supportRate}%`,
        detail: `${acceptedCount}/${reviewedCount || 0} 条声明可采纳`,
      },
      {
        label: "平均信心",
        value: avgConfidence == null ? "--" : `${Math.round(avgConfidence * 100)}%`,
        detail: `${competitors.length || 0} 个竞品参与对比`,
      },
    ],
    evidenceByCompetitor: buildEvidenceBars(evidence),
    sourceTypes: buildTopSourceTypes(evidence),
    claimStatusSegments: buildClaimStatusSegments(supportCounts, claims.length),
    supportRate,
    heatmapDimensions: buildHeatmapDimensions(evidence, dimensions),
    heatmapRows: buildHeatmapRows(evidence, dimensions),
    pipeline: PIPELINE_STEPS.map((label) => {
      const values: Record<string, number> = {
        Planning: dimensions.length,
        Collection: evidence.length || tasks.length || branches.length,
        Structuring: knowledge.length || facts.length,
        Analysis: claims.length,
        "Claim Review": reviews.length,
        Writing: report.answer ? 1 : 0,
        Publishing: artifacts,
      };
      return { label, value: values[label] ?? 0 };
    }),
  };
}

function collectRows(report: ReportRecord, keys: string[]): Row[] {
  const state = asRecord(report.state);
  const provenance = asRecord(state?.provenance);
  const result: Row[] = [];

  for (const key of keys) {
    result.push(...asRows(report[key]));
    result.push(...asRows(state?.[key]));
    result.push(...asRows(provenance?.[key]));
  }

  return dedupeRows(result);
}

function asRecord(value: unknown): Row | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Row;
  }
  return null;
}

function asRows(value: unknown): Row[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is Row => Boolean(asRecord(item)));
}

function dedupeRows(rows: Row[]): Row[] {
  const seen = new Set<string>();
  const result: Row[] = [];

  rows.forEach((row, index) => {
    const key = String(row.id || row.claim_id || row.url || row.canonical_url || index);
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    result.push(row);
  });

  return result;
}

function buildEvidenceBars(evidence: Row[]) {
  const sourceTypes = buildTopSourceTypes(evidence);
  const byCompetitor = new Map<string, { total: number; sources: Record<string, number> }>();

  evidence.forEach((item) => {
    const competitor = getCompetitor(item);
    const sourceType = sourceTypes.includes(getSourceType(item)) ? getSourceType(item) : "other";
    const current = byCompetitor.get(competitor) ?? { total: 0, sources: {} };
    current.total += 1;
    current.sources[sourceType] = (current.sources[sourceType] ?? 0) + 1;
    byCompetitor.set(competitor, current);
  });

  return Array.from(byCompetitor.entries())
    .map(([competitor, data]) => ({ competitor, ...data }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 8);
}

function buildTopSourceTypes(evidence: Row[]) {
  const counts = countBy(evidence.map(getSourceType));
  const top = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([source]) => source);

  return top.length < Object.keys(counts).length ? [...top, "other"] : top;
}

function buildClaimStatusSegments(
  counts: Record<string, number>,
  claimCount: number,
): StatusSegment[] {
  const reviewedTotal = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const unreviewed = Math.max(claimCount - reviewedTotal, 0);
  const keys = [
    "supported",
    "supported_with_limitations",
    "weak",
    "contradicted",
    "unverifiable",
  ];

  const segments = keys.map((key) => ({
    key,
    label: STATUS_LABELS[key],
    value: counts[key] ?? 0,
    color: STATUS_COLORS[key],
  }));

  if (unreviewed > 0) {
    segments.push({
      key: "unreviewed",
      label: STATUS_LABELS.unreviewed,
      value: unreviewed,
      color: STATUS_COLORS.unreviewed,
    });
  }

  return segments.filter((segment) => segment.value > 0);
}

function buildHeatmapDimensions(evidence: Row[], dimensions: Row[]) {
  const dimensionNames = [
    ...dimensions.map((item) => stringValue(item.name || item.direction_name || item.id)),
    ...evidence.map((item) => getDimensionName(item, dimensions)),
  ];
  return uniqueStrings(dimensionNames).slice(0, 6);
}

function buildHeatmapRows(evidence: Row[], dimensions: Row[]) {
  const dimensionNames = buildHeatmapDimensions(evidence, dimensions);
  const competitors = uniqueStrings(evidence.map(getCompetitor)).slice(0, 8);

  return competitors.map((competitor) => {
    const scores: Record<string, number | null> = {};
    dimensionNames.forEach((dimension) => {
      const matching = evidence.filter(
        (item) =>
          getCompetitor(item) === competitor &&
          getDimensionName(item, dimensions) === dimension,
      );
      scores[dimension] = average(matching.map((item) => toScore(item.confidence)));
    });
    return { competitor, scores };
  });
}

function countSupportStatuses(reviews: Row[]) {
  return countBy(
    reviews.map((review) =>
      stringValue(review.support_status || review.status || "unreviewed").toLowerCase(),
    ),
  );
}

function countPrimarySources(evidence: Row[]) {
  return evidence.filter(
    (item) =>
      item.is_primary_source === true ||
      ["official_site", "pricing_page", "docs", "financial_filing", "public_registry"].includes(
        getSourceType(item),
      ),
  ).length;
}

function getCompetitor(item: Row) {
  if (Array.isArray(item.competitors) && item.competitors.length > 0) {
    return stringValue(item.competitors[0]) || "整体";
  }
  return stringValue(
    item.competitor ||
      item.competitor_name ||
      item.target_competitor ||
      item.company ||
      "整体",
  );
}

function getSourceType(item: Row) {
  return stringValue(item.source_type || item.source_category || item.source_kind || "other");
}

function getDimensionName(item: Row, dimensions: Row[]) {
  const explicit = stringValue(item.dimension_name || item.direction_name || item.dimension);
  if (explicit) {
    return explicit;
  }

  const dimensionId = stringValue(item.analysis_dimension_id || item.dimension_id);
  if (!dimensionId) {
    return "未归类";
  }

  const dimension = dimensions.find(
    (candidate) =>
      stringValue(candidate.id) === dimensionId ||
      stringValue(candidate.direction_id) === dimensionId,
  );
  return stringValue(dimension?.name || dimension?.direction_name || dimensionId);
}

function getClaimId(claim: Row) {
  return stringValue(claim.id || claim.claim_id || claim.claimId);
}

function getClaimText(claim: Row) {
  return (
    stringValue(claim.claim || claim.text || claim.statement || claim.title || claim.summary) ||
    "未命名结论"
  );
}

function getClaimCompetitors(claim: Row) {
  if (Array.isArray(claim.competitors)) {
    return uniqueStrings(claim.competitors.map((item) => String(item || ""))).slice(0, 4);
  }
  return uniqueStrings([
    stringValue(claim.competitor),
    stringValue(claim.competitor_name),
    stringValue(claim.company),
  ]).slice(0, 4);
}

function getClaimEvidenceIds(claim: Row, review?: Row) {
  const values = [
    ...(Array.isArray(claim.evidence_ids) ? claim.evidence_ids : []),
    ...(Array.isArray(claim.evidenceIds) ? claim.evidenceIds : []),
    ...(Array.isArray(review?.evidence_ids) ? review?.evidence_ids : []),
    ...(Array.isArray(review?.evidenceIds) ? review?.evidenceIds : []),
  ];
  return uniqueStrings(values.map((value) => String(value || "")));
}

function getClaimStatus(claim: Row, review?: Row) {
  return stringValue(review?.support_status || review?.status || claim.support_status || claim.status || "unreviewed").toLowerCase();
}

function getClaimConfidence(claim: Row, review?: Row) {
  return toScore(claim.confidence) ?? toScore(review?.confidence);
}

function getEvidenceId(evidence: Row) {
  return stringValue(evidence.id || evidence.evidence_id || evidence.evidenceId);
}

function getEvidenceUrl(evidence: Row) {
  return stringValue(evidence.url || evidence.source_url || evidence.canonical_url || evidence.metadata?.url);
}

function getEvidenceTitle(evidence: Row) {
  const url = getEvidenceUrl(evidence);
  return (
    stringValue(evidence.title || evidence.source_title || evidence.name || evidence.snippet) ||
    sourceNameFromUrl(url) ||
    formatEvidenceReference(getEvidenceId(evidence))
  );
}

function toTraceGraphEvidence(evidence: Row): TraceGraphEvidence {
  return {
    id: getEvidenceId(evidence) || getEvidenceTitle(evidence),
    title: getEvidenceTitle(evidence),
    url: getEvidenceUrl(evidence),
    sourceType: formatSourceType(getSourceType(evidence)),
  };
}

function statusLabel(status: string) {
  const normalized = stringValue(status).toLowerCase();
  return STATUS_LABELS[normalized] || normalized.replace(/_/g, " ") || "未复核";
}

function formatSourceType(sourceType: string) {
  const labels: Record<string, string> = {
    official_site: "官网",
    pricing_page: "价格页",
    docs: "产品文档",
    financial_filing: "财务披露",
    public_registry: "公开登记",
    news: "新闻报道",
    social: "社交媒体",
    review: "用户评价",
    other: "其他来源",
  };
  const normalized = sourceType.toLowerCase();
  return labels[normalized] || normalized.replace(/_/g, " ") || "其他来源";
}

function sourceNameFromUrl(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function toDisplayDimension(value: string) {
  const normalized = stringValue(value);
  return DIRECTION_LABELS[normalized] || normalized.replace(/_/g, " ") || "未归类";
}

function normalizeKey(value: string) {
  return value.trim().toLowerCase();
}

function normalizeClaimKey(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ")
    .slice(0, 220);
}

function formatConfidence(value: number | null) {
  return value === null ? "暂无" : `${Math.round(value * 100)}%`;
}

function formatSignedPercent(value: number) {
  const rounded = Math.round(value * 100);
  return `${rounded >= 0 ? "+" : ""}${rounded}%`;
}

function confidenceChangeText(previous: number | null, current: number | null) {
  if (previous === null || current === null) {
    return "信心数据不完整";
  }
  return `${formatConfidence(previous)} → ${formatConfidence(current)}`;
}

function formatClaimReference(claimId: string) {
  const numericId = claimId.match(/\d+/)?.[0];
  return numericId ? `第 ${numericId} 条` : "结论";
}

function formatEvidenceReference(evidenceId: string) {
  const numericId = evidenceId.match(/\d+/)?.[0];
  return numericId ? `第 ${numericId} 条来源` : "未命名来源";
}

function countBy(items: string[]) {
  return items.reduce<Record<string, number>>((acc, item) => {
    const key = item || "unknown";
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});
}

function average(values: Array<number | null>) {
  const valid = values.filter((value): value is number => typeof value === "number");
  if (valid.length === 0) {
    return null;
  }
  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
}

function toScore(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  if (value > 1) {
    return Math.max(0, Math.min(value / 100, 1));
  }
  return Math.max(0, Math.min(value, 1));
}

function uniqueStrings(values: string[]) {
  return Array.from(
    new Set(values.map((value) => stringValue(value)).filter(Boolean)),
  );
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function objectSize(value: unknown) {
  if (!value || typeof value !== "object") {
    return 0;
  }
  return Object.keys(value).length;
}

function formatDate(timestamp?: number) {
  if (!timestamp) {
    return "暂无时间";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

function formatRunReference(id?: string) {
  const value = stringValue(id);
  if (!value) {
    return "暂无编号";
  }

  const readableId = value.match(/task_\d+_([a-z0-9]+)$/i)?.[1] || value.slice(-8);
  return readableId.toUpperCase();
}
