"""Rivalens research modes used by evidence collection adapters."""

from enum import Enum

from rivalens.research.utils.enum import ReportType


class ResearchMode(str, Enum):
    STANDARD_EVIDENCE = "standard_evidence"


REPORT_TYPE_BY_MODE = {
    ResearchMode.STANDARD_EVIDENCE: ReportType.ResearchReport.value,
}
