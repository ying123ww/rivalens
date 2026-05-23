"""Structured messages passed between Rivalens agents."""

from datetime import datetime, timezone
from typing import Any

from rivalens.schema import AgentMessage


def create_agent_message(
    sender: str,
    receiver: str,
    message_type: str,
    payload: dict[str, Any],
    artifact_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
) -> AgentMessage:
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"msg_{sender}_{receiver}_{message_type}_{timestamp}",
        "sender": sender,
        "receiver": receiver,
        "type": message_type,
        "payload": payload,
        "artifact_ids": artifact_ids or [],
        "evidence_ids": evidence_ids or [],
        "created_at": timestamp,
    }
