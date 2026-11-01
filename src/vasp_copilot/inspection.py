"""Inspect known filenames without interpreting calculation results."""

from pathlib import Path
from typing import Any

from .diagnostics import diagnose_outcar
from .input_context import inspect_incar
from .oszicar import inspect_oszicar
from .output_comparison import compare_output_steps
from .output_context import compare_contexts, inspect_outcar_parameters
from .schemas import FileInspection, ScanReport

VASP_FILES = (
    "INCAR", "POSCAR", "KPOINTS", "POTCAR",
    "OUTCAR", "OSZICAR", "CONTCAR", "vasprun.xml",
)


def inspect_file(path: Path) -> dict[str, Any]:
    """Probe at most one byte. Readability describes this probe only."""
    result: dict[str, Any] = {
        "name": path.name, "exists": None, "readable": False,
        "status": "error", "error": None,
    }
    try:
        path.stat()
        result["exists"] = True
        if not path.is_file():
            result["status"] = "not_file"
            return FileInspection.model_validate(result).model_dump()
        with path.open("rb") as stream:
            stream.read(1)
        result.update(readable=True, status="readable")
    except FileNotFoundError:
        result.update(exists=False, status="missing")
    except OSError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return FileInspection.model_validate(result).model_dump()


def scan_directory(directory: Path) -> dict[str, Any]:
    """Return metadata for eight known files; never modify input files."""
    directory = directory.expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")
    input_context = inspect_incar(directory / "INCAR")
    output_context = inspect_outcar_parameters(directory / "OUTCAR")
    diagnostics = diagnose_outcar(directory / "OUTCAR")
    oszicar = inspect_oszicar(directory / "OSZICAR")
    return ScanReport(
        directory=str(directory),
        files=[FileInspection.model_validate(inspect_file(directory / name)) for name in VASP_FILES],
        diagnostics=diagnostics,
        input_context=input_context,
        output_context=output_context,
        context_comparison=compare_contexts(input_context, output_context),
        oszicar=oszicar,
        output_comparison=compare_output_steps(diagnostics, oszicar),
    ).model_dump()
