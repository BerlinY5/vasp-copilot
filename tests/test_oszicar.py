import hashlib
import json
from pathlib import Path

import pytest

from vasp_copilot import oszicar

FIXTURES = Path(__file__).parent / "fixtures" / "pymatgen"
HEADER = b"N E dE d eps ncg rms rms(c)\n"
ELECTRONIC = b"RMM: 13 -1.06452777428E+01 -1.9111E-06 -2.3579E-07 274 9.12E-04\n"
SUMMARY = b"1 F= -1.0645278E+01 E0= -1.0645278E+01 d E =0.0 mag= -0.0\n"


def parse(tmp_path, raw):
    path = tmp_path / "OSZICAR"
    path.write_bytes(raw)
    result = oszicar.inspect_oszicar(path)
    assert path.read_bytes() == raw
    # No non-standard JSON constants such as NaN or Infinity may escape.
    json.dumps(result.model_dump(), allow_nan=False)
    return result


def test_public_sample_values_positions_and_integrity(tmp_path):
    metadata = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))["oszicar_samples"]["static_silicon"]
    raw = (FIXTURES / metadata["path"]).read_bytes()
    assert len(raw) == 1314 == metadata["bytes"]
    assert hashlib.sha256(raw).hexdigest() == metadata["sha256"]
    result = parse(tmp_path, raw)
    assert result.status == "observed" and result.issues == [] and result.error is None
    assert (result.read_start, result.bytes_read, result.snapshot_size) == (0, 1314, 1314)
    electronic, summary = result.last_electronic_step, result.last_energy_summary
    assert (electronic.algorithm, electronic.iteration, electronic.ncg) == ("RMM", 13, 274)
    assert electronic.energy_ev == pytest.approx(-10.6452777428)
    assert electronic.delta_energy_ev == pytest.approx(-0.0000019111)
    assert electronic.delta_band_energy_ev == pytest.approx(-0.00000023579)
    assert electronic.rms == pytest.approx(0.000912) and electronic.rms_charge is None
    assert (summary.ionic_step, summary.free_energy_ev, summary.energy_sigma0_ev, summary.reported_delta_energy_ev) == (1, -10.645278, -10.645278, 0.0)
    assert (electronic.evidence.byte_offset, summary.evidence.byte_offset) == (1156, 1236)
    for evidence in (electronic.evidence, summary.evidence):
        assert evidence.file == "OSZICAR"
        assert raw[evidence.byte_offset:].split(b"\n", 1)[0].decode().rstrip("\r") == evidence.text
    assert result.electronic_convergence == result.ionic_convergence == result.normal_termination == "unknown"


@pytest.mark.parametrize("algorithm", ["DAV", "RMM", "CG"])
def test_fortran_numbers_optional_charge_and_crlf(tmp_path, algorithm):
    raw = f"{algorithm} : 2 -.2D+02 +.3d-03 -1e-4 56 .5E-2 .6E-3\r\n".encode()
    result = parse(tmp_path, raw)
    assert result.last_electronic_step.energy_ev == -20
    assert result.last_electronic_step.rms_charge == pytest.approx(0.0006)
    assert result.last_energy_summary is None


@pytest.mark.parametrize("suffix", [b"", b" mag= -0.5", b" mag= 0.1 -0.2 0.3"])
def test_summary_fields_remain_separate_from_electronic_delta(tmp_path, suffix):
    result = parse(tmp_path, ELECTRONIC + b"3 F= -10 E0= -9 d E= .2D-01" + suffix + b"\n")
    assert result.last_energy_summary.reported_delta_energy_ev == 0.02
    assert result.last_electronic_step.delta_energy_ev != 0.02


@pytest.mark.parametrize("last", [
    b"DAV: 1 -10 -0.1 -0.2 12 0.3\n", HEADER + b"DAV: 1 -10 -0.1 -0.2 12 0.3\n",
])
def test_new_cycle_discards_previous_summary(tmp_path, last):
    result = parse(tmp_path, ELECTRONIC + SUMMARY + last)
    assert result.last_electronic_step.iteration == 1
    assert result.last_energy_summary is None


def test_consecutive_summaries_do_not_attach_old_electronic_step(tmp_path):
    result = parse(tmp_path, ELECTRONIC + SUMMARY + SUMMARY.replace(b"1 F=", b"2 F="))
    assert result.last_energy_summary.ionic_step == 2
    assert result.last_electronic_step is None


