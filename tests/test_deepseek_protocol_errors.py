"""Expose the reason for the online protocol failure without storing raw replies."""

import io

import pytest

from vasp_copilot.agent import deepseek
from vasp_copilot.agent.deepseek import DeepSeekBackend, DeepSeekProtocolError
from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.agent.protocol import AgentState, ToolCall, ToolEvent
from vasp_copilot.config import DeepSeekConfig
from vasp_copilot.reports.generator import render_markdown
from vasp_copilot.storage.repository import RunRepository
from vasp_copilot.tools.file_inspection import create_registry

PRIVATE = "sensitive-response-text-and-test-key"


def response(reason="stop", content=PRIVATE, calls=None):
    return {"choices": [{"finish_reason": reason, "message": {
        "role": "assistant", "content": content, "tool_calls": calls,
    }}]}


def call(arguments='{"query": "EDIFF"}', call_id="call_1"):
    return {"id": call_id, "type": "function", "function": {"name": "search_knowledge", "arguments": arguments}}


@pytest.mark.parametrize("raw, expected", [
    ({}, "DeepSeekResponseShapeError"),
    ({"choices": []}, "DeepSeekResponseShapeError"),
    ({"choices": [None]}, "DeepSeekResponseShapeError"),
    (response("length", calls=[call(arguments="partial"), call()]), "DeepSeekResponseTruncatedError"),
    (response("content_filter"), "DeepSeekResponseFilteredError"),
    (response("insufficient_system_resource"), "DeepSeekResourceInterruptedError"),
    (response("aborted"), "DeepSeekResponseAbortedError"),
    (response(PRIVATE), "DeepSeekFinishReasonError"),
    (response(None), "DeepSeekFinishReasonError"),
    (response("stop", calls=[call()]), "DeepSeekFinishReasonError"),
    (response("tool_calls", calls=[call(call_id=f"call_{i}") for i in range(9)]), "DeepSeekToolCallLimitError"),
    (response("tool_calls", calls=[]), "DeepSeekToolCallFormatError"),
    (response("tool_calls", calls=PRIVATE), "DeepSeekToolCallFormatError"),
    (response("tool_calls", calls=[{}]), "DeepSeekToolCallFormatError"),
    (response("tool_calls", calls=[call(arguments=PRIVATE)]), "DeepSeekToolArgumentsError"),
    (response("tool_calls", calls=[call(arguments={"secret": PRIVATE})]), "DeepSeekToolArgumentsError"),
    (response("tool_calls", calls=[call(arguments="[]")]), "DeepSeekToolArgumentsError"),
    (response(content="  "), "DeepSeekEmptyAnswerError"),
    (response(content=None), "DeepSeekEmptyAnswerError"),
])
def test_specific_error_reaches_saved_agent_run_without_raw_response(tmp_path, raw, expected):
    invocations = []

    def transport(payload, config):
        invocations.append(payload)
        return raw

    backend = DeepSeekBackend(DeepSeekConfig("test-key"), transport)
    run = AgentLoop(backend, create_registry(tmp_path), 8,
                    required_tools=("search_knowledge",)).run("Retrieve references", str(tmp_path))
    assert run.status == "backend_error" and run.decision_steps == 1
    assert run.error.message == expected
    assert run.state.history == [] and run.state.completion_feedback == []
    assert len(invocations) == 1  # Classification does not add a retry or API call.
    repository = RunRepository(tmp_path / "history.sqlite3")
    saved = repository.save(run, "deepseek")
    record = repository.get(saved.id)
    assert record.run.error.message == expected
    assert PRIVATE not in record.model_dump_json() + render_markdown(record)
    assert "test-key" not in record.model_dump_json()


@pytest.mark.parametrize("raw, expected", [
    (b"private not json", "DeepSeekResponseJSONError"),
    (b"[]", "DeepSeekResponseShapeError"),
    (b"x" * (deepseek.MAX_RESPONSE_BYTES + 1), "DeepSeekResponseTooLargeError"),
], ids=["invalid-json", "non-object", "oversized"])
def test_transport_body_errors_are_specific_and_compatible(monkeypatch, raw, expected):
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(raw)

    monkeypatch.setattr(deepseek, "build_opener", lambda *handlers: Opener())
    with pytest.raises(DeepSeekProtocolError) as caught:
        deepseek.request_completion({}, DeepSeekConfig("test-key"))
    assert type(caught.value).__name__ == expected
    assert str(caught.value) == ""


def test_duplicate_native_call_keeps_prior_tool_history(tmp_path):
    backend = DeepSeekBackend(DeepSeekConfig("test-key"),
                              lambda payload, config: response("tool_calls", content=None, calls=[call()]))
    run = AgentLoop(backend, create_registry(tmp_path), 4).run("Retrieve", str(tmp_path))
    assert run.status == "backend_error" and run.decision_steps == 2
    assert run.error.message == "DeepSeekDuplicateToolCallError"
    assert len(run.state.history) == 1


def test_missing_native_id_fails_before_transport(tmp_path):
    registry = create_registry(tmp_path)
    observation = registry.execute("search_knowledge", {"query": "EDIFF"})
    state = AgentState(question="Retrieve", directory=str(tmp_path), history=[ToolEvent(
        step=1, call=ToolCall(tool_name="search_knowledge", arguments={"query": "EDIFF"}), observation=observation)])

    def forbidden(*args):
        raise AssertionError("History must be checked before network access")

    with pytest.raises(deepseek.DeepSeekHistoryReplayError):
        DeepSeekBackend(DeepSeekConfig("test-key"), forbidden).decide(state, registry.describe())
