"""Orchestrator agents: MAF agents + Workflow that drive the research swarm."""
from .workflow import (
    MAX_RESEARCHERS,
    ResearchInput,
    build_research_workflow,
)

__all__ = [
    "MAX_RESEARCHERS",
    "ResearchInput",
    "build_research_workflow",
]
