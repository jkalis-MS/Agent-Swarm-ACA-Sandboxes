"""
Decomposer Agent — MAF agent that breaks a topic into 4-6 sub-questions.

Returned as a JSON array of strings on the agent's final message.
"""
from __future__ import annotations

from agent_framework import Agent

from .chat_client import build_chat_client


DECOMPOSER_INSTRUCTIONS = (
    "You are a research planning assistant. Given a broad research topic, "
    "decompose it into 4-6 specific, focused sub-questions that together "
    "would provide a comprehensive understanding of the topic.\n\n"
    "Return ONLY a JSON array of question strings, no extra text and no code fences. "
    'Example: ["What is ...?", "How does ...?", ...]'
)


def build_decomposer_agent() -> Agent:
    return Agent(
        client=build_chat_client(),
        instructions=DECOMPOSER_INSTRUCTIONS,
        name="decomposer",
        default_options={"reasoning": {"effort": "low"}},
    )
