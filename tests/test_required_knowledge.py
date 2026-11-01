"""Regression for the online scan -> unperformed retrieval -> premature final."""

import json

import pytest

from vasp_copilot import cli
from vasp_copilot.agent.deepseek import DeepSeekBackend
from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.agent.protocol import AgentRun, Finish, ToolCall
from vasp_copilot.config import DeepSeekConfig
from vasp_copilot.reports.generator import render_markdown
from vasp_copilot.storage.repository import RunRepository
from vasp_copilot.tools.file_inspection import create_registry


class Decisions:
    def __init__(self, *decisions):
        self.decisions = iter(decisions)

    def decide(self, state, tools):
        return next(self.decisions)


def search(query="EDIFF"):
    return ToolCall(tool_name="search_knowledge", arguments={"query": query})


def native_tool(name, arguments, call_id):
    return {"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": {
            "name": name, "arguments": json.dumps(arguments),
        }}],
    }}]}


def native_final(answer):
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": answer}}]}


def test_native_premature_final_is_repaired_and_saved_via_cli(tmp_path, monkeypatch, capsys):
    directory = tmp_path / "calculation"
    directory.mkdir()
    (directory / "OUTCAR").write_text("Iteration 1( 3)\naborting loop because EDIFF is reached\n", encoding="ascii")
    payloads = []

    def transport(payload, config):
        payloads.append(payload)
        if len(payloads) == 1:
            assert '"missing_required_tools": ["search_knowledge"]' in payload["messages"][0]["content"]
            return native_tool("scan_directory", {"directory": str(directory)}, "scan_1")
        if len(payloads) == 2:
            assert '"knowledge_search_calls": 0' in payload["messages"][0]["content"]
            return native_final("References suggest... This premature answer must not be accepted.")
        if len(payloads) == 3:
            instruction = payload["messages"][0]["content"]
            assert "missing_required_tools" in instruction and '"step": 2' in instruction
            assert "Final answer not accepted" in instruction
            assert payload["messages"][-1]["tool_call_id"] == "scan_1"
            return native_tool("search_knowledge", {"query": "EDIFF"}, "search_3")
        assert len(payloads) == 4
        assert '"missing_required_tools": []' in payload["messages"][0]["content"]
        assert '"successful_knowledge_searches": 1' in payload["messages"][0]["content"]
        assert '"returned_reference_hits": 1' in payload["messages"][0]["content"]
        assert '"completion_feedback": null' in payload["messages"][0]["content"]
        assert payload["messages"][-1]["tool_call_id"] == "search_3"
        assert json.loads(payload["messages"][-1]["content"])["data"]["hits"]
        return native_final("Local EDIFF references retrieved; this calculation remains unknown.")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli, "DeepSeekBackend", lambda config: DeepSeekBackend(config, transport))
    database = tmp_path / "history.sqlite3"
    code = cli.main([str(directory), "--agent", "--backend", "deepseek", "--require-knowledge",
                     "--max-steps", "4", "--save-history", "--db", str(database)])
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result["status"] == "completed" and result["decision_steps"] == 4
    assert [event["step"] for event in result["state"]["history"]] == [1, 3]
    assert [event["call"]["tool_name"] for event in result["state"]["history"]] == ["scan_directory", "search_knowledge"]
    feedback = result["state"]["completion_feedback"]
    assert len(feedback) == 1 and feedback[0]["step"] == 2
    record = RunRepository(database).get(result["history_record"]["run_id"])
    assert record.run.state.completion_feedback[0].missing_tools == ["search_knowledge"]
    report = render_markdown(record)
    assert "Final-answer correction history" in report and "Required tools before completion" in report
    assert "This premature answer must not be accepted" not in report
    assert "test-key" not in report + json.dumps(payloads)


