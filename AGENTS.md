# Rivalens Agent Instructions

This file is the repository-level instruction entry point for Codex and other coding agents that read `AGENTS.md`.

For the full project context, evaluation rubric, and collaboration rules, read:

- [Rivalens Context Engineering](docs/CONTEXT_ENGINEERING.md)
- [README](README.md)

## Project Intent

Rivalens is a traceable multi-agent competitor analysis system. Code changes should strengthen the end-to-end chain from public evidence collection to structured competitor knowledge, analysis claims, quality review, backend delivery, and frontend source review.

## Non-Negotiable Rules

- Preserve traceability from important analysis claims to `EvidenceItem` records and source URLs.
- Keep Agent roles clear: planning, schema selection, collection, knowledge structuring, analysis, quality, revision, writing, publishing.
- Use structured messages and Pydantic payloads for Agent handoffs.
- Do not bypass `rivalens/schema/competitive.py` when changing state, messages, evidence, knowledge, claims, or quality findings.
- Keep LangGraph DAG behavior visible and explainable.
- Make quality feedback real: findings should be able to trigger revision or additional collection, not just produce a decorative review note.
- Add observability for prompt, input, output, decision, and token/cost behavior when changing Agent logic.
- Add focused tests or executable verification for workflow, schema, and evidence-traceability changes.
- Update docs when architecture, Agent roles, protocols, setup, or demo behavior changes.

## Planning Checklist

Before complex changes, identify:

- Which rubric item in `docs/CONTEXT_ENGINEERING.md` the change improves.
- Which Agents, schema fields, workflow edges, backend APIs, frontend views, and docs are affected.
- Which evidence IDs, source URLs, and structured payloads must remain traceable.
- Which logs, traces, token/cost records, retries, or fallback paths are needed.
- Which tests or demo steps prove the change works.

## Review Checklist

During review, prioritize:

- Agent role overlap or missing ownership.
- Natural-language handoffs replacing structured messages.
- Claims without evidence bindings.
- Quality loops that cannot actually route work back or improve output.
- Missing observability, token/cost tracking, timeout handling, retries, or fallbacks.
- Frontend or backend gaps that prevent source viewing, human correction, or decision replay.

