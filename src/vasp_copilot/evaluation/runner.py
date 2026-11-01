"""Run isolated Mock scenarios and compare traces against explicit expectations."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from ..agent.loop import AgentLoop
from ..agent.mock import MockBackend
from ..agent.protocol import AgentRun
from ..schemas import ErrorInfo, Schema
from ..tools.file_inspection import create_registry
from .cases import OSZICAR_SAMPLE, REVISION, SAMPLES, Scenario, build_scenarios, load_samples
from .observations import observe_comparison, observe_oszicar

QUESTION = "请根据文件证据检查计算状态，并区分参考资料与本次计算的证据。"
REFERENCE_SOURCES = {
    "electronic.md": "https://vasp.at/wiki/index.php/EDIFF",
    "ionic.md": "https://vasp.at/wiki/index.php/EDIFFG",
    "outcar.md": "https://vasp.at/wiki/index.php/OUTCAR",
}


class CheckResult(Schema):
    name: str
    expected: Any
    actual: Any
    passed: bool


class CaseResult(Schema):
    name: str
    description: str
    origin: str
    status: Literal["passed", "failed", "error"]
    checks: list[CheckResult]
    error: ErrorInfo | None = None


class EvaluationReport(Schema):
    suite: str = "mock-agent-v2"
    backend: Literal["mock"] = "mock"
    scope: str = "固定离线场景的流程与证据回归；不是 LLM 回答质量评分或 VASP 科学正确性验证。"
    fixture_revision: str = REVISION
    fixture_sha256: dict[str, str]
    status: Literal["passed", "failed"]
    total: int
    passed: int
    failed: int
    cases: list[CaseResult]


class _FailingBackend(MockBackend):
    def decide(self, state, tools):
        if state.history:
            raise RuntimeError("injected evaluation failure")
        return super().decide(state, tools)


def _fingerprints(directory: Path) -> dict[str, str] | None:
    if not directory.exists():
        return None
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "directory"
            for path in directory.iterdir()}


def check_run(case: Scenario, run: AgentRun, directory: Path) -> list[CheckResult]:
    """Compare recorded observations; file evidence is checked against scenario bytes."""
    history = run.state.history
    observed: dict[str, Any] = {
        "status": run.status, "decision_steps": run.decision_steps,
        "tools": [event.call.tool_name for event in history],
        "tool_statuses": [event.observation.status for event in history],
        "tool_errors": [event.observation.error.kind if event.observation.error else None for event in history],
        "tool_error_messages": [event.observation.error.message if event.observation.error else None for event in history],
        "run_error": run.error.kind if run.error else None,
        "run_error_message": run.error.message if run.error else None,
        "answer_present": bool(run.answer and run.answer.strip()),
    }
    checks = []

    def check(name, expected, actual):
        checks.append(CheckResult(name=name, expected=expected, actual=actual, passed=expected == actual))

    check("question_preserved", QUESTION, run.state.question)
    check("directory_preserved", True, run.state.directory == str(directory))
    check("event_steps", list(range(1, len(history) + 1)), [event.step for event in history])
    check("observation_names", [event.call.tool_name for event in history],
          [event.observation.tool_name for event in history])
    observations = []
    for event in history:
        data = event.observation.data
        if data is None:
            continue
        if event.call.tool_name == "scan_directory":
            check("scan.calculation_status", "unknown", data["calculation_status"])
            check("scan.directory_preserved", True, data["directory"] == str(directory))
            # A scan contains the same observations as the individual tools. Score
            # the saved payload only; never call the parser to generate expectations.
            observations.extend([("diagnose_outcar", data["diagnostics"]),
                                 ("inspect_oszicar", data["oszicar"]),
                                 ("compare_outputs", data["output_comparison"])])
        else:
            observations.append((event.call.tool_name, data))
    for tool_name, data in observations:
        if tool_name == "diagnose_outcar":
            last = data["last_iteration"]
            observed["iteration"] = [last["ionic_step"], last["electronic_step"], last["status"],
                                     last["header"]["byte_offset"] if last["header"] else None,
                                     [marker["byte_offset"] for marker in last["markers"]]]
            states = {finding["rule_id"]: finding["status"] for finding in data["findings"]}
            observed["marker_states"] = [states.get("outcar.timing_marker"), states.get("outcar.ionic_stop_marker")]
            for finding in data["findings"]:
                check(f"{finding['rule_id']}.evidence_count", 1 if finding["status"] == "marker_found" else 0,
                      len(finding["evidence"]))
            check("diagnosis_error", None, data["error"])
            check("overall_verdicts", ["unknown"] * 3,
                  [data[key] for key in ("electronic_convergence", "ionic_convergence", "normal_termination")])
            raw = case.files["OUTCAR"]
            check("sample_coverage", [max(0, len(raw) - 65536), min(len(raw), 65536), len(raw)],
                  [data["read_start"], data["bytes_read"], data["snapshot_size"]])
            evidence = ([last["header"]] if last["header"] else []) + last["markers"]
            evidence += [item for finding in data["findings"] for item in finding["evidence"]]
            for index, item in enumerate(evidence):
                offset = item["byte_offset"]
                valid = (item["file"] == "OUTCAR" and data["read_start"] <= offset < len(raw) and
                         (offset == 0 or raw[offset - 1:offset] == b"\n") and
                         raw[offset:].split(b"\n", 1)[0].decode("utf-8").strip() == item["text"].strip())
                check(f"outcar_evidence_{index}", True, valid)
        elif tool_name == "inspect_oszicar":
            observed.update(observe_oszicar(data, case.files, check))
        elif tool_name == "compare_outputs":
            observed.update(observe_comparison(data, case.files, check))
        elif tool_name == "inspect_incar":
            observed["input_type"] = data["calculation_type"]
            observed["input_error"] = data["error"]["kind"] if data["error"] else None
            observed["input_parameters"] = {item["name"]: item["value"] for item in data["parameters"]}
            for index, item in enumerate(data["parameters"]):
                lines = case.files["INCAR"].decode("utf-8").splitlines()
                line = item["line_number"]
                check(f"incar_evidence_{index}", True, 1 <= line <= len(lines) and lines[line - 1] == item["text"])
        elif tool_name == "search_knowledge":
            hits = data["hits"]
            observed["reference_documents"] = sorted(hit["document"] for hit in hits)
            for index, hit in enumerate(hits):
                check(f"reference_source_{index}", REFERENCE_SOURCES.get(hit["document"]), hit["source"])
                check(f"reference_label_{index}", "reference", hit["evidence_type"])
                check(f"answer_source_{index}", True, hit["source"] in (run.answer or ""))
    for name, expected in case.expected.items():
        check(name, expected, observed.get(name))
    return checks


def run_scenario(case: Scenario, root: Path) -> CaseResult:
    directory = root / case.name
    checks = []
    try:
        # Tools return canonical paths; Windows temp roots can use short aliases.
        directory = directory.resolve()
        if not case.missing_directory:
            directory.mkdir()
            for name, raw in case.files.items():
                (directory / name).write_bytes(raw)
        before = _fingerprints(directory)
        backend = _FailingBackend() if case.fail_backend else MockBackend()
        run = AgentLoop(backend, create_registry(allowed_directory=directory), case.max_steps).run(QUESTION, str(directory))
        checks = check_run(case, run, directory)
        after = _fingerprints(directory)
        checks.append(CheckResult(name="inputs_unchanged", expected=before, actual=after, passed=before == after))
    except Exception as exc:
        return CaseResult(name=case.name, description=case.description, origin=case.origin, status="error",
                          checks=checks, error=ErrorInfo(kind="evaluation_error", message=type(exc).__name__))
    return CaseResult(name=case.name, description=case.description, origin=case.origin,
                      status="passed" if all(check.passed for check in checks) else "failed", checks=checks)


def evaluate(fixtures: Path) -> EvaluationReport:
    samples = load_samples(fixtures)
    with TemporaryDirectory(prefix="vasp-copilot-eval-") as temporary:
        results = [run_scenario(case, Path(temporary)) for case in build_scenarios(samples)]
    passed = sum(result.status == "passed" for result in results)
    digests = {name: digest for name, (_, digest) in SAMPLES.items()}
    digests["static_silicon_oszicar"] = OSZICAR_SAMPLE[1]
    return EvaluationReport(fixture_sha256=digests,
                            status="passed" if passed == len(results) else "failed",
                            total=len(results), passed=passed, failed=len(results) - passed, cases=results)
