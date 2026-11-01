"""Progress must be timely, bounded, and independent of JSON/model evidence."""

import io
import json
from dataclasses import FrozenInstanceError

import pytest

from vasp_copilot import cli
from vasp_copilot.agent.deepseek import DeepSeekBackend
from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.agent.mock import MockBackend
from vasp_copilot.agent.progress import StderrProgressReporter
from vasp_copilot.storage.repository import RunRepository
from vasp_copilot.tools.file_inspection import create_registry


class FlushedStream(io.StringIO):
    def __init__(self):
        super().__init__()
        self.flush_count = 0

    def flush(self):
        self.flush_count += 1
        super().flush()


def tool(name, args, identifier):
    return {"id": identifier, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args),
    }}


def test_native_batch_progress_is_flushed_before_wait_and_keeps_json_and_save(tmp_path, monkeypatch, capsys):
    stream = FlushedStream()
    monkeypatch.setattr(cli.sys, "stderr", stream)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "private-key")
    requests = []

    def transport(payload, config):
        requests.append(payload)
        assert f"decision {len(requests)}/2" in stream.getvalue()
        assert stream.flush_count > 0  # The waiting stage is visible before network work.
        if len(requests) == 1:
            return {"choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": "private-model-text", "tool_calls": [
                    tool("inspect_directory", {"directory": str(tmp_path)}, "first"),
                    tool("search_knowledge", {"query": "OSZICAR"}, "second"),
                ],
            }}]}
        assert "private-question" not in stream.getvalue()
        assert "Tool 2/2: search_knowledge -> success" in stream.getvalue()
        assert [m["tool_call_id"] for m in payload["messages"][-2:]] == ["first", "second"]
        assert "[progress" not in json.dumps(payload, ensure_ascii=False)
        return {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "private-answer",
        }}]}

    monkeypatch.setattr(cli, "DeepSeekBackend", lambda config: DeepSeekBackend(config, transport))
    database = tmp_path / "history.sqlite3"
    assert cli.main([str(tmp_path), "--agent", "--backend", "deepseek", "--progress",
                     "--question", "private-question", "--max-steps", "2", "--require-knowledge",
                     "--save-history", "--db", str(database)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "completed" and len(requests) == 2
    record = RunRepository(database).get(result["history_record"]["run_id"])
    assert record.run.model_dump() == {k: v for k, v in result.items() if k != "history_record"}
    lines = stream.getvalue().splitlines()
    assert len(lines) == stream.flush_count == 7
    assert lines[-1].endswith("Agent finished: completed (execution status only)")
    assert stream.getvalue().isascii()
    for private in ("private-key", "private-model-text", "private-answer", str(tmp_path)):
        assert private not in stream.getvalue()


def test_progress_is_default_off_and_does_not_leak_to_next_cli_call(tmp_path, capsys):
    assert cli.main([str(tmp_path), "--agent", "--progress"]) == 0
    first = capsys.readouterr()
    assert "[progress" in first.err and json.loads(first.out)["status"] == "completed"
    assert cli.main([str(tmp_path), "--agent"]) == 0
    second = capsys.readouterr()
    assert second.err == "" and json.loads(second.out)["status"] == "completed"


def test_failed_tool_and_deferred_final_are_visible_without_changing_decisions(tmp_path):
    events = []
    decisions = iter([
        {"type": "tool", "tool_name": "search_knowledge", "arguments": {}},
        {"type": "final", "answer": "premature"},
        {"type": "tool", "tool_name": "search_knowledge", "arguments": {"query": "OSZICAR"}},
        {"type": "final", "answer": "done"},
    ])

    class Backend:
        def decide(self, state, tools):
            return next(decisions)

    run = AgentLoop(Backend(), create_registry(tmp_path), 4, required_tools=("search_knowledge",),
                    on_progress=events.append).run("check", str(tmp_path))
    assert run.status == "completed" and run.decision_steps == 4
    assert [(e.step, e.status) for e in events if e.kind == "tool_finished"] == [(1, "error"), (3, "success")]
    assert [e.step for e in events if e.kind == "final_deferred"] == [2]
    assert events[-1].status == "completed" and len(run.state.completion_feedback) == 1


@pytest.mark.parametrize("mode, status", [("limit", "max_steps"), ("exception", "backend_error"), ("invalid", "backend_error")])
def test_failure_and_budget_exit_events_preserve_result(tmp_path, mode, status):
    events = []

    class Backend:
        def decide(self, state, tools):
            if mode == "exception":
                raise RuntimeError("private-exception")
            if mode == "invalid":
                return {"type": "invalid"}
            return {"type": "tool", "tool_name": "inspect_directory", "arguments": {"directory": str(tmp_path)}}

    run = AgentLoop(Backend(), create_registry(tmp_path), 1, on_progress=events.append).run("check", str(tmp_path))
    assert run.status == status and events[-1].kind == "run_finished" and events[-1].status == status
    assert events[0].kind == "decision_started" and "private-exception" not in repr(events)


def test_unknown_tool_name_is_not_printed_in_progress_or_warning(tmp_path, caplog):
    stream = FlushedStream()
    name = "private-name\npretend-log-line"

    class Backend:
        def decide(self, state, tools):
            return {"type": "tool", "tool_name": name, "arguments": {"private-arg": "value"}}

    run = AgentLoop(Backend(), create_registry(tmp_path), 1,
                    on_progress=StderrProgressReporter(stream)).run("check", str(tmp_path))
    assert run.state.history[0].observation.error.kind == "unknown_tool"
    assert "<unknown_tool>" in stream.getvalue() and "<unknown_tool>" in caplog.text
    assert "private-name" not in stream.getvalue() + caplog.text


def test_callback_failure_does_not_change_run_and_event_is_immutable(tmp_path, caplog):
    def failing(event):
        with pytest.raises(FrozenInstanceError):
            event.step = 999
        raise OSError("private-callback-detail")

    registry = create_registry(tmp_path)
    expected = AgentLoop(MockBackend(), registry).run("check", str(tmp_path))
    actual = AgentLoop(MockBackend(), registry, on_progress=failing).run("check", str(tmp_path))
    assert actual == expected
    assert "Progress callback failed" in caplog.text and "private-callback-detail" not in caplog.text


def test_callback_interrupt_propagates(tmp_path):
    def interrupt(event):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        AgentLoop(MockBackend(), create_registry(tmp_path), on_progress=interrupt).run("check", str(tmp_path))


@pytest.mark.parametrize("arguments", [["."], ["--history"], ["--show-run", "1"], ["--export-run", "1"], ["--history", "--agent"]])
def test_progress_rejects_non_agent_operations(arguments):
    with pytest.raises(SystemExit) as caught:
        cli.main([*arguments, "--progress"])
    assert caught.value.code == 2
