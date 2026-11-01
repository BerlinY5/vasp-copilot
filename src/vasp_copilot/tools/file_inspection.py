"""Register the existing directory scanner without duplicating parsing logic."""

from pathlib import Path

from pydantic import Field

from ..agent.tool_registry import ToolRegistry
from ..inspection import VASP_FILES, inspect_file, scan_directory
from ..diagnostics import diagnose_outcar
from ..input_context import inspect_incar
from ..oszicar import inspect_oszicar
from ..output_comparison import inspect_output_comparison
from ..schemas import FileInspection, InputContext, OszicarObservation, OutputDiagnosis, OutputStepComparison, ScanReport, Schema
from .knowledge_search import register_knowledge_tool


class ScanDirectoryArgs(Schema):
    directory: str = Field(min_length=1, description="Path to the VASP calculation directory")


class DirectoryInventory(Schema):
    directory: str
    files: list[FileInspection]


def create_registry(allowed_directory: Path | None = None) -> ToolRegistry:
    """Build an independent registry containing the read-only diagnostic tools."""
    registry = ToolRegistry()
    allowed = allowed_directory.expanduser().resolve() if allowed_directory is not None else None

    def checked_directory(value: str) -> Path:
        directory = Path(value).expanduser().resolve()
        if allowed is not None:
            if directory != allowed:
                raise PermissionError("Tool directory differs from the selected directory")
            for name in VASP_FILES:
                if not (directory / name).resolve().is_relative_to(allowed):
                    raise PermissionError("VASP file resolves outside the selected directory")
        return directory

    @registry.register(
        "scan_directory",
        "Combined read-only inspection. Returns files (availability), input_context (explicit INCAR settings), "
        "output_context (OUTCAR prefix IBRION/NSW with byte evidence, even if INCAR is missing), "
        "context_comparison, diagnostics (OUTCAR tail, electronic_settings for prefix EDIFF/NELM/ICHARG/ALGO/IALGO, "
        "and electronic_step_diagnosis with qualified setting considerations), oszicar (tail rows), and output_comparison "
        "(cross-file step checks). Prefer this for questions needing several of these observations; "
        "do not also call the overlapping individual tools unless a specific gap or refresh requires it. "
        "Reads are separate, not an atomic snapshot; results do not prove convergence or run identity.",
        ScanDirectoryArgs, ScanReport,
    )
    def scan(args: ScanDirectoryArgs) -> dict:
        return scan_directory(checked_directory(args.directory))

    @registry.register("inspect_directory",
                       "Check known file availability only, without parsing content or calculation settings. "
                       "Missing INCAR does not establish that IBRION/NSW are absent from OUTCAR. "
                       "Use scan_directory for OUTCAR parameter evidence; it also includes this inventory.",
                       ScanDirectoryArgs, DirectoryInventory)
    def inventory(args: ScanDirectoryArgs) -> DirectoryInventory:
        directory = checked_directory(args.directory).resolve(strict=True)
        if not directory.is_dir():
            raise NotADirectoryError(str(directory))
        return DirectoryInventory(directory=str(directory), files=[
            FileInspection.model_validate(inspect_file(directory / name)) for name in VASP_FILES
        ])

    @registry.register("diagnose_outcar",
                       "Observe OUTCAR tail markers and the last recognized iteration, with byte evidence. "
                       "Returns electronic_step_diagnosis: an explicit last-loop EDIFF-not-reached report "
                       "can produce a scoped warning, impact and manual checks, not a global convergence verdict. "
                       "Also reads a bounded prefix for electronic_settings (EDIFF/NELM/ICHARG/ALGO/IALGO), "
                       "preserving values, missing/ambiguous states and byte evidence. Prefix-to-loop association is unverified. "
                       "Does not extract prefix IBRION/NSW settings; use scan_directory.output_context for those. "
                       "Already included in scan_directory.diagnostics; no overall convergence verdict.",
                       ScanDirectoryArgs, OutputDiagnosis)
    def output(args: ScanDirectoryArgs) -> OutputDiagnosis:
        return diagnose_outcar(checked_directory(args.directory) / "OUTCAR")

    @registry.register("inspect_incar",
                       "Read explicit INCAR IBRION and NSW with evidence (input intent only). "
                       "Already included in scan_directory.input_context. Missing INCAR says nothing about "
                       "OUTCAR settings; scan_directory can inspect those separately.",
                       ScanDirectoryArgs, InputContext)
    def input_context(args: ScanDirectoryArgs) -> InputContext:
        return inspect_incar(checked_directory(args.directory) / "INCAR")

    @registry.register("inspect_oszicar",
                       "Read OSZICAR tail electronic rows and F/E0/d E summaries with byte evidence. "
                       "Already included in scan_directory.oszicar; use this for OSZICAR-specific details "
                       "not already available. No convergence verdict.",
                       ScanDirectoryArgs, OszicarObservation)
    def energy_log(args: ScanDirectoryArgs) -> OszicarObservation:
        return inspect_oszicar(checked_directory(args.directory) / "OSZICAR")

    @registry.register("compare_outputs",
                       "Read OUTCAR and OSZICAR and compare last sampled step numbers with evidence and reasons. "
                       "Returns checks and run_identity, not full log observations or IBRION/NSW settings. "
                       "Use this for a focused alignment question; if full log observations or mode settings "
                       "are also needed, prefer scan_directory, which includes output_comparison. "
                       "Matching does not verify run identity or convergence.",
                       ScanDirectoryArgs, OutputStepComparison)
    def compare(args: ScanDirectoryArgs) -> OutputStepComparison:
        return inspect_output_comparison(checked_directory(args.directory))

    register_knowledge_tool(registry)
    return registry
