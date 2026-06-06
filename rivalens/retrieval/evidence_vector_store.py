"""Pgvector-backed EvidenceItem indexing and retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Any, Iterable

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.types import UserDefinedType

from rivalens.research.config.config import Config
from rivalens.research.memory import Memory

DEFAULT_DATABASE_URL = "postgresql://rivalens:123456@localhost:5433/rivalens"
JSON_DATA = JSON().with_variant(JSONB, "postgresql")


class VectorType(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_: Any) -> str:
        return "vector"


def define_evidence_embeddings_table(metadata: MetaData) -> Table:
    return Table(
        "evidence_embeddings",
        metadata,
        Column("research_id", String(280), primary_key=True),
        Column("evidence_id", String(180), primary_key=True),
        Column("chunk_index", Integer, primary_key=True, default=0),
        Column("run_id", String(160), nullable=True, index=True),
        Column("embedding_provider", String(80), nullable=False, default=""),
        Column("embedding_model", String(160), nullable=False, default=""),
        Column("title", Text, nullable=False, default=""),
        Column("url", Text, nullable=False, default=""),
        Column("competitor", String(160), nullable=False, default=""),
        Column("analysis_dimension_id", String(160), nullable=False, default=""),
        Column("report_section_id", String(160), nullable=False, default=""),
        Column("source_type", String(80), nullable=False, default=""),
        Column("content_sha256", String(64), nullable=False, default=""),
        Column("content", Text, nullable=False, default=""),
        Column("metadata", JSON_DATA, nullable=False, default=dict),
        Column("embedding", VectorType(), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        extend_existing=True,
    )


class EvidenceVectorStore:
    """Index and retrieve EvidenceItem records with pgvector cosine distance."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        config_path: str = "default",
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        embedding_kwargs: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.database_url = database_url
        self.config_path = config_path
        self.embedding_provider = embedding_provider
        self.embedding_model = embedding_model
        self.embedding_kwargs = embedding_kwargs
        self.enabled = (
            enabled
            if enabled is not None
            else _env_flag("RIVALENS_ENABLE_EVIDENCE_RAG", True)
        )
        self._engine: Engine | None = None
        self._embedding_client: Any | None = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            database_url = self.database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
            self._engine = create_engine(_sqlalchemy_database_url(database_url), pool_pre_ping=True)
        return self._engine

    def index_report(self, research_id: str, report: dict[str, Any]) -> int:
        run_id = str(report.get("run_id") or research_id)
        evidence_items = extract_evidence_items(report)
        return self.index_evidence_items(
            research_id=research_id,
            run_id=run_id,
            evidence_items=evidence_items,
            replace_existing=True,
        )

    def index_evidence_items(
        self,
        *,
        research_id: str,
        run_id: str | None,
        evidence_items: Iterable[dict[str, Any]],
        replace_existing: bool = False,
    ) -> int:
        if not self.enabled or not research_id:
            return 0

        normalized = [item for item in (_normalize_evidence_item(item) for item in evidence_items) if item.get("id")]
        if not normalized:
            if replace_existing:
                self.delete_scope(research_id)
            return 0

        texts = [_evidence_text(item) for item in normalized]
        embedding_client = self._get_embedding_client()
        embeddings = embedding_client.embed_documents(texts)
        if len(embeddings) != len(normalized):
            raise ValueError("Embedding provider returned a mismatched vector count.")

        provider, model = self._embedding_identity()
        rows = [
            _index_row(
                research_id=research_id,
                run_id=run_id,
                item=item,
                content=text_value,
                embedding=embedding,
                embedding_provider=provider,
                embedding_model=model,
            )
            for item, text_value, embedding in zip(normalized, texts, embeddings)
        ]

        with self.engine.begin() as conn:
            if replace_existing:
                conn.execute(
                    text("DELETE FROM evidence_embeddings WHERE research_id = :research_id"),
                    {"research_id": research_id},
                )
            for row in rows:
                conn.execute(_UPSERT_SQL, row)
        return len(rows)

    def search(
        self,
        query: str,
        *,
        research_id: str | None = None,
        run_id: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        if not self.enabled or not query.strip():
            return []

        query_embedding = self._get_embedding_client().embed_query(query)
        params = {
            "query_embedding": _vector_literal(query_embedding),
            "research_id": research_id or "",
            "run_id": run_id or "",
            "limit": max(1, min(int(limit), 50)),
        }

        with self.engine.connect() as conn:
            rows = conn.execute(_SEARCH_SQL, params).mappings().all()

        return [_search_row_to_evidence(dict(row)) for row in rows]

    def delete_scope(self, research_id: str) -> None:
        if not research_id:
            return
        with self.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM evidence_embeddings WHERE research_id = :research_id"),
                {"research_id": research_id},
            )

    def _get_embedding_client(self) -> Any:
        if self._embedding_client is None:
            provider, model, kwargs = self._load_embedding_config()
            self._embedding_client = Memory(provider, model, **kwargs).get_embeddings()
        return self._embedding_client

    def _embedding_identity(self) -> tuple[str, str]:
        provider, model, _ = self._load_embedding_config()
        return provider, model

    def _load_embedding_config(self) -> tuple[str, str, dict[str, Any]]:
        cfg = Config(self.config_path)
        provider = self.embedding_provider or cfg.embedding_provider
        model = self.embedding_model or cfg.embedding_model
        kwargs = dict(cfg.embedding_kwargs)
        kwargs.update(self.embedding_kwargs or {})
        if not provider or not model:
            raise ValueError("Embedding provider/model is not configured.")
        return str(provider), str(model), kwargs


