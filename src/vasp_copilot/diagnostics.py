"""Bounded OUTCAR settings, stop messages and local diagnostics. See docs/rules.md."""

import os
from pathlib import Path

from .schemas import ErrorInfo, Evidence, Finding, OutputDiagnosis
from .iterations import observe_last_iteration
from .electronic_diagnosis import diagnose_electronic_step
from .scf_settings import HEAD_BYTES, observe_electronic_settings, run_start_offsets

TAIL_BYTES = 64 * 1024
TIMING = "General timing and accounting informations for this job:"
IONIC = "reached required accuracy - stopping structural energy minimisation"
SISL_SOURCE = "https://sisl.readthedocs.io/en/stable/_modules/sisl/io/vasp/outcar.html"
ASE_SOURCE = "https://wiki.fysik.dtu.dk/ase/_modules/ase/calculators/vasp/vasp.html"


def diagnose_outcar(path: Path) -> OutputDiagnosis:
    """Read a bounded prefix/tail; absence and parameter counts never prove failure."""
    rules = [
        (TIMING, Finding(
            rule_id="outcar.timing_marker",
            explanation="Timing summary marker only; normal termination and convergence are not verified.",
            sources=[SISL_SOURCE],
        )),
        (IONIC, Finding(
            rule_id="outcar.ionic_stop_marker",
            explanation="Structural minimisation stop marker only; run boundaries, settings and all electronic steps are not verified.",
            sources=[ASE_SOURCE, "https://vasp.at/wiki/index.php/EDIFFG"],
        )),
    ]
    result = OutputDiagnosis(findings=[finding for _, finding in rules])
    try:
        with path.open("rb") as stream:
            initial_stat = os.fstat(stream.fileno())
            size = initial_stat.st_size
            start = max(0, size - TAIL_BYTES)
            prefix = stream.read(min(size, HEAD_BYTES + 1))
            if len(prefix) == size:
                data = prefix[start:]
            else:
                stream.seek(start)
                data = stream.read(size - start)
            final_stat = os.fstat(stream.fileno())
        result.snapshot_size = size
        result.read_start = start
        result.bytes_read = len(data)
        if (len(prefix) != min(size, HEAD_BYTES + 1) or len(data) != size - start
                or final_stat.st_size != size or final_stat.st_mtime_ns != initial_stat.st_mtime_ns):
            raise OSError("OUTCAR size, timestamp or read length changed during sampling; retry when stable")
    except OSError as exc:
        result.error = ErrorInfo(kind=type(exc).__name__, message=str(exc))
        return result

    result.last_iteration = observe_last_iteration(data, start)
    result.electronic_settings = observe_electronic_settings(prefix, size, later_run_offsets=run_start_offsets(data, start))
    result.electronic_step_diagnosis = diagnose_electronic_step(result.last_iteration, result.electronic_settings)
    offset = start
    # The first line may begin outside the sampled region; discard it.
    for index, line in enumerate(data.splitlines(keepends=True)):
        if (start == 0 or index > 0) and line.endswith(b"\n"):
            for marker, finding in rules:
                if line.strip() == marker.encode("ascii"):
                    finding.status = "marker_found"
                    # Retain only the latest match, keeping report size bounded.
                    finding.evidence = [Evidence(byte_offset=offset, text=marker)]
        offset += len(line)
    return result
