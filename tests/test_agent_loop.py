import json

import pytest

from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.agent.mock import MockBackend
from vasp_copilot.agent.protocol import Finish, ToolCall
from vasp_copilot.cli import main
from vasp_copilot.tools.file_inspection import create_registry


def run_mock(directory, max_steps=6):
    return AgentLoop(MockBackend(), create_registry(), max_steps).run("检查计算", str(directory))


def test_first_observation_changes_next_tool(tmp_path):
    output_dir, input_dir = tmp_path / "output", tmp_path / "input"
    output_dir.mkdir()
    input_dir.mkdir()
    (output_dir / "OUTCAR").write_text("Iteration 1( 3)\naborting loop because EDIFF is reached\n", encoding="ascii")
    (input_dir / "INCAR").write_text("IBRION=2;NSW=20\n", encoding="ascii")
    first, second = run_mock(output_dir), run_mock(input_dir)
    assert [e.call.tool_name for e in first.state.history] == ["inspect_directory", "diagnose_outcar", "search_knowledge"]
    assert [e.call.tool_name for e in second.state.history] == ["inspect_directory", "inspect_incar"]
    assert first.status == second.status == "completed"
    assert first.decision_steps == 4 and second.decision_steps == 3
    assert first.state.history[1].observation.data["last_iteration"]["markers"]
    assert "unknown" in first.answer and "relaxation" in second.answer


def test_empty_directory_finishes_after_one_tool(tmp_path):
    result = run_mock(tmp_path)
    assert result.status == "completed" and len(result.state.history) == 1
    assert result.decision_steps == 2
    assert "证据不足" in result.answer


def test_missing_directory_error_is_observed_and_explained(tmp_path):
    result = run_mock(tmp_path / "missing")
    assert result.status == "completed"
    assert result.state.history[0].observation.error.kind == "execution_error"
    assert "FileNotFoundError" in result.answer


def test_tool_success_with_file_error_not_misreported(tmp_path):
    class RemovingBackend(MockBackend):
        def decide(self, state, tools):
            decision = super().decide(state, tools)
            if isinstance(decision, ToolCall) and decision.tool_name == "diagnose_outcar":
                (tmp_path / "OUTCAR").unlink()
            return decision
    (tmp_path / "OUTCAR").write_text("example", encoding="ascii")
    result = AgentLoop(RemovingBackend(), create_registry()).run("检查", str(tmp_path))
    assert "FileNotFoundError" in result.answer
    assert result.state.history[-1].observation.status == "success"
    assert result.state.history[-1].observation.data["error"] is not None


def test_max_steps_bounds_calls_and_preserves_history(tmp_path):
    class RepeatingBackend:
        def decide(self, state, tools):
            return ToolCall(tool_name="inspect_directory", arguments={"directory": state.directory})
    result = AgentLoop(RepeatingBackend(), create_registry(), 2).run("检查", str(tmp_path))
    assert result.status == "max_steps" and result.answer is None
    assert [event.step for event in result.state.history] == [1, 2]
    assert result.decision_steps == 2


def test_limit_counts_final_decision(tmp_path):
    result = run_mock(tmp_path, max_steps=1)
    assert result.status == "max_steps" and len(result.state.history) == 1


@pytest.mark.parametrize("bad", [0, -1, 101, True, 1.5])
def test_invalid_limit_rejected(bad):
    with pytest.raises(ValueError):
        AgentLoop(MockBackend(), create_registry(), bad)


@pytest.mark.parametrize("raw", [
    {"type": "other"}, {"type": "tool", "tool_name": "inspect_directory", "arguments": []},
    {"type": "final", "answer": ""}, {"type": "final", "answer": "ok", "extra": 1},
])
def test_invalid_backend_decision_stops_without_tool_execution(tmp_path, raw):
    class InvalidBackend:
        def decide(self, state, tools):
            return raw
    result = AgentLoop(InvalidBackend(), create_registry()).run("检查", str(tmp_path))
    assert result.status == "backend_error"
    assert result.state.history == []


def test_backend_failure_keeps_prior_history(tmp_path):
    class FailingBackend(MockBackend):
        def decide(self, state, tools):
            if state.history:
                raise RuntimeError("private backend detail")
            return super().decide(state, tools)
    result = AgentLoop(FailingBackend(), create_registry()).run("检查", str(tmp_path))
    assert result.status == "backend_error" and len(result.state.history) == 1
    assert "private backend detail" not in result.model_dump_json()


def test_backend_can_correct_invalid_tool_arguments(tmp_path):
    class CorrectingBackend:
        def decide(self, state, tools):
            if not state.history:
                return ToolCall(tool_name="inspect_directory", arguments={})
            if state.history[-1].observation.status == "error":
                assert state.history[-1].observation.error.kind == "invalid_arguments"
                return ToolCall(tool_name="inspect_directory", arguments={"directory": state.directory})
            return Finish(answer="已修正参数并获得文件检查结果")
    result = AgentLoop(CorrectingBackend(), create_registry()).run("检查", str(tmp_path))
    assert result.status == "completed"
    assert [e.observation.status for e in result.state.history] == ["error", "success"]


def test_unknown_tool_observation_can_reach_backend(tmp_path):
    class UnknownToolBackend:
        def decide(self, state, tools):
            if not state.history:
                return ToolCall(tool_name="not_registered", arguments={})
            assert state.history[-1].observation.error.kind == "unknown_tool"
            return Finish(answer="工具不存在，停止")
    result = AgentLoop(UnknownToolBackend(), create_registry()).run("检查", str(tmp_path))
    assert result.status == "completed" and len(result.state.history) == 1


def test_backend_cannot_modify_recorded_history(tmp_path):
    class MutatingBackend(MockBackend):
        def decide(self, state, tools):
            if state.history:
                state.history.clear()
                state.question = "changed"
                return Finish(answer="done")
            return super().decide(state, tools)
    result = AgentLoop(MutatingBackend(), create_registry()).run("original", str(tmp_path))
    assert result.state.question == "original" and len(result.state.history) == 1


def test_reusing_loop_does_not_accumulate_history(tmp_path):
    loop = AgentLoop(MockBackend(), create_registry())
    first, second = loop.run("one", str(tmp_path)), loop.run("two", str(tmp_path))
    assert len(first.state.history) == len(second.state.history) == 1
    assert second.state.question == "two"


def test_cli_agent_serializes_history(tmp_path, capsys):
    assert main([str(tmp_path), "--agent", "--question", "检查输出"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "completed"
    assert report["state"]["question"] == "检查输出"
    assert report["state"]["history"][0]["call"]["tool_name"] == "inspect_directory"


def test_cli_step_limit_exit_code(tmp_path, capsys):
    assert main([str(tmp_path), "--agent", "--max-steps", "1"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "max_steps"


def test_keyboard_interrupt_propagates(tmp_path):
    class InterruptingBackend:
        def decide(self, state, tools):
            raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        AgentLoop(InterruptingBackend(), create_registry()).run("检查", str(tmp_path))
