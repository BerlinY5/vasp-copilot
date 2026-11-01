"""Regression for run 6: a native response contains several tool requests."""

import copy
import gzip
import json
from pathlib import Path

import pytest

from vasp_copilot import cli
from vasp_copilot.agent.deepseek import DeepSeekBackend, DeepSeekHistoryReplayError, _history_messages
from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.agent.protocol import AgentState, ToolEvent
from vasp_copilot.config import DeepSeekConfig
from vasp_copilot.reports.generator import render_markdown
from vasp_copilot.storage.repository import RunRepository
from vasp_copilot.tools.file_inspection import create_registry

FIXTURES = Path(__file__).parent / "fixtures" / "pymatgen"


def call(name, arguments, call_id):
    return {"id": call_id, "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments),
    }}


def batch(*calls):
    return {"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": "读取文件并检索参考", "tool_calls": list(calls),
    }}]}


def final():
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "保留 unknown"}}]}


def test_native_batch_scan_and_search_roundtrip_cli_save_report(tmp_path, monkeypatch, capsys):
    directory = tmp_path / "calculation"
    directory.mkdir()
    (directory / "OUTCAR").write_bytes(gzip.decompress((FIXTURES / "static_silicon.OUTCAR.gz").read_bytes()))
    (directory / "OSZICAR").write_bytes((FIXTURES / "static_silicon.OSZICAR").read_bytes()[:1236])
    calls = [call("scan_directory", {"directory": str(directory)}, "scan_1"),
             call("search_knowledge", {"query": "OUTCAR"}, "search_1")]
    payloads = []

    def transport(payload, config):
        payloads.append(payload)
        if len(payloads) == 1:
            return batch(*calls)
        assert len(payloads) == 2
        assistant, scan, search = payload["messages"][-3:]
        assert assistant["role"] == "assistant" and assistant["tool_calls"] == calls
        assert assistant["content"] == "读取文件并检索参考"
        assert scan["role"] == search["role"] == "tool"
        assert [scan["tool_call_id"], search["tool_call_id"]] == ["scan_1", "search_1"]
        assert json.loads(scan["content"])["data"]["output_comparison"]["status"] == "unknown"
        assert json.loads(search["content"])["data"]["hits"]
        assert '"missing_required_tools": []' in payload["messages"][0]["content"]
        return final()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli, "DeepSeekBackend", lambda config: DeepSeekBackend(config, transport))
    database = tmp_path / "history.sqlite3"
    assert cli.main([str(directory), "--agent", "--backend", "deepseek", "--require-knowledge",
                     "--max-steps", "2", "--save-history", "--db", str(database)]) == 0
    output = json.loads(capsys.readouterr().out)
    record = RunRepository(database).get(output["history_record"]["run_id"])
    assert record.summary.decision_steps == 2 and record.summary.tool_calls == 2
    assert [(event.step, event.batch_index, event.batch_size) for event in record.run.state.history] == [(1, 1, 2), (1, 2, 2)]
    assert not record.run.state.completion_feedback
    assert _history_messages(record.run.state) == payloads[1]["messages"][-3:]
    report = render_markdown(record)
    assert "同轮调用 1/2" in report and "同轮调用 2/2" in report
    assert "test-key" not in report


@pytest.mark.parametrize("problem, expected", [
    ("json", "DeepSeekToolArgumentsError"),
    ("duplicate", "DeepSeekDuplicateToolCallError"),
    ("envelope", "DeepSeekToolCallFormatError"),
    ("oversized", "DeepSeekToolCallLimitError"),
])
def test_entire_batch_is_parsed_before_any_execution(tmp_path, monkeypatch, problem, expected):
    calls = [call("search_knowledge", {"query": "OUTCAR"}, "one"),
             call("search_knowledge", {"query": "EDIFF"}, "two")]
    if problem == "json":
        calls[1]["function"]["arguments"] = "invalid private text"
    elif problem == "duplicate":
        calls[1]["id"] = "one"
    elif problem == "envelope":
        calls[1]["function"] = None
    else:
        calls = [call("search_knowledge", {"query": "OUTCAR"}, str(i)) for i in range(9)]
    registry = create_registry(tmp_path)
    executions = []
    monkeypatch.setattr(registry, "execute", lambda *args: executions.append(args))
    backend = DeepSeekBackend(DeepSeekConfig("test-key"), lambda *args: batch(*calls))
    run = AgentLoop(backend, registry).run("检查", str(tmp_path))
    assert run.status == "backend_error" and run.error.message == expected
    assert not executions and not run.state.history
    assert "private" not in run.model_dump_json()


def test_batch_errors_are_returned_and_required_search_can_be_repaired(tmp_path):
    payloads = []

    def transport(payload, config):
        payloads.append(payload)
        if len(payloads) == 1:
            return batch(call("search_knowledge", {}, "bad_search"),
                         call("inspect_directory", {"directory": str(tmp_path)}, "inventory"))
        if len(payloads) == 2:
            results = [json.loads(message["content"]) for message in payload["messages"][-2:]]
            assert [result["status"] for result in results] == ["error", "success"]
            assert results[0]["error"]["kind"] == "invalid_arguments"
            return final()  # Rejected: the batch's search failed.
        if len(payloads) == 3:
            assert "Final answer not accepted" in payload["messages"][0]["content"]
            return batch(call("search_knowledge", {"query": "OUTCAR"}, "fixed_search"))
        assert [message["role"] for message in payload["messages"][2:]] == ["assistant", "tool", "tool", "assistant", "tool"]
        return final()

    run = AgentLoop(DeepSeekBackend(DeepSeekConfig("test-key"), transport), create_registry(tmp_path), 4,
                    required_tools=("search_knowledge",)).run("检查", str(tmp_path))
    assert run.status == "completed" and run.decision_steps == 4
    assert [event.step for event in run.state.history] == [1, 1, 3]
    assert run.state.completion_feedback[0].step == 2


