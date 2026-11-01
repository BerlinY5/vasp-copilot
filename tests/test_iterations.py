import json

import pytest

from vasp_copilot.cli import main
from vasp_copilot.diagnostics import TAIL_BYTES, diagnose_outcar
from vasp_copilot.iterations import NOT_REACHED, REACHED, observe_last_iteration


def header(ionic=1, electronic=1):
    return f" ----- Iteration {ionic}( {electronic}) -----\r\n".encode()


@pytest.mark.parametrize("marker,status", [(REACHED, "reached_marker"), (NOT_REACHED, "not_reached_marker")])
def test_messages_and_byte_evidence(marker, status):
    prefix = "title \u6d4b\u8bd5\n".encode()
    data = prefix + header(2, 8) + b"---" + marker + b"---\r\n"
    result = observe_last_iteration(data, 0)
    assert (result.ionic_step, result.electronic_step, result.status) == (2, 8, status)
    assert result.header.byte_offset == len(prefix)
    assert result.markers[0].byte_offset == len(prefix) + len(header(2, 8))


@pytest.mark.parametrize("next_header", [header(1, 2), header(2, 1)])
def test_new_iteration_never_inherits_previous_message(next_header):
    result = observe_last_iteration(header() + REACHED + b"\n" + next_header, 0)
    assert result.status == "unknown"
    assert not result.markers


def test_later_failure_replaces_earlier_success():
    result = observe_last_iteration(header() + REACHED + b"\n" + header(2, 7) + NOT_REACHED + b"\n", 0)
    assert result.status == "not_reached_marker"
    assert result.ionic_step == 2


@pytest.mark.parametrize("marker", [REACHED, NOT_REACHED])
def test_orphan_message_unknown(marker):
    result = observe_last_iteration(marker + b"\n", 0)
    assert result.status == "unknown"
    assert result.header is None
    assert result.issues


def test_conflicting_messages_are_explicit():
    result = observe_last_iteration(header() + REACHED + b"\n" + NOT_REACHED + b"\n", 0)
    assert result.status == "conflicting_markers"
    assert len(result.markers) == 2


def test_repeated_messages_keep_bounded_evidence():
    result = observe_last_iteration(header() + (REACHED + b"\n") * 100, 0)
    assert result.status == "reached_marker"
    assert len(result.markers) == 1


@pytest.mark.parametrize("suffix", [b"vasp.6.4.3 new run\n", b"vasp.5.4.4 new run\n", b"Iteration broken\n"])
def test_new_run_or_bad_header_discards_old_context(suffix):
    result = observe_last_iteration(header() + REACHED + b"\n" + suffix, 0)
    assert result.status == "unknown"
    assert result.header is None


@pytest.mark.parametrize("suffix", [b"Iteration 2(", b"vasp.6.", b"partial text"])
def test_truncated_end_invalidates_status(suffix):
    result = observe_last_iteration(header() + REACHED + b"\n" + suffix, 0)
    assert result.status == "unknown"
    assert result.issues


def test_clipped_first_header_not_used():
    result = observe_last_iteration(header() + REACHED + b"\n", 100)
    assert result.status == "unknown"
    assert result.header is None


def test_partial_window_reports_absolute_offsets():
    result = observe_last_iteration(b"clipped\n" + header() + REACHED + b"\n", 100)
    assert result.header.byte_offset == 108
    assert result.status == "reached_marker"


def test_unrelated_quoted_message_not_matched():
    result = observe_last_iteration(header() + b"quote: " + REACHED + b"\n", 0)
    assert result.status == "unknown"


def test_header_outside_tail_does_not_authorize_message(tmp_path):
    path = tmp_path / "OUTCAR"
    path.write_bytes(header() + b"x" * TAIL_BYTES + b"\n" + REACHED + b"\n")
    report = diagnose_outcar(path)
    assert report.bytes_read == TAIL_BYTES
    assert report.last_iteration.status == "unknown"


def test_cli_exposes_observation_without_global_verdict(tmp_path, capsys):
    path = tmp_path / "OUTCAR"
    content = header(3, 9) + REACHED + b"\n"
    path.write_bytes(content)
    assert main([str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["diagnostics"]["last_iteration"]["status"] == "reached_marker"
    assert report["diagnostics"]["electronic_convergence"] == "unknown"
    assert report["calculation_status"] == "unknown"
    assert path.read_bytes() == content
