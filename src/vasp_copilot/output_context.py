"""Observe bounded OUTCAR assignments and compare explicit input values."""

import re
from pathlib import Path

from .schemas import (
    ContextComparison, ErrorInfo, Evidence, InputContext, OutputContext,
    OutputParameter, ParameterComparison,
)

HEAD_BYTES = 128 * 1024
PARAMETER_LINE = re.compile(rb"^[ \t]*(IBRION|NSW)\b(.*)$")
INTEGER_VALUE = re.compile(rb"[ \t]*=[ \t]*([+-]?[0-9]{1,9})(?:[ \t]+[^\r\n]*)?[ \t]*$")


def inspect_outcar_parameters(path: Path) -> OutputContext:
    """Accept standalone assignment lines; retain evidence, not inferred defaults."""
    result = OutputContext()
    try:
        with path.open("rb") as stream:
            data = stream.read(HEAD_BYTES + 1)
    except OSError as exc:
        result.error = ErrorInfo(kind=type(exc).__name__, message=str(exc))
        return result
    result.bytes_read = len(data)
    result.window_limited = len(data) > HEAD_BYTES
    data = data[:HEAD_BYTES]
    offset = 0
    seen: set[str] = set()
    for line in data.splitlines(keepends=True):
        # A truncated last line must never supply a parameter value.
        match = PARAMETER_LINE.fullmatch(line.rstrip(b"\r\n"))
        if match:
            name = match[1].decode("ascii")
            if not line.endswith(b"\n"):
                result.issues.append(f"Incomplete {name} line at byte {offset}.")
            else:
                if name in seen:
                    result.issues.append(f"Duplicate {name} in sampled prefix; no precedence assumed.")
                seen.add(name)
                value_match = INTEGER_VALUE.fullmatch(match[2])
                if (value_match is None or b"\x00" in line
                        or b";" in line or line.count(b"=") != 1):
                    result.issues.append(f"Unsupported {name} assignment at byte {offset}.")
                else:
                    try:
                        text = line.rstrip(b"\r\n").decode("utf-8")
                    except UnicodeError as exc:
                        result.error = ErrorInfo(kind=type(exc).__name__, message=str(exc))
                        return result
                    result.parameters.append(OutputParameter(
                        name=name, value=int(value_match[1]),
                        evidence=Evidence(byte_offset=offset, text=text),
                    ))
        offset += len(line)
    return result


def compare_contexts(incar: InputContext, outcar: OutputContext) -> ContextComparison:
    """Compare unambiguous observations; missing values are never invented."""
    comparisons = []
    for name in ("IBRION", "NSW"):
        inputs = [p for p in incar.parameters if p.name == name]
        outputs = [p for p in outcar.parameters if p.name == name]
        comparison = ParameterComparison(
            name=name,
            incar_value=inputs[0].value if len(inputs) == 1 else None,
            outcar_value=outputs[0].value if len(outputs) == 1 else None,
        )
        if (not incar.error and not incar.issues and not outcar.error and not outcar.issues
                and len(inputs) == len(outputs) == 1):
            comparison.status = "matched" if inputs[0].value == outputs[0].value else "mismatched"
        comparisons.append(comparison)
    return ContextComparison(parameters=comparisons)
