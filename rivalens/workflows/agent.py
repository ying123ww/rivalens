"""LangGraph entry point for Rivalens."""

from .competitive_analysis import build_competitive_analysis_graph

graph = build_competitive_analysis_graph().compile()
