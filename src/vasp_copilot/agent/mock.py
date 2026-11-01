"""Deterministic, observation-driven demonstration; not an LLM emulator."""

from typing import Any

from .protocol import AgentState, Finish, ToolCall


def summarize_outcar(data: dict[str, Any]) -> str:
    iteration = data["last_iteration"]
    summary = (
        f"File evidence: OUTCAR tail sample, last identifiable ionic step={iteration['ionic_step']}, "
        f"electronic step={iteration['electronic_step']}, message status={iteration['status']}."
    )
    for evidence in iteration["markers"]:
        summary += f" OUTCAR byte offset {evidence['byte_offset']}: {evidence['text']}."
    for finding in data["findings"]:
        for evidence in finding["evidence"]:
            summary += f" OUTCAR byte offset {evidence['byte_offset']}: {evidence['text']}."
    return summary + " These are log observations only; overall convergence remains unknown. See the tool history for complete evidence."


def summarize_comparison(data: dict[str, Any]) -> str:
    parts = [f"Sampled output step comparison: {data['status']}; same-run identity is unknown."]
    for check in data["checks"]:
        left = check["outcar_value"] if check["outcar_value"] is not None else "unknown"
        right = check["oszicar_value"] if check["oszicar_value"] is not None else "unknown"
        parts.append(f"{check['name']}: OUTCAR={left}, OSZICAR={right}; {check['status']}. {check['reason']}.")
        for evidence in (check["outcar_evidence"], check["oszicar_evidence"]):
            if evidence:
                parts.append(f"{evidence['file']} byte offset {evidence['byte_offset']}: {evidence['text']}")
    parts.append("Matching numbers do not establish a shared run or convergence; differing numbers do not establish failure or its cause.")
    return "\n".join(parts)


class MockBackend:
    def decide(self, state: AgentState, tools: list[dict[str, Any]]) -> ToolCall | Finish:
        if not state.history:
            return ToolCall(tool_name="inspect_directory", arguments={"directory": state.directory})
        last = state.history[-1].observation
        if last.tool_name == "search_knowledge":
            previous = state.history[-2].observation
            if previous.tool_name == "scan_directory":
                summary = summarize_outcar(previous.data["diagnostics"]) + "\n\n" + summarize_comparison(previous.data["output_comparison"])
            else:
                summary = summarize_outcar(previous.data)
            if last.status == "error":
                return Finish(answer=summary + f"\n\nReferences: Retrieval failed ({last.error.kind}); no general explanation was added.")
            if not last.data["hits"]:
                return Finish(answer=summary + "\n\nReferences: the local knowledge base has no matching entries; the observations above are unchanged.")
            references = []
            for hit in last.data["hits"]:
                references.append(
                    f"References (general explanation): {hit['title']}\n{hit['excerpt']}\n"
                    f"Source: {hit['source']}; local document {hit['document']}, lines {hit['line_start']}–{hit['line_end']}."
                )
            return Finish(answer=summary + "\n\n" + "\n\n".join(references))
        if last.status == "error":
            return Finish(answer=f"Tool {last.tool_name} did not complete: {last.error.kind} ({last.error.message}). Insufficient evidence to determine the calculation status.")
        data = last.data
        if last.tool_name == "inspect_directory":
            readable = {file["name"] for file in data["files"] if file["readable"]}
            if {"OUTCAR", "OSZICAR"}.issubset(readable):
                return ToolCall(tool_name="scan_directory", arguments={"directory": state.directory})
            if "OUTCAR" in readable:
                return ToolCall(tool_name="diagnose_outcar", arguments={"directory": state.directory})
            if "OSZICAR" in readable:
                return ToolCall(tool_name="inspect_oszicar", arguments={"directory": state.directory})
            if "INCAR" in readable:
                return ToolCall(tool_name="inspect_incar", arguments={"directory": state.directory})
            return Finish(answer="File inspection found no readable OUTCAR, OSZICAR, or INCAR. Insufficient evidence; calculation status is unknown.")
        if data.get("error"):
            return Finish(answer=f"File parsing reported an error: {data['error']['kind']}. Calculation status is unknown; see the tool history for details.")
        if last.tool_name in {"diagnose_outcar", "scan_directory"}:
            output = data["diagnostics"] if last.tool_name == "scan_directory" else data
            if last.tool_name == "scan_directory" and output.get("error"):
                return Finish(answer=f"OUTCAR read failed: {output['error']['kind']}. Overall status is unknown.\n" +
                              summarize_comparison(data["output_comparison"]))
            topics = []
            if output["last_iteration"]["status"] != "unknown":
                topics.append("EDIFF")
            if any(finding["rule_id"] == "outcar.ionic_stop_marker" and finding["status"] == "marker_found"
                   for finding in output["findings"]):
                topics.append("EDIFFG")
            return ToolCall(tool_name="search_knowledge", arguments={"query": " ".join(topics) or "OUTCAR", "top_k": 2})
        if last.tool_name == "inspect_incar":
            return Finish(answer=(f"No readable OUTCAR was obtained; the calculation type expressed by INCAR is {data['calculation_type']}. "
                                  "Input intent does not establish completion or convergence; calculation status is unknown. See the tool history for original parameter text and issues."))
        if last.tool_name == "inspect_oszicar":
            parts = [f"File evidence: OSZICAR tail parsing status is {data['status']}."]
            for key in ("last_electronic_step", "last_energy_summary"):
                if data[key] is not None:
                    evidence = data[key]["evidence"]
                    parts.append(f"OSZICAR byte offset {evidence['byte_offset']}: {evidence['text']}")
            parts.extend(data["issues"])
            parts.append("These are log-row observations only. Step numbers are not treated as total step counts, and energy summaries do not establish convergence; overall status remains unknown.")
            parts.append("Format references (not evidence for this calculation): " + ", ".join(data["sources"]))
            return Finish(answer="\n".join(parts))
        return Finish(answer="Mock does not support further interpretation of this tool result. Calculation status is unknown.")
