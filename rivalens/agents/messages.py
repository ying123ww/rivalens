"""Structured messages passed between Rivalens agents."""

from datetime import datetime, timezone
from typing import Any, cast

from pydantic import BaseModel

from rivalens.schema import (
    AgentMessage,
    AgentMessagePayload,
    AgentMessageType,
    AnalysisMessagePayload,
    CompetitorAnalysisState,
    EvidenceMessagePayload,
    PlanMessagePayload,
    PublishMessagePayload,
    ReportMessagePayload,
    ReviewMessagePayload,
    RevisionMessagePayload,
    SchemaMessagePayload,
    SchemaSelectionMessagePayload,
)


PAYLOAD_MODELS: dict[AgentMessageType, type[BaseModel]] = {
    "plan": PlanMessagePayload,
    "schema_selection": SchemaSelectionMessagePayload,
    "evidence": EvidenceMessagePayload,
    "schema": SchemaMessagePayload,
    "analysis": AnalysisMessagePayload,
    "review": ReviewMessagePayload,
    "revision": RevisionMessagePayload,
    "report": ReportMessagePayload,
    "publish": PublishMessagePayload,
}


def validate_payload(
    message_type: AgentMessageType,
    payload: AgentMessagePayload | dict[str, Any],
) -> dict[str, Any]:
    """Validate and serialize a function-calling-like message payload."""
    model = PAYLOAD_MODELS[message_type]
    validated = payload if isinstance(payload, model) else model.model_validate(payload)
    return validated.model_dump()


def create_agent_message(
    sender: str,
    receiver: str,
    message_type: AgentMessageType,
    payload: AgentMessagePayload | dict[str, Any],
    artifact_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
) -> AgentMessage:
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"msg_{sender}_{receiver}_{message_type}_{timestamp}",
        "sender": sender,
        "receiver": receiver,
        "type": message_type,
        "payload": validate_payload(message_type, payload),
        "artifact_ids": artifact_ids or [],
        "evidence_ids": evidence_ids or [],
        "created_at": timestamp,
    }


def validate_agent_message(message: AgentMessage) -> AgentMessage:
    """Validate an existing serialized message before a receiver consumes it."""
    message_type = cast(AgentMessageType, message.get("type"))
    return {
        **message,
        "type": message_type,
        "payload": validate_payload(message_type, message.get("payload", {})),
    }


def latest_message_for(
    state: CompetitorAnalysisState,
    receiver: str,
    message_type: AgentMessageType | None = None,
    sender: str | None = None,
) -> AgentMessage | None:
    """Return the latest validated message addressed to an agent."""
    for message in reversed(state.get("messages", [])):
        if message.get("receiver") != receiver:
            continue
        if message_type is not None and message.get("type") != message_type:
            continue
        if sender is not None and message.get("sender") != sender:
            continue
        return validate_agent_message(message)
    return None
