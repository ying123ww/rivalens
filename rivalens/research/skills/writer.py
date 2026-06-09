"""Report generator skill for Rivalens.

This module provides the ReportGenerator class that handles report writing.
"""

import json

from ..actions import (
    generate_report,
    stream_output,
)


class ReportGenerator:
    """Generates reports based on research data.

    This class handles report generation from collected research context.

    Attributes:
        researcher: The parent ResearchEngine instance.
        research_params: Dictionary of parameters for report generation.
    """

    def __init__(self, researcher):
        """Initialize the ReportGenerator.

        Args:
            researcher: The ResearchEngine instance that owns this generator.
        """
        self.researcher = researcher
        self.research_params = {
            "query": self.researcher.query,
            "agent_role_prompt": self.researcher.cfg.agent_role or self.researcher.role,
            "report_type": self.researcher.report_type,
            "report_source": self.researcher.report_source,
            "tone": self.researcher.tone,
            "websocket": self.researcher.websocket,
            "cfg": self.researcher.cfg,
            "headers": self.researcher.headers,
        }

    async def write_report(self, ext_context=None, custom_prompt="") -> str:
        """
        Write a report based on existing headers and relevant contents.

        Args:
            ext_context (Optional): External context, if any.
            custom_prompt (str): Custom prompt for the report.

        Returns:
            str: The generated report.
        """
        # send the selected images prior to writing report
        research_images = self.researcher.get_research_images()
        if research_images:
            await stream_output(
                "images",
                "selected_images",
                json.dumps(research_images),
                self.researcher.websocket,
                True,
                research_images
            )

        context = ext_context or self.researcher.context

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "writing_report",
                f"✍️ Writing report for '{self.researcher.query}'...",
                self.researcher.websocket,
            )

        report_params = self.research_params.copy()
        if not report_params["agent_role_prompt"]:
            report_params["agent_role_prompt"] = self.researcher.cfg.agent_role or self.researcher.role
        report_params["context"] = context
        report_params["custom_prompt"] = custom_prompt
        report_params["cost_callback"] = self.researcher.add_costs

        report = await generate_report(**report_params, **self.researcher.kwargs)

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "report_written",
                f"📝 Report written for '{self.researcher.query}'",
                self.researcher.websocket,
            )

        return report
