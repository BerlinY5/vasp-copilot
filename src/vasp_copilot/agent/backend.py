"""Replaceable decision interface; no dependency on a model provider."""

from typing import Any, Protocol

from .protocol import AgentState, Finish, ToolBatch, ToolCall


class DecisionBackend(Protocol):
    def decide(
        self, state: AgentState, tools: list[dict[str, Any]],
    ) -> ToolCall | ToolBatch | Finish | dict[str, Any]:
        """Choose a tool call, a bounded batch, or finish using recorded observations."""
        ...