def extract_evidence_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_items = payload.get("evidence_index") or payload.get("evidence_items")
    if isinstance(evidence_items, list):
        return [item for item in evidence_items if isinstance(item, dict)]

    state = payload.get("state")
    if isinstance(state, dict):
        state_items = state.get("evidence_items")
        if isinstance(state_items, list):
            return [item for item in state_items if isinstance(item, dict)]

    return []


def _normalize_evidence_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized["id"] = str(
        item.get("id")
        or item.get("evidence_id")
        or item.get("citation_ref")
        or ""
    )
    normalized["url"] = str(item.get("url") or item.get("source_url") or "")
    return normalized


def _evidence_text(item: dict[str, Any]) -> str:
    fields = [
        item.get("title", ""),
        item.get("competitor", ""),
        item.get("dimension_name") or item.get("analysis_dimension_id") or item.get("dimension_id", ""),
        item.get("source_type", ""),
        item.get("excerpt") or item.get("summary") or item.get("content") or "",
        item.get("url", ""),
    ]
    return "\n".join(str(field).strip() for field in fields if str(field or "").strip())[:5000]


def _index_row(
    *,
    research_id: str,
    run_id: str | None,
    item: dict[str, Any],
    content: str,
    embedding: list[float],
    embedding_provider: str,
    embedding_model: str,
) -> dict[str, Any]:
    return {
        "research_id": research_id,
        "evidence_id": str(item.get("id", "")),
        "chunk_index": 0,
        "run_id": run_id or "",
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "title": str(item.get("title") or ""),
        "url": str(item.get("url") or item.get("source_url") or ""),
        "competitor": str(item.get("competitor") or ""),
        "analysis_dimension_id": str(item.get("analysis_dimension_id") or item.get("dimension_id") or ""),
        "report_section_id": str(item.get("report_section_id") or ""),
        "source_type": str(item.get("source_type") or ""),
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
        "metadata": json.dumps(item, ensure_ascii=False),
        "embedding": _vector_literal(embedding),
    }


def _search_row_to_evidence(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}

    evidence = dict(metadata)
    evidence.update(
        {
            "id": row.get("evidence_id", "") or metadata.get("id", ""),
            "url": row.get("url", "") or metadata.get("url", ""),
            "title": row.get("title", "") or metadata.get("title", ""),
            "competitor": row.get("competitor", "") or metadata.get("competitor", ""),
            "analysis_dimension_id": row.get("analysis_dimension_id", "") or metadata.get("analysis_dimension_id", ""),
            "report_section_id": row.get("report_section_id", "") or metadata.get("report_section_id", ""),
            "source_type": row.get("source_type", "") or metadata.get("source_type", ""),
            "excerpt": metadata.get("excerpt") or row.get("content", ""),
            "retrieval": {
                "research_id": row.get("research_id", ""),
                "run_id": row.get("run_id", ""),
                "distance": float(row.get("distance") or 0.0),
            },
        }
    )
    return evidence


def _vector_literal(values: Iterable[float]) -> str:
    parts: list[str] = []
    for value in values:
        number = float(value)
        if not math.isfinite(number):
            number = 0.0
        parts.append(f"{number:.8g}")
    return "[" + ",".join(parts) + "]"


def _sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


_UPSERT_SQL = text(
    """
    INSERT INTO evidence_embeddings (
        research_id,
        evidence_id,
        chunk_index,
        run_id,
        embedding_provider,
        embedding_model,
        title,
        url,
        competitor,
        analysis_dimension_id,
        report_section_id,
        source_type,
        content_sha256,
        content,
        metadata,
        embedding,
        created_at,
        updated_at
    )
    VALUES (
        :research_id,
        :evidence_id,
        :chunk_index,
        NULLIF(:run_id, ''),
        :embedding_provider,
        :embedding_model,
        :title,
        :url,
        :competitor,
        :analysis_dimension_id,
        :report_section_id,
        :source_type,
        :content_sha256,
        :content,
        CAST(:metadata AS jsonb),
        CAST(:embedding AS vector),
        now(),
        now()
    )
    ON CONFLICT (research_id, evidence_id, chunk_index)
    DO UPDATE SET
        run_id = EXCLUDED.run_id,
        embedding_provider = EXCLUDED.embedding_provider,
        embedding_model = EXCLUDED.embedding_model,
        title = EXCLUDED.title,
        url = EXCLUDED.url,
        competitor = EXCLUDED.competitor,
        analysis_dimension_id = EXCLUDED.analysis_dimension_id,
        report_section_id = EXCLUDED.report_section_id,
        source_type = EXCLUDED.source_type,
        content_sha256 = EXCLUDED.content_sha256,
        content = EXCLUDED.content,
        metadata = EXCLUDED.metadata,
        embedding = EXCLUDED.embedding,
        updated_at = now()
    """
)


_SEARCH_SQL = text(
    """
    SELECT
        research_id,
        run_id,
        evidence_id,
        title,
        url,
        competitor,
        analysis_dimension_id,
        report_section_id,
        source_type,
        content,
        metadata,
        embedding <=> CAST(:query_embedding AS vector) AS distance
    FROM evidence_embeddings
    WHERE (:research_id = '' OR research_id = :research_id)
      AND (:run_id = '' OR run_id = :run_id)
    ORDER BY embedding <=> CAST(:query_embedding AS vector)
    LIMIT :limit
    """
)
