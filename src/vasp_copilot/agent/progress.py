"""Transient execution progress, separate from model messages and saved evidence."""

from dataclasses import dataclass
from time import monotonic
from typing import Callable, Literal, TextIO


@dataclass(frozen=True)
class ProgressEvent:
    kind: Literal["decision_started", "tool_started", "tool_finished", "final_deferred", "run_finished"]
    step: int
    max_steps: int
    tool_name: str | None = None
    batch_index: int = 1
    batch_size: int = 1
    status: Literal["success", "error", "completed", "max_steps", "backend_error"] | None = None


ProgressCallback = Callable[[ProgressEvent], None]


class StderrProgressReporter:
    """ASCII stage labels survive Windows pipe/console code-page differences."""

    def __init__(self, stream: TextIO):
        self.stream = stream
        self.started_at = monotonic()

    def __call__(self, event: ProgressEvent) -> None:
        if event.kind == "decision_started":
            message = "Waiting for backend decision"
        elif event.kind == "tool_started":
            message = f"Starting tool {event.batch_index}/{event.batch_size}: {event.tool_name}"
        elif event.kind == "tool_finished":
            message = f"Tool {event.batch_index}/{event.batch_size}: {event.tool_name} -> {event.status}"
        elif event.kind == "final_deferred":
            message = "Final deferred: required tools not yet successful; continuing"
        else:
            message = f"Agent finished: {event.status} (execution status only)"
        elapsed = monotonic() - self.started_at
        print(f"[progress {elapsed:.1f}s | decision {event.step}/{event.max_steps}] {message}",
              file=self.stream, flush=True)
