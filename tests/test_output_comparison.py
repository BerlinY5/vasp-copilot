import gzip
from pathlib import Path

import pytest

from vasp_copilot.diagnostics import diagnose_outcar
from vasp_copilot.oszicar import inspect_oszicar
from vasp_copilot.output_comparison import compare_output_steps
from vasp_copilot.schemas import ErrorInfo

FIXTURES = Path(__file__).parent / "fixtures" / "pymatgen"
OUTCAR = b"Iteration 1( 13)\n"
ELECTRONIC = b"RMM: 13 -10 -1e-6 -2e-7 10 .1\n"
SUMMARY = b"1 F= -10 E0= -10 d E= 0\n"


def observations(tmp_path, outcar=OUTCAR, oszicar=ELECTRONIC + SUMMARY):
    (tmp_path / "OUTCAR").write_bytes(outcar)
    (tmp_path / "OSZICAR").write_bytes(oszicar)
    return diagnose_outcar(tmp_path / "OUTCAR"), inspect_oszicar(tmp_path / "OSZICAR")


def test_public_pair_matches_numbers_but_not_run_identity(tmp_path):
    first = gzip.decompress((FIXTURES / "static_silicon.OUTCAR.gz").read_bytes())
    second = (FIXTURES / "static_silicon.OSZICAR").read_bytes()
    outcar, oszicar = observations(tmp_path, first, second)
    report = compare_output_steps(outcar, oszicar)
    assert report.status == "matched" and report.run_identity == "unknown"
    ionic, electronic = report.checks
    assert (ionic.outcar_value, ionic.oszicar_value) == (1, 1)
    assert (electronic.outcar_value, electronic.oszicar_value) == (13, 13)
    assert ionic.outcar_evidence.byte_offset == electronic.outcar_evidence.byte_offset == 42249
    assert ionic.oszicar_evidence.byte_offset == 1236
    assert electronic.oszicar_evidence.byte_offset == 1156
    assert outcar.electronic_convergence == oszicar.electronic_convergence == "unknown"


def test_electronic_mismatch_only_with_same_observed_ionic_number(tmp_path):
    outcar, oszicar = observations(tmp_path, oszicar=ELECTRONIC.replace(b"13", b"12") + SUMMARY)
    report = compare_output_steps(outcar, oszicar)
    assert report.status == "mismatched"
    assert [item.status for item in report.checks] == ["matched", "mismatched"]
    assert (report.checks[1].outcar_value, report.checks[1].oszicar_value) == (13, 12)
    assert "the cause is undetermined" in report.checks[1].reason


def test_different_ionic_numbers_do_not_claim_electronic_alignment(tmp_path):
    outcar, oszicar = observations(tmp_path, oszicar=ELECTRONIC + SUMMARY.replace(b"1 F", b"2 F"))
    report = compare_output_steps(outcar, oszicar)
    assert report.status == "mismatched"
    assert [item.status for item in report.checks] == ["mismatched", "unknown"]
    assert (report.checks[1].outcar_value, report.checks[1].oszicar_value) == (13, 13)
    assert "are not compared" in report.checks[1].reason


@pytest.mark.parametrize("missing", ["OUTCAR", "OSZICAR"])
def test_missing_file_blocks_comparison(tmp_path, missing):
    observations(tmp_path)
    (tmp_path / missing).unlink()
    report = compare_output_steps(diagnose_outcar(tmp_path / "OUTCAR"), inspect_oszicar(tmp_path / "OSZICAR"))
    assert report.status == "unknown"
    assert all(item.status == "unknown" and f"{missing} read failed" in item.reason for item in report.checks)


