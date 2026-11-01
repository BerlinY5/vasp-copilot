"""Render saved evidence without re-running tools or promoting model claims."""

import html
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..rag.retriever import KnowledgeSearchResult
from ..schemas import InputContext, OszicarObservation, OutputDiagnosis, OutputStepComparison, ScanReport
from ..storage.repository import StoredRun
from ..tools.file_inspection import DirectoryInventory


class ReportPathError(RuntimeError):
    pass


def _cell(value: Any) -> str:
    text = "unknown" if value is None else str(value)
    text = html.escape(text, quote=False).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", text)
    return text.replace("\n", "<br>")


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _fenced(text: str, language: str = "text") -> str:
    # Untrusted text cannot close its fence and inject headings, links or raw HTML.
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def _json(value: Any) -> str:
    return _fenced(json.dumps(value, ensure_ascii=False, indent=2), "json")


def _evidence(item: dict[str, Any]) -> str:
    return f"File: {_cell(item['file'])}; zero-based byte offset: {item['byte_offset']}.\n\n{_fenced(item['text'])}"


def _inventory(data: dict[str, Any]) -> list[str]:
    return ["**File inventory**", _table(["File", "Inspection status", "Exists", "Readable", "Error"], [
        [item["name"], item["status"], item["exists"], item["readable"], item["error"] or "—"]
        for item in data["files"]
    ])]


def _diagnosis(data: dict[str, Any]) -> list[str]:
    parts = ["**OUTCAR sampling and status**", _table(["Field", "Value recorded by the tool"], [
        [key, data[key]] for key in ("read_start", "bytes_read", "snapshot_size", "normal_termination", "electronic_convergence", "ionic_convergence")
    ]), "A byte-read range does not mean all content was parsed; markers and iteration numbers do not establish overall convergence."]
    if data["error"]:
        parts.extend(["File parsing error:", _json(data["error"])])
    parts.append(_table(["Rule", "Observation status", "Evidence count"], [
        [finding["rule_id"], finding["status"], len(finding["evidence"])] for finding in data["findings"]
    ]))
    for finding in data["findings"]:
        parts.append(f"Rule explanation: {_cell(finding['rule_id'])}")
        parts.append(_fenced(finding["explanation"]))
        parts.extend(_evidence(item) for item in finding["evidence"])
        if finding["sources"]:
            parts.extend(["Rule references (not evidence for this calculation):", _fenced("\n".join(finding["sources"]))])
    iteration = data["last_iteration"]
    parts.extend(["**Last identifiable iteration**", _table(["Ionic step number", "Electronic step number", "Message status"], [
        [iteration["ionic_step"], iteration["electronic_step"], iteration["status"]]
    ])])
    if iteration["header"]:
        parts.append(_evidence(iteration["header"]))
    parts.extend(_evidence(item) for item in iteration["markers"])
    if iteration["issues"]:
        parts.extend(["Uncertainties recorded by the tool:", _json(iteration["issues"])])
    parts.extend(["Iteration observation scope:", _fenced(iteration["explanation"])])
    if iteration["sources"]:
        parts.extend(["Iteration parsing references:", _fenced("\n".join(iteration["sources"]))])
    settings = data["electronic_settings"]
    if settings is None:
        parts.append("Electronic self-consistency settings were not generated or saved in this record; they are not filled in from current files.")
    else:
        parts.extend(["**OUTCAR prefix electronic self-consistency settings**", _table(["Prefix bytes read", "File snapshot size", "Window limited", "Loop association"], [[
            settings["bytes_read"], settings["snapshot_size"], settings["window_limited"], settings["iteration_association"],
        ]]), _table(["Parameter", "Sampling status", "Value", "Occurrences"], [
            [p["name"], p["status"], p["value"], p["occurrences"]] for p in settings["parameters"]
        ]), _fenced(settings["explanation"])])
        for parameter in settings["parameters"]:
            parts.append(f"Parameter {_cell(parameter['name'])}:")
            parts.extend(_evidence(e) for e in parameter["evidence"])
            if parameter["issues"]:
                parts.append(_json(parameter["issues"]))
        if settings["issues"]:
            parts.extend(["Settings context issues:", _json(settings["issues"])])
    local = data["electronic_step_diagnosis"]
    if local is None:
        parts.append("A local electronic-loop diagnosis was not generated or saved in this record; current rules are not applied retroactively.")
    else:
        parts.extend(["**Local diagnosis of the last sampled electronic loop**", _table(["Rule", "Local status", "Severity", "Scope"], [[
            local["rule_id"], local["status"], local["severity"], local["scope"],
        ]]), _fenced(local["summary"])])
        if local["impact"]:
            parts.extend(["Impact and risks:", _fenced(local["impact"])])
        parts.extend(_evidence(item) for item in local["evidence"])
        if local["recommendations"]:
            parts.extend(["Suggested manual checks (no automatic parameter changes):", _fenced("\n".join(local["recommendations"]))])
        if local["settings_considerations"]:
            parts.append("Conditional notes on prefix settings (their association with this loop is unverified):")
            for consideration in local["settings_considerations"]:
                parts.append(_fenced(consideration["summary"]))
                parts.extend(_evidence(e) for e in consideration["evidence"])
        parts.extend(["Limitations:", _fenced("\n".join(local["limitations"])),
                      "Rule sources (do not replace file evidence for this calculation):", _fenced("\n".join(local["sources"]))])
    return parts


