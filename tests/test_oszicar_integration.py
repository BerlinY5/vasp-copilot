import json
from pathlib import Path

from vasp_copilot.agent.deepseek import DeepSeekBackend
from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.agent.mock import MockBackend
from vasp_copilot.agent.protocol import Finish, ToolCall
from vasp_copilot.cli import main
from vasp_copilot.config import DeepSeekConfig
from vasp_copilot.inspection import scan_directory
from vasp_copilot.reports.generator import render_markdown
from vasp_copilot.storage.repository import RunRepository
from vasp_copilot.tools.file_inspection import create_registry

FIXTURE = Path(__file__).parent / "fixtures" / "pymatgen" / "static_silicon.OSZICAR"


def test_scan_and_cli_include_oszicar_with_no_overall_verdict(tmp_path, capsys):
    (tmp_path / "OSZICAR").write_bytes(FIXTURE.read_bytes())
    assert main([str(tmp_path)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["calculation_status"] == "unknown"
    assert data["oszicar"]["last_electronic_step"]["iteration"] == 13
    assert data["oszicar"]["last_energy_summary"]["free_energy_ev"] == -10.645278


def test_mock_oszicar_branch_and_saved_report_roundtrip(tmp_path):
    (tmp_path / "OSZICAR").write_bytes(FIXTURE.read_bytes())
    (tmp_path / "INCAR").write_text("IBRION=2; NSW=20\n", encoding="utf-8")
    run = AgentLoop(MockBackend(), create_registry(tmp_path)).run("检查", str(tmp_path))
    assert run.status == "completed" and run.decision_steps == 3
    assert [event.call.tool_name for event in run.state.history] == ["inspect_directory", "inspect_oszicar"]
    assert "OSZICAR 字节偏移 1156" in run.answer and "unknown" in run.answer
    repository = RunRepository(tmp_path / "history.sqlite3")
    saved = repository.save(run, "mock")
    record = repository.get(saved.id)
    assert record.run == run
    report = render_markdown(record)
    assert "OSZICAR 电子迭代与能量摘要" in report
    assert "零起始字节偏移：1236" in report and "-10.645278" in report
    assert "https://vasp.at/wiki/index.php/OSZICAR" in report


def test_scan_report_compatibility_with_older_history(tmp_path):
    class Scanner:
        def decide(self, state, tools):
            if not state.history:
                return ToolCall(tool_name="scan_directory", arguments={"directory": state.directory})
            return Finish(answer="保留 unknown")
    run = AgentLoop(Scanner(), create_registry(tmp_path)).run("检查", str(tmp_path))
    del run.state.history[0].observation.data["oszicar"]
    del run.state.history[0].observation.data["output_comparison"]
    repository = RunRepository(tmp_path / "history.sqlite3")
    saved = repository.save(run, "mock")
    record = repository.get(saved.id)
    report = render_markdown(record)
    assert "未保存 OSZICAR 解析" in report
    assert "不符合当前报告视图" not in report
    assert "oszicar" not in record.run.state.history[0].observation.data


def test_scan_view_renders_new_observation(tmp_path):
    from vasp_copilot.reports.generator import _observation
    (tmp_path / "OSZICAR").write_bytes(FIXTURE.read_bytes())
    text = "\n".join(_observation("scan_directory", scan_directory(tmp_path)))
    assert "OSZICAR 电子迭代与能量摘要" in text and "1156" in text


def test_native_tool_call_observation_roundtrip_offline(tmp_path):
    (tmp_path / "OSZICAR").write_bytes(FIXTURE.read_bytes())
    payloads = []
    def transport(payload, config):
        payloads.append(payload)
        if len(payloads) == 1:
            assert "inspect_oszicar" in [tool["function"]["name"] for tool in payload["tools"]]
            return {"choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{"id": "oszicar_1", "type": "function", "function": {
                    "name": "inspect_oszicar", "arguments": json.dumps({"directory": str(tmp_path)}),
                }}],
            }}]}
        message = payload["messages"][-1]
        assert message["role"] == "tool" and message["tool_call_id"] == "oszicar_1"
        observation = json.loads(message["content"])
        assert observation["data"]["last_energy_summary"]["evidence"]["byte_offset"] == 1236
        return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "观察到摘要，整体 unknown"}}]}
    run = AgentLoop(DeepSeekBackend(DeepSeekConfig("test-only"), transport), create_registry(tmp_path)).run("查看 OSZICAR", str(tmp_path))
    assert run.status == "completed" and len(payloads) == 2


def test_oszicar_external_file_target_rejected(tmp_path, monkeypatch):
    selected = tmp_path / "selected"
    selected.mkdir()
    original = Path.resolve
    def resolved(path, *args, **kwargs):
        return tmp_path / "external" if path == selected / "OSZICAR" else original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", resolved)
    result = create_registry(selected).execute("inspect_oszicar", {"directory": str(selected)})
    assert result.error.kind == "execution_error" and "PermissionError" in result.error.message


def test_missing_file_is_reported_inside_successful_tool_result(tmp_path):
    result = create_registry(tmp_path).execute("inspect_oszicar", {"directory": str(tmp_path)})
    assert result.status == "success"
    assert result.data["error"]["kind"] == "FileNotFoundError"
    assert result.data["status"] == "unknown"