@pytest.mark.parametrize("tail", [
    b"RMM: 14 -10", b"\xff\n", b"DAV: 14 ******** -1 -2 10 .1\n",
    b"1 T= 300 E= -10 F= -10 E0= -10\n", b"unknown message\n", HEADER,
    b"vasp.6 new run\n", b"RMM: 14 -10 -1 -2 10 .1 unexpected\n",
], ids=["incomplete", "encoding", "overflow_stars", "md", "unknown", "new_header", "new_run", "extra_fields"])
def test_unsupported_or_incomplete_tail_clears_old_candidates(tmp_path, tail):
    result = parse(tmp_path, ELECTRONIC + SUMMARY + tail)
    assert result.status == "unknown"
    assert result.last_electronic_step is None and result.last_energy_summary is None
    if tail != HEADER:
        assert result.issues


@pytest.mark.parametrize("value", ["NaN", "Inf", "1e999", "1e-999", "1e-999999999999999999999999999", "1" * 65],
                         ids=["nan", "inf", "overflow", "underflow", "huge_exponent", "long_token"])
def test_nonfinite_and_unrepresentable_numbers_are_not_observations(tmp_path, value):
    result = parse(tmp_path, ELECTRONIC + SUMMARY + f"DAV: 1 {value} -1 -2 10 .1\n".encode())
    assert result.status == "unknown" and result.issues


@pytest.mark.parametrize("row", [b"DAV: 0 -1 -2 -3 10 .1\n", b"DAV: 1 -1 -2 -3 10 -.1\n",
                                 b"0 F= -10 E0= -10 dE= 0\n", b"1 F= -10 E0= -10 dE= 0 mag= .1 .2\n"])
def test_invalid_counters_rms_and_suffix_rejected(tmp_path, row):
    assert parse(tmp_path, row).status == "unknown"


def test_recovery_after_unknown_record_keeps_warning_and_only_new_rows(tmp_path):
    result = parse(tmp_path, ELECTRONIC + SUMMARY + b"unsupported\n" + SUMMARY.replace(b"1 F=", b"2 F="))
    assert result.status == "observed" and result.issues
    assert result.last_electronic_step is None and result.last_energy_summary.ionic_step == 2


def test_bounded_window_preserves_absolute_evidence_offsets(tmp_path):
    prefix = b"x" * (oszicar.TAIL_BYTES + 50) + b"\n"
    raw = prefix + ELECTRONIC + SUMMARY
    result = parse(tmp_path, raw)
    assert result.bytes_read == oszicar.TAIL_BYTES
    assert result.read_start == len(raw) - oszicar.TAIL_BYTES
    assert result.last_electronic_step.evidence.byte_offset == len(prefix)
    assert result.last_energy_summary.evidence.byte_offset == len(prefix) + len(ELECTRONIC)
    assert result.issues


def test_partial_first_line_cannot_be_misread_as_complete_record(tmp_path, monkeypatch):
    monkeypatch.setattr(oszicar, "TAIL_BYTES", len(SUMMARY))
    result = parse(tmp_path, b"malformed prefix " + SUMMARY)
    assert result.status == "unknown" and result.last_energy_summary is None


def test_empty_bom_and_blank_lines(tmp_path):
    assert parse(tmp_path, b"").status == "unknown"
    result = parse(tmp_path, b"\xef\xbb\xbf" + ELECTRONIC + SUMMARY + b"\n")
    assert result.last_electronic_step.evidence.byte_offset == 0
    assert result.last_electronic_step.evidence.text.startswith("\ufeffRMM:")


def test_missing_and_unreadable_files_are_structured(tmp_path, monkeypatch):
    assert oszicar.inspect_oszicar(tmp_path / "missing").error.kind == "FileNotFoundError"
    def denied(*args, **kwargs):
        raise PermissionError("denied")
    monkeypatch.setattr(Path, "open", denied)
    result = oszicar.inspect_oszicar(tmp_path / "OSZICAR")
    assert result.error.kind == "PermissionError" and result.status == "unknown"


def test_short_read_is_not_parsed(tmp_path, monkeypatch):
    path = tmp_path / "OSZICAR"
    path.write_bytes(ELECTRONIC + SUMMARY)
    original = Path.open
    class ShortReader:
        def __enter__(self):
            self.handle = original(path, "rb")
            return self
        def __exit__(self, *args):
            self.handle.close()
        def fileno(self):
            return self.handle.fileno()
        def seek(self, offset):
            return self.handle.seek(offset)
        def read(self, count):
            return self.handle.read(count - 1)
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: ShortReader())
    result = oszicar.inspect_oszicar(path)
    assert result.error.kind == "OSError" and result.last_energy_summary is None
