"""Observe common OSZICAR rows with bounded reads and original byte evidence."""

import math
import os
import re
from pathlib import Path

from .schemas import (ErrorInfo, OszicarElectronicStep, OszicarEnergySummary,
                      OszicarEvidence, OszicarObservation)

TAIL_BYTES = 64 * 1024
NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[EeDd][+-]?[0-9]+)?"
HEADER = re.compile(r"N\s+E\s+dE\s+d\s+eps\s+ncg\s+rms(?:\s+rms\(c\))?")
ELECTRONIC = re.compile(
    rf"(?P<algorithm>DAV|RMM|CG)\s*:\s*(?P<iteration>[0-9]{{1,9}})\s+"
    rf"(?P<energy>{NUMBER})\s+(?P<delta>{NUMBER})\s+(?P<band>{NUMBER})\s+"
    rf"(?P<ncg>[0-9]{{1,9}})\s+(?P<rms>{NUMBER})(?:\s+(?P<charge>{NUMBER}))?"
)
SUMMARY = re.compile(
    rf"(?P<step>[0-9]{{1,9}})\s+F=\s*(?P<free>{NUMBER})\s+E0=\s*(?P<zero>{NUMBER})"
    rf"\s+d\s*E\s*=\s*(?P<delta>{NUMBER})"
    rf"(?:\s+mag=\s*(?P<mag>{NUMBER}(?:\s+{NUMBER}\s+{NUMBER})?))?"
)


def _number(token: str) -> float:
    if len(token) > 64:
        raise ValueError("Numeric token exceeds supported length")
    normalized = token.replace("D", "E").replace("d", "e")
    value = float(normalized)
    nonzero_mantissa = any(char in "123456789" for char in normalized.upper().split("E")[0])
    if not math.isfinite(value) or (value == 0 and nonzero_mantissa):
        raise ValueError("Numeric overflow or underflow")
    return value


def inspect_oszicar(path: Path) -> OszicarObservation:
    result = OszicarObservation()
    try:
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            start = max(0, size - TAIL_BYTES)
            stream.seek(start)
            raw = stream.read(size - start)
        result.read_start, result.bytes_read, result.snapshot_size = start, len(raw), size
        if len(raw) != size - start:
            raise OSError("OSZICAR changed size during read; retry when stable")
    except OSError as exc:
        result.error = ErrorInfo(kind=type(exc).__name__, message=str(exc))
        return result

    def clear(reason: str | None = None) -> None:
        result.last_electronic_step = None
        result.last_energy_summary = None
        if reason and reason not in result.issues:
            result.issues.append(reason)

    offset = start
    for index, line in enumerate(raw.splitlines(keepends=True)):
        position, offset = offset, offset + len(line)
        if start > 0 and index == 0:
            clear("Tail window is limited; first sampled line omitted.")
            continue
        if not line.endswith(b"\n"):
            clear("Incomplete final line; earlier candidates cleared.")
            continue
        try:
            original = line.decode("utf-8").rstrip("\r\n")
        except UnicodeError:
            clear("Invalid UTF-8 record; earlier candidates cleared.")
            continue
        text = original.lstrip("\ufeff") if position == 0 else original
        text = text.strip()
        if not text:
            continue
        if HEADER.fullmatch(text):
            clear()
            continue
        evidence = OszicarEvidence(byte_offset=position, text=original)
        electronic, summary = ELECTRONIC.fullmatch(text), SUMMARY.fullmatch(text)
        try:
            if electronic:
                values = electronic.groupdict()
                # A new cycle can start without a repeated column header.
                if result.last_energy_summary is not None:
                    clear()
                result.last_electronic_step = OszicarElectronicStep(
                    algorithm=values["algorithm"], iteration=int(values["iteration"]),
                    energy_ev=_number(values["energy"]), delta_energy_ev=_number(values["delta"]),
                    delta_band_energy_ev=_number(values["band"]), ncg=int(values["ncg"]),
                    rms=_number(values["rms"]),
                    rms_charge=_number(values["charge"]) if values["charge"] is not None else None,
                    evidence=evidence,
                )
            elif summary:
                values = summary.groupdict()
                # Validate an optional numeric mag suffix, but do not interpret it.
                for token in (values["mag"] or "").split():
                    _number(token)
                if result.last_energy_summary is not None:
                    result.last_electronic_step = None
                result.last_energy_summary = OszicarEnergySummary(
                    ionic_step=int(values["step"]), free_energy_ev=_number(values["free"]),
                    energy_sigma0_ev=_number(values["zero"]), reported_delta_energy_ev=_number(values["delta"]),
                    evidence=evidence,
                )
            else:
                clear("Unsupported or malformed record; earlier candidates cleared.")
        except ValueError:
            clear("Invalid numeric record; earlier candidates cleared.")
    if result.last_electronic_step is not None or result.last_energy_summary is not None:
        result.status = "observed"
    return result
