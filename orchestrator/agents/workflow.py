"""
Research Workflow — MAF Workflow that orchestrates the swarm pipeline.

Shape::

    [DecomposeExecutor]
            ↓
       (1 message per question)
            ↓
    [Researcher_0] [Researcher_1] ... [Researcher_N]   ← fan-out
            ↓        ↓                    ↓
            └────────┴───── fan-in ──────┘
                            ↓
                  [SynthesizeExecutor]
                            ↓
                       final markdown
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from agent_framework import (
    AgentExecutor,
    AgentExecutorRequest,
    AgentExecutorResponse,
    Executor,
    Message,
    Workflow,
    WorkflowBuilder,
    WorkflowContext,
    handler,
)
from typing_extensions import Never

from sandbox_manager import SandboxManager

from .decomposer_agent import build_decomposer_agent
from .researcher_agent import build_researcher_agent
from .synthesizer_agent import build_synthesizer_agent

logger = logging.getLogger(__name__)

EmitFn = Callable[[dict], Awaitable[None]]

# A workflow with too many parallel researchers is expensive and may hit AOAI
# rate limits. Cap the fan-out width here.
MAX_RESEARCHERS = 6


@dataclass
class ResearchInput:
    """Input passed to the workflow start executor."""
    topic: str


# ── Stage 1: Decompose ──────────────────────────────────────────────────────

class DecomposeExecutor(Executor):
    """
    Asks the decomposer agent for sub-questions, then dispatches one
    AgentExecutorRequest per question to the parallel researcher executors.
    """

    def __init__(self, id: str = "decomposer"):
        super().__init__(id=id)
        self._agent = build_decomposer_agent()

    @handler
    async def decompose(
        self,
        payload: ResearchInput,
        ctx: WorkflowContext[AgentExecutorRequest, list[str]],
    ) -> None:
        # 1) Ask the LLM to decompose
        result = await self._agent.run(payload.topic)
        raw = (result.text or "").strip()
        questions = _parse_questions(raw, fallback_topic=payload.topic)
        # Cap at MAX_RESEARCHERS; researchers list is built to match this size
        questions = questions[:MAX_RESEARCHERS]

        # Surface the questions as a workflow output (events) so the UI gets them
        await ctx.yield_output(questions)

        # 2) Dispatch one request per question. The framework will route
        # successive sends in the same handler invocation across the fan-out
        # edges round-robin / by index, so we attach the index in metadata
        # via a structured user message.
        for i, q in enumerate(questions):
            await ctx.send_message(
                AgentExecutorRequest(
                    messages=[Message("user", [q])],
                    should_respond=True,
                ),
                target_id=f"researcher_{i}",
            )


# ── Stage 2: Researchers (one AgentExecutor per parallel branch) ────────────

def _build_researcher_executors(
    sandbox_mgr: SandboxManager,
    emit: EmitFn,
) -> list[AgentExecutor]:
    """
    Build a fixed pool of MAX_RESEARCHERS researcher AgentExecutors. Each one
    has a unique id (`researcher_0`, `researcher_1`, ...) so DecomposeExecutor
    can target by index. The sandbox manager + emit callback are bound via
    closure on each researcher's tool.
    """
    pool: list[AgentExecutor] = []
    for i in range(MAX_RESEARCHERS):
        agent_id = f"researcher_{i}"
        agent = build_researcher_agent(agent_id, sandbox_mgr, emit, i)
        pool.append(AgentExecutor(agent=agent, id=agent_id))
    return pool


# ── Stage 3: Synthesize (fan-in) ────────────────────────────────────────────

class SynthesizeExecutor(Executor):
    """
    Aggregates all researcher AgentExecutorResponses, asks the synthesizer
    agent to produce a markdown report, then yields it as the workflow output.
    """

    def __init__(self, id: str = "synthesizer"):
        super().__init__(id=id)
        self._agent = build_synthesizer_agent()

    @handler
    async def synthesize(
        self,
        responses: list[AgentExecutorResponse],
        ctx: WorkflowContext[Never, str],
    ) -> None:
        # Each response.text from a researcher is the JSON our researcher tool
        # returned. Parse them back into structured findings.
        findings: list[dict] = []
        for r in responses:
            text = (r.agent_response.text or "").strip()
            text = _strip_code_fences(text)
            try:
                findings.append(json.loads(text))
            except json.JSONDecodeError:
                findings.append({
                    "question": "(unparsed)",
                    "answer": text,
                    "sources": [],
                    "confidence": 0.0,
                })

        # Build the synthesis prompt
        prompt_lines: list[str] = ["## Individual Agent Findings\n"]
        for i, f in enumerate(findings, start=1):
            prompt_lines.append(f"### Agent {i}: {f.get('question', '')}")
            prompt_lines.append(f"**Confidence:** {float(f.get('confidence', 0)):.0%}\n")
            prompt_lines.append(str(f.get("answer", "")))
            srcs = f.get("sources") or []
            if srcs:
                prompt_lines.append("\n**Sources:** " + ", ".join(srcs))
            prompt_lines.append("")

        result = await self._agent.run("\n".join(prompt_lines))
        await ctx.yield_output(result.text or "")


# ── Build & expose ──────────────────────────────────────────────────────────

def build_research_workflow(
    sandbox_mgr: SandboxManager,
    emit: EmitFn,
) -> Workflow:
    """
    Construct the full fan-out/fan-in workflow:
        decomposer → [researcher_0..N-1] → synthesizer

    The workflow is built per request so each researcher's tool closes over
    the right WebSocket emit callback.
    """
    decomposer  = DecomposeExecutor()
    researchers = _build_researcher_executors(sandbox_mgr, emit)
    synthesizer = SynthesizeExecutor()

    # NOTE: We use individual edges (decomposer → researcher_i) instead of a
    # single `add_fan_out_edges` group on purpose. MAF's fan-out edge runner
    # delivers the N targeted messages sequentially within a single edge
    # runner (`for message in source_messages: await deliver(...)`), which
    # serializes the LLM calls for all 6 researchers. Using 6 separate edge
    # runners lets MAF parallelize them via `asyncio.gather` in the runner.
    builder = WorkflowBuilder(start_executor=decomposer)
    for r in researchers:
        builder = builder.add_edge(decomposer, r)
    wf = builder.add_fan_in_edges(list(researchers), synthesizer).build()
    return wf


def per_agent_kwargs_for_run(
    sandbox_mgr: SandboxManager,
    emit,  # async callable taking a dict
) -> dict[str, dict]:
    """
    Per-researcher kwargs supplied via `function_invocation_kwargs`. Each
    branch gets its index injected so the tool can correlate WebSocket events.
    """
    out: dict[str, dict] = {}
    for i in range(MAX_RESEARCHERS):
        out[f"researcher_{i}"] = {
            "sandbox_mgr": sandbox_mgr,
            "emit": emit,
            "index": i,
        }
    return out


# ── helpers ─────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?|\n?```$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def _parse_questions(raw: str, fallback_topic: str) -> list[str]:
    raw = _strip_code_fences(raw)
    try:
        data = json.loads(raw)
        if isinstance(data, list) and all(isinstance(q, str) for q in data):
            return data
    except json.JSONDecodeError:
        logger.warning("[Decompose] Could not parse LLM response: %r", raw[:200])
    # Fallback simulation
    return [
        f"What is the current state of {fallback_topic}?",
        f"What are the key challenges facing {fallback_topic}?",
        f"What recent breakthroughs have occurred in {fallback_topic}?",
        f"How does {fallback_topic} compare to alternative approaches?",
        f"What is the future outlook for {fallback_topic}?",
    ]
