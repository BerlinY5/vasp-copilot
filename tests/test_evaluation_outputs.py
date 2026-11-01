"""Negative controls for the v2 evaluator using complete recorded Agent traces."""

import shutil
from pathlib import Path

import pytest

from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.agent.mock import MockBackend
from vasp_copilot.evaluation.cases import FixtureError, build_scenarios, load_samples
from vasp_copilot.evaluation.runner import QUESTION, check_run, run_scenario
from vasp_copilot.tools.file_inspection import create_registry

FIXTURES = Path(__file__).parent / "fixtures" / "pymatgen"


@pytest.mark.parametrize("path, value, expected_check", [
    (("oszicar", "last_electronic_step", "iteration"), 12, "oszicar_electronic"),
    (("oszicar", "last_electronic_step", "energy_ev"), -999.0, "oszicar_electronic"),
    (("oszicar", "last_energy_summary", "reported_delta_energy_ev"), 1.0, "oszicar_summary"),
    (("oszicar", "last_electronic_step", "evidence", "byte_offset"), 1157, "oszicar.electronic.evidence"),
    (("oszicar", "last_energy_summary", "evidence", "text"), "invented", "oszicar.summary.evidence"),
    (("oszicar", "last_energy_summary", "evidence", "file"), "OUTCAR", "oszicar.summary.evidence"),
    (("oszicar", "bytes_read"), 1, "oszicar.sample_coverage"),
    (("oszicar", "electronic_convergence"), "converged", "oszicar.overall_verdicts"),
    (("oszicar", "issues"), ["invented problem"], "oszicar_has_issues"),
    (("output_comparison", "status"), "unknown", "comparison_status"),
    (("output_comparison", "run_identity"), "matched", "comparison.run_identity"),
    (("output_comparison", "checks", 0, "outcar_value"), 2, "comparison_checks"),
    (("output_comparison", "checks", 1, "status"), "mismatched", "comparison_checks"),
    (("output_comparison", "checks", 1, "oszicar_evidence"), None, "comparison_checks"),
    (("output_comparison", "checks", 1, "oszicar_evidence", "text"), "invented", "comparison.electronic_step.oszicar_evidence"),
    (("output_comparison", "checks", 0, "outcar_evidence", "byte_offset"), 42250, "comparison.ionic_step.outcar_evidence"),
    (("output_comparison", "checks", 0, "reason"), " ", "comparison.ionic_step.reason_present"),
    (("output_comparison", "checks"), [], "comparison_checks"),
    (("diagnostics", "normal_termination"), "successful", "overall_verdicts"),
    (("calculation_status",), "converged", "scan.calculation_status"),
    (("directory",), "wrong-directory", "scan.directory_preserved"),
])
def test_detects_corruption_inside_full_scan(monkeypatch, tmp_path, path, value, expected_check):
    original = AgentLoop.run

    def corrupted(self, question, directory):
        run = original(self, question, directory)
        target = run.state.history[1].observation.data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return run

    monkeypatch.setattr(AgentLoop, "run", corrupted)
    case = next(case for case in build_scenarios(load_samples(FIXTURES)) if case.name == "paired_outputs")
    result = run_scenario(case, tmp_path)
    assert result.status == "failed"
    assert expected_check in {check.name for check in result.checks if not check.passed}


@pytest.mark.parametrize("name", ["ionic_mismatch", "truncated_oszicar", "missing_oszicar_summary", "unsupported_oszicar"])
def test_rejects_promoting_uncertain_comparison_to_match(monkeypatch, tmp_path, name):
    original = AgentLoop.run

    def corrupted(self, question, directory):
        run = original(self, question, directory)
        comparison = run.state.history[1].observation.data["output_comparison"]
        comparison["status"] = "matched"
        for item in comparison["checks"]:
            item["status"] = "matched"
        return run

    monkeypatch.setattr(AgentLoop, "run", corrupted)
    case = next(case for case in build_scenarios(load_samples(FIXTURES)) if case.name == name)
    result = run_scenario(case, tmp_path)
    assert result.status == "failed"
    failed = {check.name for check in result.checks if not check.passed}
    assert {"comparison_status", "comparison_checks"} <= failed


def test_scenario_accepts_equivalent_directory_spelling(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    case = next(case for case in build_scenarios(load_samples(FIXTURES)) if case.name == "paired_outputs")
    result = run_scenario(case, existing / "..")
    assert result.status == "passed", [check.name for check in result.checks if not check.passed]


@pytest.mark.parametrize("replacement", [None, b"short", b"x" * 1314, b"x" * 1315],
                         ids=["missing", "short", "changed_hash", "oversized"])
def test_oszicar_fixture_is_pinned(tmp_path, replacement):
    for name in ["static_silicon.OUTCAR.gz", "relaxation.OUTCAR.gz"]:
        shutil.copyfile(FIXTURES / name, tmp_path / name)
    if replacement is not None:
        (tmp_path / "static_silicon.OSZICAR").write_bytes(replacement)
    with pytest.raises(FixtureError, match=r"static_silicon\.OSZICAR"):
        load_samples(tmp_path)


def test_scoring_uses_saved_observations_without_reading_or_reparsing(tmp_path, monkeypatch):
    case = next(case for case in build_scenarios(load_samples(FIXTURES)) if case.name == "paired_outputs")
    for name, raw in case.files.items():
        (tmp_path / name).write_bytes(raw)
    run = AgentLoop(MockBackend(), create_registry(allowed_directory=tmp_path), 6).run(QUESTION, str(tmp_path))

    def forbidden(*args, **kwargs):
        raise AssertionError("Scoring must use independent expected values and saved scenario bytes")

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr("vasp_copilot.oszicar.inspect_oszicar", forbidden)
    monkeypatch.setattr("vasp_copilot.output_comparison.compare_output_steps", forbidden)
    monkeypatch.setattr("vasp_copilot.diagnostics.diagnose_outcar", forbidden)
    checks = check_run(case, run, tmp_path)
    assert checks and all(check.passed for check in checks)


def test_scenario_mutations_and_expectations_do_not_come_from_parsers():
    samples = load_samples(FIXTURES)
    original = dict(samples)
    cases = {case.name: case for case in build_scenarios(samples)}
    raw = samples["static_silicon_oszicar"]
    assert samples == original
    assert cases["paired_outputs"].files["OSZICAR"] == raw
    assert cases["ionic_mismatch"].files["OSZICAR"] == raw[:1239] + b"2" + raw[1240:]
    assert cases["electronic_mismatch"].files["OSZICAR"] == raw[:1163] + b"2" + raw[1164:]
    assert cases["missing_oszicar_summary"].files["OSZICAR"] == raw[:1236]
    assert cases["truncated_oszicar"].files["OSZICAR"] == raw[:-1]
    expected = cases["ionic_mismatch"].expected["comparison_checks"]
    assert expected == [["ionic_step", "mismatched", 1, 2, 42249, 1236],
                        ["electronic_step", "unknown", 13, 13, 42249, 1156]]