def _input_context(data: dict[str, Any]) -> list[str]:
    parts = [f"**INCAR input intent: {_cell(data['calculation_type'])}**", _table(["Parameter", "Value", "One-based line number", "Original line"], [
        [item["name"], item["value"], item["line_number"], item["text"]] for item in data["parameters"]
    ])]
    if data["issues"] or data["error"]:
        parts.extend(["Input parsing issues:", _json({"issues": data["issues"], "error": data["error"]})])
    parts.extend([_fenced(data["explanation"]), "Input parameter references:", _fenced("\n".join(data["sources"]))])
    return parts


def _oszicar(data: dict[str, Any]) -> list[str]:
    parts = ["**OSZICAR electronic iterations and energy summaries**", _table(["Field", "Value recorded by the tool"], [
        [key, data[key]] for key in ("status", "read_start", "bytes_read", "snapshot_size",
                                    "electronic_convergence", "ionic_convergence", "normal_termination")
    ]), "observed means only that supported log rows were identified. Electronic-row dE and summary d E are shown separately; their magnitudes do not establish convergence."]
    electronic, summary = data["last_electronic_step"], data["last_energy_summary"]
    if electronic:
        parts.extend(["Last retained electronic iteration row:", _table(
            ["Algorithm", "Electronic step number", "E (eV)", "dE (eV)", "d eps (eV)", "ncg", "rms", "rms(c)"],
            [[electronic[key] for key in ("algorithm", "iteration", "energy_ev", "delta_energy_ev",
                                          "delta_band_energy_ev", "ncg", "rms", "rms_charge")]]),
            _evidence(electronic["evidence"])])
    if summary:
        parts.extend(["Last retained energy summary row:", _table(
            ["Ionic step number", "F (eV)", "E0 (eV)", "Summary d E (eV)"],
            [[summary[key] for key in ("ionic_step", "free_energy_ev", "energy_sigma0_ev", "reported_delta_energy_ev")]]),
            _evidence(summary["evidence"])])
    if not electronic and not summary:
        parts.append("This record retains no interpretable complete electronic row or energy summary; this does not establish calculation failure.")
    if data["issues"] or data["error"]:
        parts.extend(["OSZICAR read or format issues:", _json({"issues": data["issues"], "error": data["error"]})])
    parts.extend([_fenced(data["explanation"]), "Format references (not evidence for this calculation):", _fenced("\n".join(data["sources"]))])
    return parts


