"""Bounded synchronous decision/observation loop."""

import logging

from pydantic import TypeAdapter

from ..schemas import ErrorInfo
from .backend import DecisionBackend
from .protocol import AgentRun, AgentState, CompletionFeedback, Decision, Finish, ToolBatch, ToolEvent
from .progress import ProgressCallback, ProgressEvent
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)
DECISION_ADAPTER = TypeAdapter(Decision)


class AgentLoop:
    def __init__(self, backend: DecisionBackend, registry: ToolRegistry, max_steps: int = 6,
                 *, required_tools: tuple[str, ...] = (), on_progress: ProgressCallback | None = None):
        if type(max_steps) is not int or not 1 <= max_steps <= 100:
            raise ValueError("max_steps must be an integer from 1 to 100")
        self.backend = backend
        self.registry = registry
        self.max_steps = max_steps
        registered = {tool["name"] for tool in registry.describe()}
        if (not isinstance(required_tools, tuple) or
                any(not isinstance(name, str) or name not in registered for name in required_tools)):
            raise ValueError("Required tools must be a tuple of registered tool names")
        self.required_tools = list(dict.fromkeys(required_tools))
        if on_progress is not None and not callable(on_progress):
            raise TypeError("on_progress must be callable or None")
        self.on_progress = on_progress
        self._registered_tools = registered

    def _notify(self, event: ProgressEvent) -> None:
        if self.on_progress is not None:
            try:
                self.on_progress(event)
            except Exception:
                # Display failures must not lose an otherwise usable diagnostic.
                # Never log arbitrary callback exception text.
                logger.warning("Progress callback failed")

    def run(self, question: str, directory: str) -> AgentRun:
        state = AgentState(question=question, directory=directory, required_tools=list(self.required_tools))
        for step in range(1, self.max_steps + 1):
            logger.info("Agent decision step %d", step)
            self._notify(ProgressEvent("decision_started", step, self.max_steps))
            try:
                # A backend must not rewrite the actual tool history.
                raw = self.backend.decide(state.model_copy(deep=True), self.registry.describe())
                if hasattr(raw, "model_dump"):
                    raw = raw.model_dump()
                decision = DECISION_ADAPTER.validate_python(raw)
            except Exception as exc:
                self._notify(ProgressEvent("run_finished", step, self.max_steps, status="backend_error"))
                return AgentRun(status="backend_error", decision_steps=step, state=state,
                                error=ErrorInfo(kind="backend_error", message=type(exc).__name__))
            if isinstance(decision, Finish):
                successful = {event.call.tool_name for event in state.history
                              if event.observation.status == "success"}
                missing = [name for name in self.required_tools if name not in successful]
                if missing:
                    # A rejected final consumes this decision; never execute a tool
                    # on the model's behalf or grant an unbounded repair request.
                    state.completion_feedback.append(CompletionFeedback(
                        step=step, missing_tools=missing,
                        message="Final answer not accepted. Call the missing required tools successfully before finishing: "
                                + ", ".join(missing)
                                + ". A successful search may have zero hits; disclose missing references or tool errors.",
                    ))
                    self._notify(ProgressEvent("final_deferred", step, self.max_steps))
                    continue
                self._notify(ProgressEvent("run_finished", step, self.max_steps, status="completed"))
                return AgentRun(status="completed", decision_steps=step, state=state, answer=decision.answer)
            calls = decision.calls if isinstance(decision, ToolBatch) else [decision]
            for index, call in enumerate(calls, start=1):
                # Tool names from the model may contain arbitrary text. Progress
                # only exposes developer-registered names, never raw unknown names.
                label = call.tool_name if call.tool_name in self._registered_tools else "<unknown_tool>"
                self._notify(ProgressEvent("tool_started", step, self.max_steps, tool_name=label,
                                           batch_index=index, batch_size=len(calls)))
                observation = self.registry.execute(call.tool_name, call.arguments)
                state.history.append(ToolEvent(step=step, call=call, observation=observation,
                                              batch_index=index, batch_size=len(calls)))
                self._notify(ProgressEvent("tool_finished", step, self.max_steps, tool_name=label,
                                           batch_index=index, batch_size=len(calls), status=observation.status))
        self._notify(ProgressEvent("run_finished", self.max_steps, self.max_steps, status="max_steps"))
        return AgentRun(status="max_steps", decision_steps=self.max_steps, state=state,
                        error=ErrorInfo(kind="max_steps", message="Decision limit reached before a final answer"))
