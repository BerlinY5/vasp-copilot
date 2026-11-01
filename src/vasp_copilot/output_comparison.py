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
        problems.append(f"OUTCAR 读取失败（{outcar.error.kind}）")
    if oszicar.error:
        problems.append(f"OSZICAR 读取失败（{oszicar.error.kind}）")
    if iteration.issues:
        problems.append("OUTCAR 最后迭代存在解析或截断问题")
    if iteration.status == "conflicting_markers":
        problems.append("OUTCAR 最后迭代存在相互冲突的消息")
    if oszicar.issues:
        problems.append("OSZICAR 存在采样或解析问题")
    if iteration.header is None or iteration.ionic_step is None or iteration.electronic_step is None:
        problems.append("缺少可靠的 OUTCAR 迭代标题和编号")
    if oszicar.status != "observed":
        problems.append("OSZICAR 未保留支持的记录")
    if problems:
        ionic.reason = electron.reason = "；".join(problems)
    else:
        if summary is None:
            ionic.reason = "缺少 OSZICAR 摘要中的离子步编号"
        else:
            ionic.status = "matched" if ionic.outcar_value == ionic.oszicar_value else "mismatched"
            ionic.reason = "两处采样离子步编号相同" if ionic.status == "matched" else "两处采样离子步编号不同，原因未确定"
        if ionic.status != "matched":
            electron.reason = "离子步编号未确认相同，不比较电子步编号，也不推算缺失编号"
        elif electronic is None:
            electron.reason = "缺少 OSZICAR 电子迭代行"
        elif electronic.evidence.byte_offset >= summary.evidence.byte_offset:
            electron.reason = "OSZICAR 电子行与摘要顺序不可靠"
        else:
            electron.status = "matched" if electron.outcar_value == electron.oszicar_value else "mismatched"
            electron.reason = "两处采样电子步编号相同" if electron.status == "matched" else "两处采样电子步编号不同，原因未确定"
    checks = [ionic, electron]
    status = ("mismatched" if any(check.status == "mismatched" for check in checks) else
              "matched" if all(check.status == "matched" for check in checks) else "unknown")
    return OutputStepComparison(status=status, checks=checks)


def inspect_output_comparison(directory: Path) -> OutputStepComparison:
    """Read each file once; the directory has already been checked by the tool."""
    outcar = diagnose_outcar(directory / "OUTCAR")
    oszicar = inspect_oszicar(directory / "OSZICAR")
    return compare_output_steps(outcar, oszicar)
