import gzip
import json
from pathlib import Path

from vasp_copilot import inspection
from vasp_copilot.agent.deepseek import DeepSeekBackend
from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.agent.mock import MockBackend
from vasp_copilot.agent.protocol import ToolCall, ToolResult
from vasp_copilot.cli import main
from vasp_copilot.config import DeepSeekConfig
from vasp_copilot.reports.generator import _observation, render_markdown
from vasp_copilot.schemas import ErrorInfo
from vasp_copilot.storage.repository import RunRepository
from vasp_copilot.tools.file_inspection import create_registry

FIXTURES = Path(__file__).parent / "fixtures" / "pymatgen"


def public_pair(directory):
    (directory / "OUTCAR").write_bytes(gzip.decompress((FIXTURES / "static_silicon.OUTCAR.gz").read_bytes()))
    (directory / "OSZICAR").write_bytes((FIXTURES / "static_silicon.OSZICAR").read_bytes())


def test_mock_cli_history_and_export_with_both_logs(tmp_path, capsys):
    public_pair(tmp_path)
    original = {name: (tmp_path / name).read_bytes() for name in ("OUTCAR", "OSZICAR")}
    db = tmp_path / "history.sqlite3"
    assert main([str(tmp_path), "--agent", "--save-history", "--db", str(db)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "completed" and result["decision_steps"] == 4
    assert [event["call"]["tool_name"] for event in result["state"]["history"]] == ["inspect_directory", "scan_directory", "search_knowledge"]
    assert "同次运行归属为 unknown" in result["answer"]
    assert "OSZICAR 字节偏移 1156" in result["answer"] and "OUTCAR 字节偏移 42249" in result["answer"]
    assert result["state"]["history"][1]["observation"]["data"]["output_comparison"]["status"] == "matched"
    output = tmp_path / "report.md"
    assert main(["--export-run", str(result["history_record"]["run_id"]), "--db", str(db), "--output", str(output)]) == 0
    capsys.readouterr()
    text = output.read_text(encoding="utf-8")
    assert "输出日志采样编号核对：matched" in text
    assert "零起始字节偏移：1156" in text and "同次运行归属：unknown" in text
    assert {name: (tmp_path / name).read_bytes() for name in original} == original


def test_scan_reuses_parsed_observations_without_extra_tail_reads(tmp_path, monkeypatch):
    public_pair(tmp_path)
    calls = {"outcar": 0, "oszicar": 0}
    original_outcar, original_oszicar = inspection.diagnose_outcar, inspection.inspect_oszicar
    def read_outcar(path):
        calls["outcar"] += 1
        return original_outcar(path)
    def read_oszicar(path):
        calls["oszicar"] += 1
        return original_oszicar(path)
    monkeypatch.setattr(inspection, "diagnose_outcar", read_outcar)
    monkeypatch.setattr(inspection, "inspect_oszicar", read_oszicar)
    result = inspection.scan_directory(tmp_path)
    assert result["output_comparison"]["status"] == "matched"
    assert calls == {"outcar": 1, "oszicar": 1}


def test_compare_tool_and_its_report_view(tmp_path):
    public_pair(tmp_path)
    result = create_registry(tmp_path).execute("compare_outputs", {"directory": str(tmp_path)})
    assert result.status == "success" and result.data["status"] == "matched"
    text = "\n".join(_observation("compare_outputs", result.data))
    assert "OSZICAR" in text and "1156" in text and "42249" in text
    assert "原始观察" not in text


def test_missing_files_are_unknown_inside_successful_tool_result(tmp_path):
    result = create_registry(tmp_path).execute("compare_outputs", {"directory": str(tmp_path)})
    assert result.status == "success" and result.data["status"] == "unknown"
    assert all("FileNotFoundError" in check["reason"] for check in result.data["checks"])


def test_mismatch_is_explained_without_claiming_failure(tmp_path):
    public_pair(tmp_path)
    path = tmp_path / "OSZICAR"
    path.write_bytes(path.read_bytes().replace(b"RMM:  13", b"RMM:  12"))
    run = AgentLoop(MockBackend(), create_registry(tmp_path)).run("检查", str(tmp_path))
    assert run.status == "completed" and "mismatched" in run.answer
    assert "OUTCAR=13，OSZICAR=12" in run.answer
    assert "编号不同不证明失败" in run.answer


def test_retrieval_failure_keeps_comparison_and_evidence(tmp_path, monkeypatch):
    public_pair(tmp_path)
    registry = create_registry(tmp_path)
    execute = registry.execute
    def fail_reference(name, arguments):
        if name == "search_knowledge":
            return ToolResult(tool_name=name, status="error", error=ErrorInfo(kind="execution_error", message="injected"))
        return execute(name, arguments)
    monkeypatch.setattr(registry, "execute", fail_reference)
    run = AgentLoop(MockBackend(), registry).run("检查", str(tmp_path))
    assert run.status == "completed" and "检索失败" in run.answer
    assert "核对：matched" in run.answer and "OSZICAR 字节偏移 1236" in run.answer


def test_file_disappearing_after_inventory_preserves_unknown(tmp_path):
    public_pair(tmp_path)
    class RemovingBackend(MockBackend):
        def decide(self, state, tools):
            decision = super().decide(state, tools)
            if isinstance(decision, ToolCall) and decision.tool_name == "scan_directory":
                (tmp_path / "OUTCAR").unlink()
            return decision
    run = AgentLoop(RemovingBackend(), create_registry(tmp_path)).run("检查", str(tmp_path))
    assert run.status == "completed" and run.decision_steps == 3
    assert "FileNotFoundError" in run.answer and "unknown" in run.answer


def test_saved_comparison_survives_file_changes_and_old_record_remains_uncompared(tmp_path):
    public_pair(tmp_path)
    run = AgentLoop(MockBackend(), create_registry(tmp_path)).run("检查", str(tmp_path))
    repository = RunRepository(tmp_path / "history.sqlite3")
    saved = repository.save(run, "mock")
    (tmp_path / "OSZICAR").write_bytes(b"changed after saving")
    record = repository.get(saved.id)
    assert record.run == run
    assert "核对：matched" in render_markdown(record)
    # A previous release's scan can include OSZICAR while lacking the new check.
    del record.run.state.history[1].observation.data["output_comparison"]
    # Its backend answer is also historical; inspect only the structured view here.
    text = "\n".join(_observation("scan_directory", record.run.state.history[1].observation.data))
    assert "未保存输出日志编号核对" in text
    assert "核对：matched" not in text


def test_deepseek_compare_tool_roundtrip_uses_injected_transport(tmp_path):
    public_pair(tmp_path)
    payloads = []
    def transport(payload, config):
        payloads.append(payload)
        if len(payloads) == 1:
            assert "compare_outputs" in [tool["function"]["name"] for tool in payload["tools"]]
            return {"choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{"id": "compare_1", "type": "function", "function": {
                    "name": "compare_outputs", "arguments": json.dumps({"directory": str(tmp_path)}),
                }}],
            }}]}
        observation = json.loads(payload["messages"][-1]["content"])
        assert observation["data"]["checks"][1]["oszicar_value"] == 13
        assert observation["data"]["run_identity"] == "unknown"
        return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "编号相同，运行归属未知"}}]}
    run = AgentLoop(DeepSeekBackend(DeepSeekConfig("test-only"), transport), create_registry(tmp_path)).run("核对编号", str(tmp_path))
    assert run.status == "completed" and len(payloads) == 2
