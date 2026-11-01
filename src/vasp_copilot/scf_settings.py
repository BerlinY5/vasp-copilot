"""Bounded OUTCAR SCF setting observations; no defaults or algorithm inference."""

import math
import re
from decimal import Decimal, InvalidOperation

from .schemas import ElectronicSetting, ElectronicSettings, Evidence

HEAD_BYTES = 128 * 1024
NAMES = ("EDIFF", "NELM", "ICHARG", "ALGO", "IALGO")
COMPANIONS = {"NELMIN", "NELMDL"}
TAG = re.compile(rb"^\s*([A-Z][A-Z0-9_]*)\b(.*)$")
INTEGER = re.compile(r"[+-]?[0-9]{1,9}")
REAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[EeDd][+-]?[0-9]{1,3})?")
RUN_START = re.compile(rb"vasp\.[0-9]+\.")


def run_start_offsets(data: bytes, start: int = 0) -> set[int]:
    offsets, offset = set(), start
    for index, line in enumerate(data.splitlines(keepends=True)):
        if (start == 0 or index > 0) and line.endswith(b"\n") and RUN_START.match(line.strip()):
            offsets.add(offset)
        offset += len(line)
    return offsets


def _value(name: str, raw: str) -> int | float | str:
    if name == "ALGO":
        value = raw.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}|Old[ \t]+(?:Fast|VeryFast)", value, re.IGNORECASE):
            raise ValueError("Unsupported ALGO literal")
        return value
    # Numeric assignments may be followed by OUTCAR's descriptive text.
    parts = raw.strip().split(maxsplit=1)
    token = parts[0] if parts else ""
    if len(parts) == 2 and not re.match(r"^[A-Za-z]", parts[1]):
        raise ValueError("Unsupported numeric suffix")
    if name != "EDIFF":
        if not INTEGER.fullmatch(token):
            raise ValueError("Unsupported integer literal")
        value = int(token)
        if (name == "NELM" and value < 1) or (name == "ICHARG" and value < 0):
            raise ValueError("Unsupported integer range")
        return value
    if len(token) > 64 or not REAL.fullmatch(token):
        raise ValueError("Unsupported EDIFF literal")
    try:
        decimal = Decimal(token.replace("D", "E").replace("d", "e"))
        value = float(decimal)
    except (InvalidOperation, OverflowError):
        raise ValueError("Unrepresentable EDIFF") from None
    if not math.isfinite(value) or decimal < 0 or (decimal != 0 and value == 0):
        raise ValueError("Unrepresentable EDIFF")
    return value


def observe_electronic_settings(prefix: bytes, size: int, *, later_run_offsets: set[int] | None = None) -> ElectronicSettings:
    """Parse complete prefix lines; duplicate/invalid assignments never choose precedence."""
    observations = {name: ElectronicSetting(name=name) for name in NAMES}
    result = ElectronicSettings(bytes_read=len(prefix), snapshot_size=size,
                                window_limited=size > HEAD_BYTES, parameters=list(observations.values()))
    sampled = prefix[:HEAD_BYTES]
    starts = run_start_offsets(sampled) | (later_run_offsets or set())
    if len(starts) > 1 or any(offset >= len(sampled) for offset in starts):
        result.issues.append("Multiple or later VASP run headers detected; do not apply prefix settings to the sampled loop.")
    offset = 0
    for line in sampled.splitlines(keepends=True):
        try:
            original = line.rstrip(b"\r\n").decode("utf-8")
            valid_encoding = True
        except UnicodeError:
            original = line.rstrip(b"\r\n").decode("utf-8", errors="replace")
            valid_encoding = False
        content = re.split(rb"[#!]", line.rstrip(b"\r\n"), maxsplit=1)[0]
        first = TAG.fullmatch(content.strip())
        if first is None or first[1].decode("ascii") not in set(NAMES) | COMPANIONS:
            offset += len(line)
            continue
        for segment in content.split(b";"):
            match = TAG.fullmatch(segment.strip())
            if match is None or match[1].decode("ascii") not in observations:
                continue
            name = match[1].decode("ascii")
            observation = observations[name]
            observation.occurrences += 1
            if len(observation.evidence) < 2:
                observation.evidence.append(Evidence(byte_offset=offset, text=original))
            try:
                if not valid_encoding or not line.endswith(b"\n") or b"\x00" in line or not match[2].lstrip().startswith(b"="):
                    raise ValueError("Incomplete or unsupported assignment")
                rhs = match[2].lstrip()[1:].decode("utf-8")
                if "=" in rhs:
                    raise ValueError("Multiple assignments without separators")
                value = _value(name, rhs)
                if observation.occurrences != 1:
                    raise ValueError("Duplicate assignment; no precedence assumed")
                observation.value, observation.status = value, "observed"
            except (ValueError, UnicodeError):
                observation.value, observation.status = None, "ambiguous"
                if not observation.issues:
                    observation.issues.append(f"Invalid, incomplete or duplicate {name} assignment in the sampled prefix.")
        offset += len(line)
    retained_offsets = [e.byte_offset for p in result.parameters for e in p.evidence]
    if retained_offsets and any(run > min(retained_offsets) for run in starts) and not result.issues:
        result.issues.append("A VASP run header follows sampled parameter evidence; do not bind those settings to the last loop.")
    return result
