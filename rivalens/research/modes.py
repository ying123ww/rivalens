"""Rivalens research modes.

These modes are business-level tools for agents. They intentionally hide the
lower-level report_type names used by ResearchEngine.
"""

from enum import Enum

from rivalens.research.utils.enum import ReportType


class ResearchMode(str, Enum):
    STANDARD_EVIDENCE = "standard_evidence"
    DEEP_EVIDENCE = "deep_evidence"
    SOURCE_DISCOVERY = "source_discovery"
    OUTLINE_ASSISTED = "outline_assisted"
    SCHEMA_EXTRACTION = "schema_extraction"
    FOCUSED_ANALYSIS = "focused_analysis"
    SUBTOPIC_EVIDENCE = "subtopic_evidence"


REPORT_TYPE_BY_MODE = {
    ResearchMode.STANDARD_EVIDENCE: ReportType.ResearchReport.value,
    ResearchMode.DEEP_EVIDENCE: ReportType.DeepResearch.value,
    ResearchMode.SOURCE_DISCOVERY: ReportType.ResourceReport.value,
    ResearchMode.OUTLINE_ASSISTED: ReportType.OutlineReport.value,
    ResearchMode.SCHEMA_EXTRACTION: ReportType.CustomReport.value,
    ResearchMode.FOCUSED_ANALYSIS: ReportType.DetailedReport.value,
    ResearchMode.SUBTOPIC_EVIDENCE: ReportType.SubtopicReport.value,
}
