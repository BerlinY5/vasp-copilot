import json
from pathlib import Path

import pytest

from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.agent.mock import MockBackend
from vasp_copilot.agent.protocol import AgentRun, AgentState, Finish, ToolCall, ToolEvent, ToolResult
from vasp_copilot.reports.generator import ReportPathError, export_markdown, render_markdown
from vasp_copilot.schemas import ErrorInfo
from vasp_copilot.storage.repository import RunRepository
from vasp_copilot.tools.file_inspection import create_registry


def save_record(tmp_path, run):
    repository = RunRepository(tmp_path / "history.sqlite3")
    summary = repository.save(run, "mock")
    return repository.get(summary.id)


def sample_record(tmp_path, backend=None):
    directory = tmp_path / "calculation"
    directory.mkdir()
    (directory / "INCAR").write_text("IBRION=2; NSW=20\n", encoding="ascii")
    (directory / "OUTCAR").write_text(
        " NSW = 0\n IBRION = -1\nIteration 1( 3)\naborting loop because EDIFF is reached\n"
        "General timing and accounting informations for this job:\n", encoding="ascii")
    run = AgentLoop(backend or MockBackend(), create_registry(directory)).run("请检查计算", str(directory))
    return save_record(tmp_path, run)


def test_report_separates_log_evidence_references_and_backend_answer(tmp_path):
    record = sample_record(tmp_path)
    report = render_markdown(record)
    assert "# VASP-Copilot 诊断报告" in report
    assert "| Agent 运行状态 | completed |" in report
    assert "| electronic\\_convergence | unknown |" in report
    assert "| ionic\\_convergence | unknown |" in report
    assert "知识库参考资料（非计算文件证据）" in report
    assert "后端回答原文（未自动事实核验）" in report
    assert "https://vasp.at/wiki/index.php/EDIFF" in report
    evidence = record.run.state.history[1].observation.data["last_iteration"]["markers"][0]
    assert f"零起始字节偏移：{evidence['byte_offset']}" in report
    assert evidence["text"] in report
    assert record.run.answer in report
    assert report.index("工具证据与参考资料") < report.index("后端回答原文")


def test_complete_json_snapshot_can_be_recovered(tmp_path):
    record = sample_record(tmp_path)
    appendix = render_markdown(record).split("## 完整保存快照\n\n", 1)[1]
    lines = appendix.strip().splitlines()
    assert json.loads("\n".join(lines[1:-1])) == record.model_dump()


def test_rendering_does_not_open_files_and_is_deterministic(tmp_path, monkeypatch):
    record = sample_record(tmp_path)
    expected = render_markdown(record)
    def forbidden(*args, **kwargs):
        raise AssertionError("Rendering must not read calculation files or knowledge documents")
    monkeypatch.setattr(Path, "open", forbidden)
    assert render_markdown(record) == expected


def test_scan_report_keeps_input_output_parameters_and_mismatch(tmp_path):
    class ScanBackend:
        def decide(self, state, tools):
            if not state.history:
                return ToolCall(tool_name="scan_directory", arguments={"directory": state.directory})
            return Finish(answer="保留 unknown")
    report = render_markdown(sample_record(tmp_path, ScanBackend()))
    assert "INCAR 输入意图：relaxation" in report
    assert "OUTCAR 前缀参数观察" in report
    assert "输入与输出采样值比较" in report and "mismatched" in report
    assert "IBRION = -1" in report.replace("\\-", "-")
    assert "NSW = 0" in report


@pytest.mark.parametrize("status", ["backend_error", "max_steps"])
def test_failed_or_incomplete_run_exports_without_inventing_answer(tmp_path, status):
    run = AgentRun(status=status, decision_steps=1, state=AgentState(question="检查", directory="missing"),
                   error=ErrorInfo(kind=status, message="Stopped"))
    report = render_markdown(save_record(tmp_path, run))
    assert "本次运行未产生最终回答" in report
    assert "本次运行未记录工具观察" in report
    assert "运行错误或终止原因" in report
    assert "Stopped" in report


def test_tool_error_and_unknown_tool_data_remain_visible(tmp_path):
    events = [
        ToolEvent(step=1, call=ToolCall(tool_name="broken", arguments={}),
                  observation=ToolResult(tool_name="broken", status="error", error=ErrorInfo(kind="execution_error", message="FileNotFoundError"))),
        ToolEvent(step=2, call=ToolCall(tool_name="custom", arguments={}),
                  observation=ToolResult(tool_name="custom", status="success", data={"measurement": 123})),
    ]
    run = AgentRun(status="completed", decision_steps=3, state=AgentState(question="检查", directory=".", history=events), answer="unknown")
    report = render_markdown(save_record(tmp_path, run))
    assert "FileNotFoundError" in report and '"measurement": 123' in report
    assert "该工具没有专用报告视图" in report


def test_old_or_malformed_observation_falls_back_to_raw_data(tmp_path):
    record = sample_record(tmp_path)
    record.run.state.history[1].observation.data = {"legacy": "preserve me"}
    report = render_markdown(record)
    assert "不符合当前报告视图的数据格式" in report
    assert '"legacy": "preserve me"' in report


def test_untrusted_markdown_and_html_cannot_escape_literal_blocks(tmp_path):
    record = sample_record(tmp_path)
    payload = "```\n# 假结论\n<script>bad()</script>\n![remote](https://example.invalid/image)\n````"
    record.run.answer = payload
    record.run.state.question = payload
    record.run.state.history[0].observation.data["files"][0]["name"] = "x|y\n<script>bad()</script>"
    report = render_markdown(record)
    assert f"`````text\n{payload}\n`````" in report
    assert "x\\|y<br>&lt;script&gt;bad\\(\\)&lt;/script&gt;" in report
    assert "\n# 假结论\n" in report  # original text retained inside its longer fence


def test_export_is_utf8_and_refuses_overwrite(tmp_path):
    record = sample_record(tmp_path)
    target = tmp_path / "reports" / "报告.md"
    assert export_markdown(record, target) == target.resolve()
    before = target.read_bytes()
    assert before.decode("utf-8") == render_markdown(record)
    assert b"\r\n" not in before
    with pytest.raises(FileExistsError):
        export_markdown(record, target)
    assert target.read_bytes() == before


@pytest.mark.parametrize("filename", ["OUTCAR", "history.sqlite3", "report.html"])
def test_export_rejects_non_markdown_targets(tmp_path, filename):
    record = sample_record(tmp_path)
    target = tmp_path / "generated" / filename
    with pytest.raises(ReportPathError):
        export_markdown(record, target)
    assert not target.parent.exists()


def test_failed_write_removes_only_new_partial_output(tmp_path, monkeypatch):
    record = sample_record(tmp_path)
    target = tmp_path / "partial.md"
    original_open = Path.open
    class FailingWriter:
        def __init__(self, handle):
            self.handle = handle
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.handle.close()
        def write(self, text):
            self.handle.write(text[:20])
            raise OSError("disk full")
    def open_with_failure(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return FailingWriter(handle) if path == target and args[0] == "x" else handle
    monkeypatch.setattr(Path, "open", open_with_failure)
    with pytest.raises(OSError):
        export_markdown(record, target)
    assert not target.exists()
    assert (tmp_path / "history.sqlite3").exists()