@pytest.mark.parametrize("name, arguments, error", [
    ("scan_directory", {"directory": "OUTSIDE"}, "execution_error"),
    ("not_registered", {}, "unknown_tool"),
])
def test_batch_does_not_bypass_registry_checks(tmp_path, name, arguments, error):
    arguments = {"directory": str(tmp_path.parent)} if arguments else arguments
    replies = iter([batch(call(name, arguments, "bad"), call("search_knowledge", {"query": "OUTCAR"}, "good")), final()])
    backend = DeepSeekBackend(DeepSeekConfig("test-key"), lambda *args: next(replies))
    run = AgentLoop(backend, create_registry(tmp_path), 2).run("检查", str(tmp_path))
    assert run.status == "completed"
    assert run.state.history[0].observation.error.kind == error
    assert run.state.history[1].observation.status == "success"


def batch_state(directory):
    calls = [call("search_knowledge", {"query": "OUTCAR"}, str(i)) for i in range(2)]
    backend = DeepSeekBackend(DeepSeekConfig("test-key"), lambda *args: batch(*calls))
    return AgentLoop(backend, create_registry(directory), 1).run("检查", str(directory)).state


@pytest.mark.parametrize("problem", ["missing_result", "reversed", "size", "content", "duplicate_id", "split_step"])
def test_incomplete_or_corrupt_batch_history_never_reaches_transport(tmp_path, problem):
    state = batch_state(tmp_path)
    if problem == "missing_result":
        state.history.pop()
    elif problem == "reversed":
        state.history.reverse()
    elif problem == "size":
        state.history[1].batch_size = 3
    elif problem == "content":
        state.history[1].call.assistant_content = "changed"
    elif problem == "duplicate_id":
        state.history[1].call.call_id = state.history[0].call.call_id
    else:
        state.history[1].step = 2

    def forbidden(*args):
        raise AssertionError("Invalid replay must not send a request")

    with pytest.raises(DeepSeekHistoryReplayError):
        DeepSeekBackend(DeepSeekConfig("test-key"), forbidden).decide(state, create_registry().describe())


def test_last_budgeted_decision_preserves_whole_eight_call_batch(tmp_path):
    requests = []

    def transport(payload, config):
        requests.append(payload)
        return batch(*[call("search_knowledge", {"query": "OUTCAR"}, str(i)) for i in range(8)])

    run = AgentLoop(DeepSeekBackend(DeepSeekConfig("test-key"), transport), create_registry(tmp_path), 1).run("检索", str(tmp_path))
    assert run.status == "max_steps" and run.answer is None and len(requests) == 1
    assert len(run.state.history) == 8 and {event.step for event in run.state.history} == {1}
    assert [event.batch_index for event in run.state.history] == list(range(1, 9))
    assert len(_history_messages(run.state)) == 9  # One assistant + eight tool messages.


def test_old_single_call_history_defaults_to_single_batch(tmp_path):
    state = batch_state(tmp_path)
    old_event = state.history[0].model_dump()
    del old_event["batch_index"], old_event["batch_size"]
    loaded = AgentState(question="旧记录", directory=str(tmp_path), history=[ToolEvent.model_validate(old_event)])
    assert loaded.history[0].batch_index == loaded.history[0].batch_size == 1
    assert len(_history_messages(loaded)) == 2


def test_single_then_batch_replay_keeps_original_assistant_groups(tmp_path):
    payloads = []

    def transport(payload, config):
        payloads.append(payload)
        if len(payloads) == 1:
            return batch(call("inspect_directory", {"directory": str(tmp_path)}, "inventory"))
        if len(payloads) == 2:
            return batch(call("search_knowledge", {"query": "OUTCAR"}, "outcar"),
                         call("search_knowledge", {"query": "EDIFF"}, "ediff"))
        assistants = [message for message in payload["messages"] if message["role"] == "assistant"]
        assert [[call["id"] for call in message["tool_calls"]] for message in assistants] == [["inventory"], ["outcar", "ediff"]]
        return final()

    run = AgentLoop(DeepSeekBackend(DeepSeekConfig("test-key"), transport), create_registry(tmp_path), 3).run("检查", str(tmp_path))
    assert run.status == "completed" and [event.step for event in run.state.history] == [1, 2, 2]


@pytest.mark.parametrize("calls", [[], [{"type": "final", "answer": "nested"}], [
    {"type": "tool", "tool_name": "search_knowledge", "arguments": {}, "call_id": "same"},
    {"type": "tool", "tool_name": "search_knowledge", "arguments": {}, "call_id": "same"},
]])
def test_generic_batch_decision_is_validated_before_execution(tmp_path, calls):
    class InvalidBackend:
        def decide(self, state, tools):
            return {"type": "tools", "calls": copy.deepcopy(calls)}

    run = AgentLoop(InvalidBackend(), create_registry(tmp_path)).run("检查", str(tmp_path))
    assert run.status == "backend_error" and run.state.history == []
