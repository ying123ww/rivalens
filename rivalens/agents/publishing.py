"""Publisher agent for final Rivalens artifacts."""

from pathlib import Path

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.schema import CompetitorAnalysisState


class PublisherAgent:
    def __init__(self, output_dir: str = "outputs/rivalens"):
        self.output_dir = Path(output_dir)

    async def run(self, state: CompetitorAnalysisState) -> CompetitorAnalysisState:
        report_message = latest_message_for(
            state,
            receiver="publisher",
            message_type="report",
            sender="writer",
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.output_dir / "competitor_analysis.md"
        report_path.write_text(state.get("report", ""), encoding="utf-8")

        return {
            "published_artifacts": {"markdown": str(report_path)},
            "messages": state.get("messages", [])
            + [
                create_agent_message(
                    sender="publisher",
                    receiver="end",
                    message_type="publish",
                    payload={"markdown": str(report_path)},
                )
            ],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "publisher",
                    "action": "publish_markdown_report",
                    "input": {
                        "report_length": len(state.get("report", "")),
                        "message_id": report_message.get("id") if report_message else None,
                    },
                    "output": {"markdown": str(report_path)},
                }
            ],
        }