@pytest.mark.parametrize("budget", [1, 3])
def test_repeated_finals_cannot_bypass_requirement_or_budget(tmp_path, budget):
    backend = Decisions(*[Finish(answer="Answer without retrieval")] * budget)
    run = AgentLoop(backend, create_registry(), budget, required_tools=("search_knowledge",)).run("Retrieve", str(tmp_path))
    assert run.status == "max_steps" and run.answer is None
    assert run.decision_steps == budget and not run.state.history
    assert [item.step for item in run.state.completion_feedback] == list(range(1, budget + 1))


def test_failed_tool_call_does_not_satisfy_requirement(tmp_path):
    backend = Decisions(ToolCall(tool_name="search_knowledge", arguments={}), Finish(answer="Retrieval complete"))
    run = AgentLoop(backend, create_registry(), 2, required_tools=("search_knowledge",)).run("Retrieve", str(tmp_path))
    assert run.status == "max_steps" and run.answer is None
    assert run.state.history[0].observation.error.kind == "invalid_arguments"
    assert run.state.completion_feedback[0].missing_tools == ["search_knowledge"]


def test_zero_hits_can_finish_and_does_not_invent_sources(tmp_path):
    payloads = []

    def transport(payload, config):
        payloads.append(payload)
        if len(payloads) == 1:
            return native_tool("search_knowledge", {"query": "zzzz-no-matching-reference"}, "empty_1")
        assert '"successful_knowledge_searches": 1' in payload["messages"][0]["content"]
        assert '"returned_reference_hits": 0' in payload["messages"][0]["content"]
        return native_final("No local references matched; reference coverage is insufficient.")

    run = AgentLoop(DeepSeekBackend(DeepSeekConfig("test-key"), transport), create_registry(), 2,
                    required_tools=("search_knowledge",)).run("Retrieve", str(tmp_path))
    assert run.status == "completed" and run.state.history[0].observation.data["hits"] == []
    assert run.state.completion_feedback == []


def test_backend_cannot_erase_requirement_by_mutating_its_state_copy(tmp_path):
    class MutatingBackend:
        def decide(self, state, tools):
            state.required_tools.clear()
            return Finish(answer="Attempt to bypass the requirement")

    run = AgentLoop(MutatingBackend(), create_registry(), 1, required_tools=("search_knowledge",)).run("Retrieve", str(tmp_path))
    assert run.status == "max_steps" and run.state.required_tools == ["search_knowledge"]


def test_opt_in_does_not_change_default_final_behavior(tmp_path):
    run = AgentLoop(Decisions(Finish(answer="Direct answer")), create_registry()).run("Explain", str(tmp_path))
    assert run.status == "completed" and run.state.required_tools == []


@pytest.mark.parametrize("required", [("missing_tool",), "search_knowledge", (1,)])
def test_invalid_required_tools_rejected(required):
    with pytest.raises(ValueError, match="registered tool names"):
        AgentLoop(Decisions(), create_registry(), required_tools=required)


@pytest.mark.parametrize("arguments", [[], ["."], [".", "--agent"], ["--history", "--agent", "--backend", "deepseek"]])
def test_requirement_cli_rejects_non_deepseek_agent_usage(arguments, capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main([*arguments, "--require-knowledge"])
    assert caught.value.code == 2
    assert "--require-knowledge requires" in capsys.readouterr().err


def test_old_snapshot_defaults_to_no_requirement_or_feedback():
    run = AgentRun.model_validate({"status": "completed", "decision_steps": 1, "answer": "Legacy answer", "error": None,
                                   "state": {"question": "Inspect", "directory": ".", "history": []}})
    assert run.state.required_tools == [] and run.state.completion_feedback == []


def test_backend_error_after_rejection_preserves_feedback(tmp_path):
    class BrokenBackend:
        def decide(self, state, tools):
            if state.completion_feedback:
                raise RuntimeError("private detail")
            return Finish(answer="Premature final answer")

    run = AgentLoop(BrokenBackend(), create_registry(), 3, required_tools=("search_knowledge",)).run("Retrieve", str(tmp_path))
    assert run.status == "backend_error" and run.decision_steps == 2
    assert len(run.state.completion_feedback) == 1 and "private detail" not in run.model_dump_json()
