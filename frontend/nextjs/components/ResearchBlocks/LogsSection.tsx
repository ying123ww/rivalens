import { useMemo } from "react";
import { ResearchHistoryItem } from "@/types/data";

interface Log {
  header: string;
  text: string;
  metadata: any;
  key: string;
}

interface OrderedLogsProps {
  logs: Log[];
  reportContext?: Partial<ResearchHistoryItem> | Record<string, any> | null;
  isResearching?: boolean;
}

type GenericRecord = Record<string, any>;
type TimelineStatus = "completed" | "active" | "pending";

const WEAK_SUPPORT_STATUSES = new Set([
  "weak",
  "unverifiable",
  "contradicted",
  "unsupported",
  "insufficient",
]);

const SUPPORT_STATUS_LABELS: Record<string, string> = {
  supported: "Supported",
  weak: "Weak",
  unverifiable: "Unverifiable",
  contradicted: "Contradicted",
  unsupported: "Unsupported",
  insufficient: "Insufficient",
};

const asArray = (value: unknown): GenericRecord[] =>
  Array.isArray(value) ? value.filter((item) => item && typeof item === "object") : [];

const uniqueCount = (values: unknown[]) =>
  new Set(values.map((value) => String(value || "").trim()).filter(Boolean)).size;

const truncateText = (value: unknown, limit = 120) => {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, limit - 3).trim()}...`;
};

const getContextArray = (
  context: GenericRecord | null | undefined,
  key: string,
  assessmentKey?: string,
) => {
  if (!context) return [];

  const direct = asArray(context[key]);
  if (direct.length) return direct;

  const state = context.state && typeof context.state === "object" ? context.state : {};
  const stateValue = asArray(state[key]);
  if (stateValue.length) return stateValue;

  const assessments =
    context.assessments && typeof context.assessments === "object" ? context.assessments : {};
  return asArray(assessments[assessmentKey || key]);
};

const getEvidenceItems = (context: GenericRecord | null | undefined) => {
  const evidenceIndex = getContextArray(context, "evidence_index");
  if (evidenceIndex.length) return evidenceIndex;
  return getContextArray(context, "evidence_items");
};

const getTraceEvents = (context: GenericRecord | null | undefined) => {
  const traceSummary =
    context?.trace_summary && typeof context.trace_summary === "object"
      ? context.trace_summary
      : {};
  return asArray(traceSummary.latest_events);
};

const getTraceAgents = (context: GenericRecord | null | undefined) => {
  const traceSummary =
    context?.trace_summary && typeof context.trace_summary === "object"
      ? context.trace_summary
      : {};
  const agents = Array.isArray(traceSummary.agents) ? traceSummary.agents : [];
  return agents.map((agent: unknown) => String(agent || "")).filter(Boolean);
};

const getClaimId = (claim: GenericRecord) => String(claim.id || claim.claim_id || "");

const getEvidenceIds = (item: GenericRecord) =>
  Array.isArray(item.evidence_ids)
    ? item.evidence_ids.map((id: unknown) => String(id || "")).filter(Boolean)
    : [];

const getConfidence = (item: GenericRecord) => {
  const numeric = Number(item.confidence);
  return Number.isFinite(numeric) ? numeric : null;
};

const buildWeakReviewItems = (claims: GenericRecord[], reviews: GenericRecord[]) => {
  const claimsById = new Map(claims.map((claim) => [getClaimId(claim), claim]));
  const reviewItems = reviews
    .filter((review) => WEAK_SUPPORT_STATUSES.has(String(review.support_status || "").toLowerCase()))
    .map((review) => {
      const claim = claimsById.get(String(review.claim_id || "")) || {};
      return {
        id: String(review.id || review.claim_id || claim.id || ""),
        claimId: String(review.claim_id || claim.id || ""),
        status: String(review.support_status || "needs_review").toLowerCase(),
        text: truncateText(claim.claim || review.reviewer_notes || "Claim needs review", 150),
        evidenceIds: getEvidenceIds(review).length ? getEvidenceIds(review) : getEvidenceIds(claim),
        note: truncateText(review.reviewer_notes || review.unsupported_phrases?.join(", "), 160),
      };
    });

  const claimItems = claims
    .filter((claim) => {
      const confidence = getConfidence(claim);
      return getEvidenceIds(claim).length === 0 || (confidence !== null && confidence < 0.45);
    })
    .map((claim) => ({
      id: getClaimId(claim),
      claimId: getClaimId(claim),
      status: getEvidenceIds(claim).length === 0 ? "missing_evidence" : "low_confidence",
      text: truncateText(claim.claim || "Claim needs review", 150),
      evidenceIds: getEvidenceIds(claim),
      note:
        getEvidenceIds(claim).length === 0
          ? "No evidence id is attached."
          : `Confidence ${Math.round((getConfidence(claim) || 0) * 100)}%.`,
    }));

  const seen = new Set<string>();
  return [...reviewItems, ...claimItems].filter((item) => {
    const key = item.claimId || item.id || item.text;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
};

const statusClassName = (status: TimelineStatus) => {
  if (status === "completed") return "border-emerald-400 bg-emerald-400";
  if (status === "active") return "border-sky-300 bg-sky-300";
  return "border-gray-600 bg-gray-950";
};

const metricAccentClassName = (index: number) => {
  const classes = [
    "text-sky-200",
    "text-emerald-200",
    "text-amber-200",
    "text-rose-200",
  ];
  return classes[index % classes.length];
};

const statusLabel = (status: string) =>
  SUPPORT_STATUS_LABELS[status] || status.replace(/_/g, " ");

const buildTimeline = ({
  context,
  logs,
  evidenceItems,
  claims,
  reviews,
  isResearching,
}: {
  context: GenericRecord | null | undefined;
  logs: Log[];
  evidenceItems: GenericRecord[];
  claims: GenericRecord[];
  reviews: GenericRecord[];
  isResearching: boolean;
}) => {
  const traceEvents = getTraceEvents(context);
  const traceAgents = getTraceAgents(context);
  const traceText = [
    ...traceAgents,
    ...traceEvents.map((event) => `${event.agent || ""} ${event.event || ""} ${event.node || ""}`),
    ...logs.map((log) => `${log.header} ${log.text}`),
  ]
    .join(" ")
    .toLowerCase();
  const state = context?.state && typeof context.state === "object" ? context.state : {};
  const hasArtifacts = Boolean(
    context?.report_artifacts ||
      context?.artifacts ||
      state.published_artifacts ||
      logs.some((log) => log.header === "path"),
  );
  const hasReport = Boolean(context?.answer || context?.report || state.report);
  const hasKnowledge = getContextArray(context, "competitor_knowledge").length > 0 ||
    getContextArray(context, "knowledge_facts").length > 0;
  const hasDimensions = asArray(state.analysis_dimensions).length > 0;
  const hasText = (tokens: string[]) => tokens.some((token) => traceText.includes(token));
  const step = (
    label: string,
    done: boolean,
    activeTokens: string[],
    detail: string,
  ): { label: string; detail: string; status: TimelineStatus } => ({
    label,
    detail,
    status: done ? "completed" : isResearching && hasText(activeTokens) ? "active" : "pending",
  });

  return [
    step(
      "Planning",
      hasText(["planning", "planningagent"]) || traceEvents.length > 0,
      ["starting", "planning"],
      traceEvents.length ? `${traceEvents.length} trace events captured` : "Research direction initialized",
    ),
    step(
      "Schema Selection",
      hasDimensions || hasText(["schema"]),
      ["schema"],
      hasDimensions ? `${asArray(state.analysis_dimensions).length} dimensions selected` : "Schema route pending",
    ),
    step(
      "Collection",
      evidenceItems.length > 0 || hasText(["collection", "evidence", "added_source_url"]),
      ["collection", "source", "evidence"],
      evidenceItems.length ? `${evidenceItems.length} evidence items collected` : "Collecting public evidence",
    ),
    step(
      "Knowledge Structuring",
      hasKnowledge || hasText(["knowledge"]),
      ["knowledge", "structuring"],
      hasKnowledge ? "Competitor knowledge extracted" : "Waiting for structured facts",
    ),
    step(
      "Analysis",
      claims.length > 0 || hasText(["analysis"]),
      ["analysis", "claim"],
      claims.length ? `${claims.length} claims generated` : "Claims not available yet",
    ),
    step(
      "Quality Review",
      reviews.length > 0 || hasText(["review", "quality"]),
      ["review", "quality"],
      reviews.length ? `${reviews.length} claim support reviews` : "Evidence review pending",
    ),
    step(
      "Writing & Publishing",
      hasReport || hasArtifacts,
      ["writing", "publish", "path"],
      hasArtifacts ? "Report artifacts available" : hasReport ? "Report text available" : "Report output pending",
    ),
  ];
};

const LogsSection = ({
  logs,
  reportContext,
  isResearching = false,
}: OrderedLogsProps) => {
  const context = reportContext as GenericRecord | null | undefined;
  const summary = useMemo(() => {
    const evidenceItems = getEvidenceItems(context);
    const claims = getContextArray(context, "analysis_claims");
    const reviews = getContextArray(context, "claim_support_reviews");
    const weakItems = buildWeakReviewItems(claims, reviews);
    const sourceCount = uniqueCount(
      evidenceItems.map((item) => item.url || item.source_url || item.metadata?.url),
    );
    const supportedCount = reviews.filter(
      (review) => String(review.support_status || "").toLowerCase() === "supported",
    ).length;
    const primarySourceCount = evidenceItems.filter((item) => item.is_primary_source).length;
    const timeline = buildTimeline({
      context,
      logs,
      evidenceItems,
      claims,
      reviews,
      isResearching,
    });

    return {
      evidenceItems,
      claims,
      reviews,
      weakItems,
      sourceCount,
      supportedCount,
      primarySourceCount,
      timeline,
      hasStructuredEvidence: evidenceItems.length > 0 || claims.length > 0 || reviews.length > 0,
    };
  }, [context, logs, isResearching]);

  const metrics = [
    {
      label: "Evidence Items",
      value: summary.hasStructuredEvidence ? summary.evidenceItems.length : "-",
      detail: `${summary.sourceCount} source URLs`,
    },
    {
      label: "Analysis Claims",
      value: summary.hasStructuredEvidence ? summary.claims.length : "-",
      detail: `${summary.supportedCount} supported`,
    },
    {
      label: "Needs Review",
      value: summary.hasStructuredEvidence ? summary.weakItems.length : "-",
      detail: summary.weakItems.length ? "Evidence gap found" : "No current flags",
    },
    {
      label: "Primary Sources",
      value: summary.hasStructuredEvidence ? summary.primarySourceCount : "-",
      detail: "Official or first-party",
    },
  ];
  const recentLogs = logs.slice(-6).reverse();
  const panelStatus = summary.hasStructuredEvidence
    ? summary.weakItems.length
      ? "review needed"
      : "evidence mapped"
    : isResearching
      ? "collecting"
      : "no structured evidence";

  return (
    <section className="container mt-5 h-auto w-full shrink-0 rounded-lg border border-solid border-gray-700/40 bg-gray-950/60 p-5 shadow-lg backdrop-blur-md">
      <div className="flex flex-col gap-3 pb-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-4">
          <img src="/img/chat-check.svg" alt="logs" width={24} height={24} />
          <div>
            <h3 className="text-base font-bold uppercase leading-[152.5%] text-white">
              Agent Work
            </h3>
          </div>
        </div>
        <span className="w-fit rounded-full border border-gray-700 bg-gray-950 px-3 py-1 text-xs font-medium uppercase tracking-wide text-gray-300">
          {panelStatus}
        </span>
      </div>

      <div className="grid overflow-hidden rounded-md border border-gray-800 bg-gray-950/50 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric, index) => (
          <div
            key={metric.label}
            className="min-w-0 border-b border-gray-800 px-4 py-3 last:border-b-0 sm:border-r sm:last:border-r-0 xl:border-b-0"
          >
            <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
              {metric.label}
            </p>
            <div className="mt-2 flex items-end gap-2">
              <span className={`text-2xl font-semibold ${metricAccentClassName(index)}`}>
                {metric.value}
              </span>
              <span className="pb-1 text-xs text-gray-500">{metric.detail}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[1.15fr_0.85fr]">
        <section className="min-w-0">
          <div className="mb-3 flex items-center justify-between">
            <h4 className="text-sm font-semibold text-gray-100">Agent Timeline</h4>
            <span className="text-xs text-gray-500">{logs.length} live events</span>
          </div>
          <ol className="space-y-3">
            {summary.timeline.map((step, index) => (
              <li key={step.label} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <span
                    className={`mt-1 h-3 w-3 rounded-full border ${statusClassName(step.status)}`}
                  />
                  {index < summary.timeline.length - 1 && (
                    <span className="mt-1 h-full min-h-8 w-px bg-gray-800" />
                  )}
                </div>
                <div className="min-w-0 pb-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-gray-100">{step.label}</p>
                    <span className="rounded-sm bg-gray-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-gray-400">
                      {step.status}
                    </span>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-gray-400">{step.detail}</p>
                </div>
              </li>
            ))}
          </ol>

          {recentLogs.length > 0 && (
            <div className="mt-3 border-t border-gray-800 pt-3">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                Recent Events
              </p>
              <div className="max-h-40 space-y-2 overflow-y-auto pr-1">
                {recentLogs.map((log) => (
                  <div key={log.key} className="rounded-md bg-gray-950/60 px-3 py-2">
                    <p className="text-xs font-semibold text-gray-200">
                      {log.header.replace(/_/g, " ")}
                    </p>
                    {log.text && (
                      <p className="mt-1 text-xs leading-5 text-gray-500">
                        {truncateText(log.text, 170)}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>

        <section className="min-w-0 border-t border-gray-800 pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
          <div className="mb-3 flex items-center justify-between">
            <h4 className="text-sm font-semibold text-gray-100">Needs Review</h4>
            <span className="text-xs text-gray-500">
              {summary.weakItems.length || 0} claims
            </span>
          </div>

          {!summary.hasStructuredEvidence ? (
            <div className="rounded-md border border-gray-800 bg-gray-950/60 p-4">
              <p className="text-sm font-medium text-gray-200">
                Structured evidence is not available yet.
              </p>
              <p className="mt-2 text-xs leading-5 text-gray-500">
                No claim-review payload was stored for this report. Recent agent events remain available in the timeline.
              </p>
            </div>
          ) : summary.weakItems.length === 0 ? (
            <div className="rounded-md border border-emerald-900/60 bg-emerald-950/20 p-4">
              <p className="text-sm font-medium text-emerald-100">
                No weak claims flagged by current review data.
              </p>
              <p className="mt-2 text-xs leading-5 text-emerald-200/60">
                {summary.reviews.length} support reviews checked against {summary.evidenceItems.length} evidence items.
              </p>
            </div>
          ) : (
            <div className="max-h-72 space-y-3 overflow-y-auto pr-1">
              {summary.weakItems.slice(0, 6).map((item) => (
                <article
                  key={item.id || item.claimId || item.text}
                  className="rounded-md border border-amber-900/60 bg-amber-950/10 p-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-sm bg-amber-900/40 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-amber-100">
                      {statusLabel(item.status)}
                    </span>
                    {item.claimId && (
                      <span className="truncate rounded-sm bg-gray-950 px-2 py-0.5 text-[11px] text-gray-400">
                        {item.claimId}
                      </span>
                    )}
                  </div>
                  <p className="mt-2 text-sm leading-5 text-gray-100">{item.text}</p>
                  {item.note && (
                    <p className="mt-2 text-xs leading-5 text-gray-500">{item.note}</p>
                  )}
                  <p className="mt-2 text-[11px] leading-5 text-gray-500">
                    Evidence ids: {item.evidenceIds.length ? item.evidenceIds.join(", ") : "none"}
                  </p>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </section>
  );
};

export default LogsSection;
