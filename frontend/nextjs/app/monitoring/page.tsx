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
                <span className="text-xs text-gray-500">{history.length} runs</span>
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
                      <p className="mt-2 truncate text-xs text-gray-500">{run.id}</p>
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

              <section className="grid gap-5 xl:grid-cols-[1.4fr_0.9fr]">
                <EvidenceStackedBars dashboard={dashboard} />
                <ClaimStatusDonut dashboard={dashboard} />
              </section>

              <section className="grid gap-5 xl:grid-cols-[1.2fr_0.9fr]">
                <ConfidenceHeatmap dashboard={dashboard} />
                <PipelineFunnel dashboard={dashboard} />
              </section>
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
          <p className="mt-2 break-all text-xs text-gray-500">Run ID: {run.id}</p>
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
        <EmptyPanelText text="当前运行暂无 evidence_index 或 evidence_items。" />
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
      {status || "unknown"}
    </span>
  );
}

function EmptyDashboard() {
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-10 text-center">
      <h2 className="text-lg font-semibold text-gray-100">暂无运行数据</h2>
      <p className="mx-auto mt-2 max-w-xl text-sm text-gray-500">
        完成一次竞品分析后，这里会自动出现对应 run 的证据、声明、质量复核和 Agent 流水线看板。
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
