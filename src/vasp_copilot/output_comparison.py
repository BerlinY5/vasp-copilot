"""Compare sampled output row numbers without inferring shared run identity."""

from pathlib import Path

from .diagnostics import diagnose_outcar
from .oszicar import inspect_oszicar
from .schemas import OszicarObservation, OutputDiagnosis, OutputStepCheck, OutputStepComparison


def compare_output_steps(outcar: OutputDiagnosis, oszicar: OszicarObservation) -> OutputStepComparison:
    """Pure comparison; preserve values and evidence even when a check is unknown."""
    iteration = outcar.last_iteration
    electronic, summary = oszicar.last_electronic_step, oszicar.last_energy_summary
    ionic = OutputStepCheck(
        name="ionic_step", outcar_value=iteration.ionic_step,
        oszicar_value=summary.ionic_step if summary else None,
        outcar_evidence=iteration.header.model_copy(deep=True) if iteration.header else None,
        oszicar_evidence=summary.evidence.model_copy(deep=True) if summary else None, reason="",
    )
    electron = OutputStepCheck(
        name="electronic_step", outcar_value=iteration.electronic_step,
        oszicar_value=electronic.iteration if electronic else None,
        outcar_evidence=iteration.header.model_copy(deep=True) if iteration.header else None,
        oszicar_evidence=electronic.evidence.model_copy(deep=True) if electronic else None, reason="",
    )
    problems = []
    if outcar.error:
        problems.append(f"OUTCAR read failed ({outcar.error.kind})")
    if oszicar.error:
        problems.append(f"OSZICAR read failed ({oszicar.error.kind})")
    if iteration.issues:
        problems.append("The last OUTCAR iteration has parsing or truncation issues")
    if iteration.status == "conflicting_markers":
        problems.append("The last OUTCAR iteration contains conflicting messages")
    if oszicar.issues:
        problems.append("OSZICAR has sampling or parsing issues")
    if iteration.header is None or iteration.ionic_step is None or iteration.electronic_step is None:
        problems.append("A reliable OUTCAR iteration header and step numbers are missing")
    if oszicar.status != "observed":
        problems.append("No supported OSZICAR record was retained")
    if problems:
        ionic.reason = electron.reason = "; ".join(problems)
    else:
        if summary is None:
            ionic.reason = "The ionic step number is missing from the OSZICAR summary"
        else:
            ionic.status = "matched" if ionic.outcar_value == ionic.oszicar_value else "mismatched"
            ionic.reason = "The sampled ionic step numbers match" if ionic.status == "matched" else "The sampled ionic step numbers differ; the cause is undetermined"
        if ionic.status != "matched":
            electron.reason = "The ionic step numbers are not confirmed to match; electronic step numbers are not compared and missing numbers are not inferred"
        elif electronic is None:
            electron.reason = "The OSZICAR electronic iteration row is missing"
        elif electronic.evidence.byte_offset >= summary.evidence.byte_offset:
            electron.reason = "The order of the OSZICAR electronic row and summary is unreliable"
        else:
            electron.status = "matched" if electron.outcar_value == electron.oszicar_value else "mismatched"
            electron.reason = "The sampled electronic step numbers match" if electron.status == "matched" else "The sampled electronic step numbers differ; the cause is undetermined"
    checks = [ionic, electron]
    status = ("mismatched" if any(check.status == "mismatched" for check in checks) else
              "matched" if all(check.status == "matched" for check in checks) else "unknown")
    return OutputStepComparison(status=status, checks=checks)


def inspect_output_comparison(directory: Path) -> OutputStepComparison:
    """Read each file once; the directory has already been checked by the tool."""
    outcar = diagnose_outcar(directory / "OUTCAR")
    oszicar = inspect_oszicar(directory / "OSZICAR")
    return compare_output_steps(outcar, oszicar)
