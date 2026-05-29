"""Publisher agent for final Rivalens artifacts."""

from pathlib import Path

from rivalens.agents.messages import create_agent_message, latest_message_for
from rivalens.report_export import generate_report_files
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
        report = state.get("report", "")
        artifacts = await generate_report_files(
            report,
            "competitor_analysis",
            output_dir=self.output_dir,
        )

        return {
            "published_artifacts": artifacts,
            "messages": state.get("messages", [])
            + [
                create_agent_message(
                    sender="publisher",
                    receiver="end",
                    message_type="publish",
                    payload=artifacts,
                )
            ],
            "agent_events": state.get("agent_events", [])
            + [
                {
                    "agent": "publisher",
                    "action": "publish_report_artifacts",
                    "input": {
                        "report_length": len(report),
                        "message_id": report_message.get("id") if report_message else None,
                    },
                    "output": artifacts,
                }
            ],
        }