@pytest.mark.parametrize("outcar, oszicar", [
    (OUTCAR + b"partial", ELECTRONIC + SUMMARY),
    (OUTCAR, ELECTRONIC + SUMMARY + b"partial"),
    (OUTCAR + b"Iteration bad\n", ELECTRONIC + SUMMARY),
    (OUTCAR, b"unsupported\n" + ELECTRONIC + SUMMARY),
    (OUTCAR + b"aborting loop because EDIFF is reached\naborting loop EDIFF was not reached (unconverged)\n", ELECTRONIC + SUMMARY),
    (b"", ELECTRONIC + SUMMARY),
    (OUTCAR, b"1 T=300 E=-10 F=-10 E0=-10\n"),
], ids=["outcar_truncated", "oszicar_truncated", "bad_header", "recovered_with_warning", "conflict", "empty", "unsupported_md"])
def test_uncertain_context_never_uses_matching_retained_numbers(tmp_path, outcar, oszicar):
    report = compare_output_steps(*observations(tmp_path, outcar, oszicar))
    assert report.status == "unknown" and all(item.status == "unknown" and item.reason for item in report.checks)


def test_electronic_row_without_summary_does_not_guess_ionic_number(tmp_path):
    report = compare_output_steps(*observations(tmp_path, oszicar=ELECTRONIC))
    assert report.status == "unknown"
    assert report.checks[0].oszicar_value is None
    assert report.checks[1].oszicar_value == 13 and report.checks[1].status == "unknown"


def test_summary_without_electronic_row_keeps_only_ionic_comparison(tmp_path):
    report = compare_output_steps(*observations(tmp_path, oszicar=SUMMARY))
    assert report.status == "unknown"
    assert [item.status for item in report.checks] == ["matched", "unknown"]


def test_new_cycle_does_not_reuse_previous_summary(tmp_path):
    report = compare_output_steps(*observations(tmp_path, outcar=b"Iteration 2( 1)\n",
        oszicar=ELECTRONIC + SUMMARY + b"DAV: 1 -10 -1 -2 10 .1\n"))
    assert report.status == "unknown"
    assert report.checks[0].oszicar_value is None
    assert report.checks[1].outcar_value == report.checks[1].oszicar_value == 1
    assert report.checks[1].status == "unknown"


def test_reversed_record_order_cannot_align_electronic_number(tmp_path):
    outcar, oszicar = observations(tmp_path)
    oszicar.last_electronic_step.evidence.byte_offset = oszicar.last_energy_summary.evidence.byte_offset
    report = compare_output_steps(outcar, oszicar)
    assert report.status == "unknown" and report.checks[1].status == "unknown"
    assert "order" in report.checks[1].reason


def test_limited_oszicar_window_with_warning_remains_unknown(tmp_path):
    outcar, oszicar = observations(tmp_path, oszicar=b"x" * 66000 + b"\n" + ELECTRONIC + SUMMARY)
    assert oszicar.last_energy_summary is not None and oszicar.issues
    assert compare_output_steps(outcar, oszicar).status == "unknown"


def test_read_error_blocks_otherwise_usable_values(tmp_path):
    outcar, oszicar = observations(tmp_path)
    outcar.error = ErrorInfo(kind="OSError", message="short read")
    report = compare_output_steps(outcar, oszicar)
    assert report.status == "unknown"
    assert report.checks[1].outcar_value == 13 and report.checks[1].outcar_evidence is not None


def test_pure_comparison_does_not_read_mutate_or_alias_inputs(tmp_path, monkeypatch):
    outcar, oszicar = observations(tmp_path)
    before = outcar.model_dump(), oszicar.model_dump()
    def forbidden(*args, **kwargs):
        raise AssertionError("Pure comparison must not read files")
    monkeypatch.setattr(Path, "open", forbidden)
    report = compare_output_steps(outcar, oszicar)
    # A missing EDIFF message alone does not make the explicit row numbers unusable.
    assert outcar.last_iteration.status == "unknown" and report.status == "matched"
    report.checks[0].outcar_evidence.text = "changed copy"
    report.checks[1].oszicar_evidence.text = "changed copy"
    assert (outcar.model_dump(), oszicar.model_dump()) == before
