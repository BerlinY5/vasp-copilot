"""Associate explicit loop messages with the latest observed iteration header."""

import re

from .schemas import Evidence, IterationObservation

REACHED = b"aborting loop because EDIFF is reached"
NOT_REACHED = b"aborting loop EDIFF was not reached (unconverged)"
HEADER = re.compile(rb"Iteration[ \t]+([1-9][0-9]{0,8})[ \t]*\([ \t]*([1-9][0-9]{0,8})[ \t]*\)")
RUN_START = re.compile(rb"vasp\.[0-9]+\.")


def observe_last_iteration(data: bytes, start: int) -> IterationObservation:
    """Parse a bounded tail supplied by the caller; perform no file I/O."""
    result = IterationObservation()
    seen: dict[bytes, Evidence] = {}
    offset = start
    for index, line in enumerate(data.splitlines(keepends=True)):
        if start > 0 and index == 0:
            offset += len(line)
            continue
        if not line.endswith(b"\n"):
            result.status = "unknown"
            result.issues.append("Incomplete final line; latest context may be truncated.")
            break
        # VASP commonly decorates iteration headers and loop messages with dashes.
        text = line.strip().strip(b"- \t")
        match = HEADER.fullmatch(text)
        if RUN_START.match(text):
            result = IterationObservation()
            seen = {}
        elif match:
            result = IterationObservation(
                ionic_step=int(match[1]), electronic_step=int(match[2]),
                header=Evidence(byte_offset=offset, text=line.rstrip(b"\r\n").decode("ascii")),
            )
            seen = {}
        elif text.startswith(b"Iteration"):
            result = IterationObservation(issues=["Unrecognized iteration header; earlier context discarded."])
            seen = {}
        elif text in (REACHED, NOT_REACHED):
            if result.header is None:
                if not result.issues:
                    result.issues.append("Loop message without a preceding recognized header in this context.")
            else:
                seen[text] = Evidence(byte_offset=offset, text=line.rstrip(b"\r\n").decode("ascii"))
                result.markers = list(seen.values())
                if len(seen) == 2:
                    result.status = "conflicting_markers"
                else:
                    result.status = "reached_marker" if text == REACHED else "not_reached_marker"
        offset += len(line)
    return result
