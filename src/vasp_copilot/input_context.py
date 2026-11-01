"""Parse a deliberately small INCAR subset, preserving explicit evidence."""

import re
from pathlib import Path

from .schemas import ErrorInfo, InputContext, InputParameter

MAX_INCAR_BYTES = 64 * 1024
SUPPORTED_IBRION = {-1, 0, 1, 2, 3}


def inspect_incar(path: Path) -> InputContext:
    """Read up to limit+1 bytes; ambiguous inputs remain unknown."""
    result = InputContext()
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_INCAR_BYTES + 1)
        if len(data) > MAX_INCAR_BYTES:
            result.issues.append("INCAR exceeds 64 KiB; no partial classification attempted.")
            return result
        text = data.decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        result.error = ErrorInfo(kind=type(exc).__name__, message=str(exc))
        return result

    seen: set[str] = set()
    for line_number, original in enumerate(text.splitlines(), start=1):
        content = re.split(r"[!#]", original, maxsplit=1)[0]
        # Quoted strings and continuation lines need a fuller parser.
        if any(char in content for char in ('"', "'", "\\", "\x00")):
            result.issues.append(f"Line {line_number}: unsupported quoting, continuation or NUL.")
            continue
        for statement in content.split(";"):
            statement = statement.strip()
            if not statement:
                continue
            match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*)", statement)
            if match is None:
                result.issues.append(f"Line {line_number}: unsupported statement.")
                continue
            name, raw_value = match.groups()
            name = name.upper()
            if name not in {"IBRION", "NSW"}:
                continue
            if name in seen:
                result.issues.append(f"Line {line_number}: duplicate {name}; no precedence assumed.")
            seen.add(name)
            if not re.fullmatch(r"[+-]?[0-9]{1,9}", raw_value.strip()):
                result.issues.append(f"Line {line_number}: {name} must be a supported integer literal.")
                continue
            value = int(raw_value)
            result.parameters.append(InputParameter(
                name=name, value=value, line_number=line_number, text=original,
            ))

    values = {parameter.name: parameter.value for parameter in result.parameters}
    for name in ("IBRION", "NSW"):
        if name not in values:
            result.issues.append(f"Explicit {name} required; default values are not inferred.")
    if "NSW" in values and values["NSW"] < 0:
        result.issues.append("NSW must be non-negative.")
    if "IBRION" in values and values["IBRION"] not in SUPPORTED_IBRION:
        result.issues.append("This parser does not classify this IBRION mode.")
    if values.get("IBRION") == 0 and values.get("NSW") == 0:
        result.issues.append("MD requested with zero timesteps; no static classification inferred.")
    if result.issues:
        return result
    if values["NSW"] == 0 or values["IBRION"] == -1:
        result.calculation_type = "static"
    elif values["IBRION"] == 0:
        result.calculation_type = "molecular_dynamics"
    else:
        result.calculation_type = "relaxation"
    return result
