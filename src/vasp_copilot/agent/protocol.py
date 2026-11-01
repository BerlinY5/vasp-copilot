"""Model-independent tool result contract."""

from typing import Annotated, Any, Literal, Union

from pydantic import Field, model_validator

from ..schemas import ErrorInfo, Schema

MAX_TOOL_CALLS_PER_DECISION = 8


class ToolResult(Schema):
    tool_name: str
    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def check_outcome(self) -> "ToolResult":
        if self.status == "success" and (self.data is None or self.error is not None):
            raise ValueError("Successful tool result requires data and no error")
        if self.status == "error" and (self.error is None or self.data is not None):
            raise ValueError("Failed tool result requires error and no data")
        return self


class ToolCall(Schema):
    type: Literal["tool"] = "tool"
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any]
    call_id: str | None = None
    assistant_content: str | None = None


class ToolBatch(Schema):
    type: Literal["tools"] = "tools"
    calls: list[ToolCall] = Field(min_length=2, max_length=MAX_TOOL_CALLS_PER_DECISION)

    @model_validator(mode="after")
    def unique_native_ids(self) -> "ToolBatch":
        ids = [call.call_id for call in self.calls if call.call_id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("Tool batch contains duplicate native IDs")
        return self


class Finish(Schema):
    type: Literal["final"] = "final"
    answer: str = Field(min_length=1)


Decision = Annotated[Union[ToolCall, ToolBatch, Finish], Field(discriminator="type")]


class ToolEvent(Schema):
    step: int = Field(ge=1)
    call: ToolCall
    observation: ToolResult
    batch_index: int = Field(default=1, ge=1, le=MAX_TOOL_CALLS_PER_DECISION)
    batch_size: int = Field(default=1, ge=1, le=MAX_TOOL_CALLS_PER_DECISION)

    @model_validator(mode="after")
    def valid_batch_position(self) -> "ToolEvent":
        if self.batch_index > self.batch_size:
            raise ValueError("Tool event index exceeds batch size")
        return self


class CompletionFeedback(Schema):
    step: int = Field(ge=1)
    kind: Literal["missing_required_tools"] = "missing_required_tools"
    missing_tools: list[str]
    message: str


class AgentState(Schema):
    question: str = Field(min_length=1)
    directory: str = Field(min_length=1)
    history: list[ToolEvent] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    completion_feedback: list[CompletionFeedback] = Field(default_factory=list)


class AgentRun(Schema):
    status: Literal["completed", "max_steps", "backend_error"]
    decision_steps: int = Field(ge=1)
    state: AgentState
    answer: str | None = None
    error: ErrorInfo | None = None
