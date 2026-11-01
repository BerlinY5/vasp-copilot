"""Check recorded output observations against scenario bytes, without reparsing."""

from collections.abc import Callable
from typing import Any

Check = Callable[[str, Any, Any], None]
VERDICTS = ("electronic_convergence", "ionic_convergence", "normal_termination")


def _evidence_valid(item: dict, filename: str, files: dict[str, bytes]) -> bool:
    raw, offset = files.get(filename, b""), item["byte_offset"]
    if (item["file"] != filename or type(offset) is not int or not 0 <= offset < len(raw)
            or (offset > 0 and raw[offset - 1:offset] != b"\n")):
        return False
    line, separator, _ = raw[offset:].partition(b"\n")
    try:
        return bool(separator) and line.decode("utf-8").rstrip("\r") == item["text"]
    except UnicodeError:
        return False


def observe_oszicar(data: dict, files: dict[str, bytes], check: Check) -> dict[str, Any]:
    electronic, summary = data["last_electronic_step"], data["last_energy_summary"]
    check("oszicar.overall_verdicts", ["unknown"] * 3, [data[key] for key in VERDICTS])
    check("oszicar.sources", ["https://vasp.at/wiki/index.php/OSZICAR"], data["sources"])
    raw = files["OSZICAR"]
    check("oszicar.sample_coverage", [max(0, len(raw) - 65536), min(len(raw), 65536), len(raw)],
          [data["read_start"], data["bytes_read"], data["snapshot_size"]])
    for name, row in [("electronic", electronic), ("summary", summary)]:
        if row is not None:
            check(f"oszicar.{name}.evidence", True, _evidence_valid(row["evidence"], "OSZICAR", files))
    return {
        "oszicar_status": data["status"],
        "oszicar_error": data["error"]["kind"] if data["error"] else None,
        "oszicar_has_issues": bool(data["issues"]),
        "oszicar_electronic": ([electronic[key] for key in (
            "algorithm", "iteration", "energy_ev", "delta_energy_ev", "delta_band_energy_ev",
            "ncg", "rms", "rms_charge")] + [electronic["evidence"]["byte_offset"]]) if electronic else None,
        "oszicar_summary": ([summary[key] for key in (
            "ionic_step", "free_energy_ev", "energy_sigma0_ev", "reported_delta_energy_ev")]
            + [summary["evidence"]["byte_offset"]]) if summary else None,
    }


def observe_comparison(data: dict, files: dict[str, bytes], check: Check) -> dict[str, Any]:
    check("comparison.run_identity", "unknown", data["run_identity"])
    rows = []
    for item in data["checks"]:
        name = item["name"]
        check(f"comparison.{name}.reason_present", True, bool(item["reason"].strip()))
        offsets = []
        for field, filename in [("outcar", "OUTCAR"), ("oszicar", "OSZICAR")]:
            evidence = item[f"{field}_evidence"]
            offsets.append(evidence["byte_offset"] if evidence else None)
            if evidence is not None:
                check(f"comparison.{name}.{field}_evidence", True, _evidence_valid(evidence, filename, files))
        rows.append([name, item["status"], item["outcar_value"], item["oszicar_value"], *offsets])
    return {"comparison_status": data["status"], "comparison_checks": rows}
