"""Register the pgvector evidence index table for backend migrations."""

from rivalens.retrieval.evidence_vector_store import (
    EvidenceVectorStore,
    define_evidence_embeddings_table,
)

from .metadata import shared_metadata

evidence_embeddings = define_evidence_embeddings_table(shared_metadata)

__all__ = ["EvidenceVectorStore", "evidence_embeddings"]