def _output_comparison(data: dict[str, Any]) -> list[str]:
    parts = [f"**Sampled output step comparison: {_cell(data['status'])}**",
             f"Same-run identity: {_cell(data['run_identity'])}. Matching numbers do not establish convergence or a shared run; differing numbers do not establish failure or a specific cause.",
             _table(["Check", "OUTCAR number", "OSZICAR number", "Comparison status", "Explanation"], [
                 [item["name"], item["outcar_value"], item["oszicar_value"], item["status"], item["reason"]]
                 for item in data["checks"]
             ])]
    for item in data["checks"]:
        parts.append(f"{_cell(item['name'])} original evidence:")
        for key in ("outcar_evidence", "oszicar_evidence"):
            if item[key]:
                parts.append(_evidence(item[key]))
    parts.append(_fenced(data["explanation"]))
    return parts


def _observation(tool_name: str, data: dict[str, Any]) -> list[str]:
    models = {"inspect_directory": DirectoryInventory, "diagnose_outcar": OutputDiagnosis,
              "inspect_incar": InputContext, "inspect_oszicar": OszicarObservation,
              "compare_outputs": OutputStepComparison, "scan_directory": ScanReport,
              "search_knowledge": KnowledgeSearchResult}
    model = models.get(tool_name)
    if model is None:
        return ["This tool has no dedicated report view; its original observation is preserved:", _json(data)]
    try:
        data = model.model_validate(data).model_dump()
    except ValidationError:
        return ["This tool record does not match the data format of the current report view, so no summary is generated; the original observation follows:", _json(data)]
    if tool_name == "inspect_directory":
        return _inventory(data)
    if tool_name == "diagnose_outcar":
        return _diagnosis(data)
    if tool_name == "inspect_incar":
        return _input_context(data)
    if tool_name == "inspect_oszicar":
        return _oszicar(data)
    if tool_name == "compare_outputs":
        return _output_comparison(data)
    if tool_name == "scan_directory":
        parts = [f"**Calculation status recorded by the tool: {_cell(data['calculation_status'])}**"]
        parts.extend(_inventory(data))
        parts.extend(_input_context(data["input_context"]))
        output = data["output_context"]
        parts.extend(["**OUTCAR prefix parameter observations**", _table(["Parameter", "Sampled value", "Byte offset", "Original line"], [
            [item["name"], item["value"], item["evidence"]["byte_offset"], item["evidence"]["text"]]
            for item in output["parameters"]
        ]), "Parameter read scope and issues:", _json({key: output[key] for key in ("read_start", "bytes_read", "window_limited", "issues", "error")}),
            "**Comparison of sampled input and output values**", _json(data["context_comparison"])])
        parts.extend(_diagnosis(data["diagnostics"]))
        if data["oszicar"] is not None:
            parts.extend(_oszicar(data["oszicar"]))
        else:
            parts.append("This historical scan record did not save OSZICAR parsing; this does not establish that the file was missing at the time.")
        if data["output_comparison"] is not None:
            parts.extend(_output_comparison(data["output_comparison"]))
        else:
            parts.append("This historical scan record did not save the output step comparison; current files or rules are not used to reconstruct a verdict.")
        return parts
    parts = ["**Knowledge-base references (not calculation file evidence)**", _fenced(data["notice"])]
    if not data["hits"]:
        parts.append("This search returned no reference entries; this does not indicate a calculation anomaly.")
    for hit in data["hits"]:
        parts.extend([
            f"Entry: {_cell(hit['title'])}; local document: {_cell(hit['document'])}; one-based lines: {hit['line_start']}–{hit['line_end']}.",
            f"Reference review date: {_cell(hit['reviewed_on'])}; type: reference.",
        ])
        if hit["sections"]:
            for section in hit["sections"]:
                label = {"official_summary": "Official documentation summary (project paraphrase)",
                         "project_policy": "Project policy", "unclassified": "Unclassified attribution"}[section["kind"]]
                parts.extend([f"**{label}**", "Local citation identifier:", _fenced(section["citation"])])
                if section["source_url"] is not None:
                    parts.extend(["Official source for this section:", _fenced(section["source_url"])])
                parts.append(_fenced(section["text"]))
        else:
            parts.extend(["This historical record has no section-level attribution; current knowledge-base content is not added. The original excerpt and source fields are preserved.",
                          "Reference source URL (does not imply support for all project limits):", _fenced(hit["source"]),
                          "Reference excerpt as saved:", _fenced(hit["excerpt"])])
    return parts


def render_markdown(record: StoredRun) -> str:
    """Pure formatting: uses only the saved record, with no filesystem or API reads."""
    summary, run = record.summary, record.run
    parts = ["# VASP-Copilot Diagnostic Report", _table(["Item", "Saved value"], [
        ["Record ID", summary.id], ["Saved at (UTC)", summary.saved_at], ["Backend", summary.backend],
        ["Agent run status", run.status], ["Decision steps", run.decision_steps], ["Tool calls", len(run.state.history)],
    ]), "completed means only that the agent generated an answer; it does not establish VASP success or convergence. The report uses the saved record and does not reflect subsequent changes to source files.",
        "## User question", _fenced(run.state.question), "## Directory selected at the time", _fenced(run.state.directory),
        "## Tool evidence and references"]
    if not run.state.history:
        parts.append("This run recorded no tool observations; no file evidence is available for tool-based verification.")
    for event in run.state.history:
        position = f" (same-turn call {event.batch_index}/{event.batch_size})" if event.batch_size > 1 else ""
        parts.extend([f"### Step {event.step}{position}: {_cell(event.call.tool_name)}",
                      f"Tool execution status: {_cell(event.observation.status)}. success means only that the tool produced a valid report.",
                      "Call arguments:", _json(event.call.arguments)])
        if event.observation.status == "error":
            parts.extend(["Tool error:", _json(event.observation.error.model_dump())])
        else:
            parts.extend(_observation(event.call.tool_name, event.observation.data))
    if run.state.required_tools:
        parts.extend(["## Required tools before completion", _json(run.state.required_tools),
                      "These tools must return successfully before a final answer is accepted. A search may return no hits; satisfying the requirement does not establish retrieval relevance or answer correctness."])
    if run.state.completion_feedback:
        parts.extend(["## Final-answer correction history",
                      "The following records indicate that required tool calls were missing at the time. Rejected answers were not saved as final answers. Corrections count toward decision steps.",
                      _json([item.model_dump() for item in run.state.completion_feedback])])
    parts.extend(["## Backend answer",
                  "The original backend answer is preserved verbatim and has not been automatically fact-checked.",
                  _fenced(run.answer) if run.answer is not None else "This run did not produce a final answer."])
    if run.error:
        parts.extend(["## Run error or termination reason", _json(run.error.model_dump())])
    parts.extend(["## Interpretation limits",
                  "This report adds no scientific verdict. It preserves the tools' unknown states, parsing errors, and scope limits; missing files or absent markers do not automatically establish failure. The backend answer is preserved verbatim and may contain inferences beyond the evidence; review it separately against the tool observations above.",
                  "## Complete saved snapshot", _json(record.model_dump())])
    return "\n\n".join(parts) + "\n"


def export_markdown(record: StoredRun, output: Path) -> Path:
    target = Path(output).expanduser().resolve()
    if target.suffix.lower() != ".md":
        raise ReportPathError("Report output must end in .md")
    content = render_markdown(record)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation refuses overwrites, including existing symlink targets.
    handle = target.open("x", encoding="utf-8", newline="\n")
    try:
        with handle:
            handle.write(content)
    except BaseException:
        # Remove only the new partial file created by this call, then preserve the failure.
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return target
