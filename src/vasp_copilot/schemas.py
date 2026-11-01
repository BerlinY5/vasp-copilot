"""Validated data contracts; JSON dictionaries remain the public scan API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ErrorInfo(Schema):
    kind: str
    message: str


class FileInspection(Schema):
    name: str
    exists: bool | None
    readable: bool
    status: Literal["readable", "missing", "not_file", "error"]
    error: str | None = None


class Evidence(Schema):
    file: Literal["OUTCAR"] = "OUTCAR"
    byte_offset: int = Field(ge=0)
    text: str


class Finding(Schema):
    rule_id: str
    status: Literal["marker_found", "unknown"] = "unknown"
    explanation: str
    sources: list[str]
    evidence: list[Evidence] = Field(default_factory=list)


class IterationObservation(Schema):
    ionic_step: int | None = Field(default=None, ge=1)
    electronic_step: int | None = Field(default=None, ge=1)
    status: Literal["reached_marker", "not_reached_marker", "conflicting_markers", "unknown"] = "unknown"
    header: Evidence | None = None
    markers: list[Evidence] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    explanation: str = (
        "Messages after the last recognized iteration in the sampled tail only; "
        "not a convergence verdict. Run completeness and calculation mode are unverified."
    )
    sources: list[str] = Field(default_factory=lambda: [
        "https://kitchingroup.cheme.cmu.edu/blog/category/vasp/2/",
        "https://gitlab.com/ase/ase/-/issues/1429",
        "https://vasp.at/forum/viewtopic.php?p=18660",
    ])


class ElectronicSetting(Schema):
    name: Literal["EDIFF", "NELM", "ICHARG", "ALGO", "IALGO"]
    status: Literal["observed", "missing", "ambiguous"] = "missing"
    value: int | float | str | None = None
    occurrences: int = Field(default=0, ge=0)
    evidence: list[Evidence] = Field(default_factory=list, max_length=2)
    issues: list[str] = Field(default_factory=list)


class ElectronicSettings(Schema):
    read_start: Literal[0] = 0
    bytes_read: int = Field(default=0, ge=0)
    snapshot_size: int = Field(ge=0)
    window_limited: bool = False
    parameters: list[ElectronicSetting]
    issues: list[str] = Field(default_factory=list)
    iteration_association: Literal["unknown"] = "unknown"
    explanation: str = "Sampled OUTCAR prefix assignments, not verified final settings or a binding to the last electronic loop."


class ElectronicSettingConsideration(Schema):
    kind: Literal["ediff_zero", "fixed_charge", "postprocessing", "sampled_step_vs_nelm"]
    summary: str
    evidence: list[Evidence]
    relation: Literal["below", "equal", "above"] | None = None


class ElectronicStepDiagnosis(Schema):
    rule_id: Literal["scf.last_loop_not_reached"] = "scf.last_loop_not_reached"
    scope: Literal["last_sampled_electronic_loop"] = "last_sampled_electronic_loop"
    status: Literal["reported_not_reached", "not_triggered", "unknown"] = "unknown"
    severity: Literal["warning"] | None = None
    ionic_step: int | None = Field(default=None, ge=1)
    electronic_step: int | None = Field(default=None, ge=1)
    summary: str
    impact: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    settings_considerations: list[ElectronicSettingConsideration] = Field(default_factory=list)


class OutputDiagnosis(Schema):
    read_start: int | None = Field(default=None, ge=0)
    bytes_read: int = Field(default=0, ge=0)
    snapshot_size: int | None = Field(default=None, ge=0)
    error: ErrorInfo | None = None
    findings: list[Finding]
    last_iteration: IterationObservation = Field(default_factory=IterationObservation)
    # None in older snapshots or when no OUTCAR sample could be read.
    electronic_step_diagnosis: ElectronicStepDiagnosis | None = None
    electronic_settings: ElectronicSettings | None = None
    electronic_convergence: Literal["unknown"] = "unknown"
    ionic_convergence: Literal["unknown"] = "unknown"
    normal_termination: Literal["unknown"] = "unknown"


class InputParameter(Schema):
    name: Literal["IBRION", "NSW"]
    value: int
    line_number: int = Field(ge=1)
    text: str


class InputContext(Schema):
    file: Literal["INCAR"] = "INCAR"
    calculation_type: Literal["static", "relaxation", "molecular_dynamics", "unknown"] = "unknown"
    parameters: list[InputParameter] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None
    explanation: str = "Input-file intent only; not verified against OUTCAR from this run."
    sources: list[str] = Field(default_factory=lambda: [
        "https://vasp.at/wiki/index.php/INCAR",
        "https://vasp.at/wiki/index.php/IBRION",
        "https://vasp.at/wiki/index.php/NSW",
    ])


class OutputParameter(Schema):
    name: Literal["IBRION", "NSW"]
    value: int
    evidence: Evidence


class OutputContext(Schema):
    read_start: Literal[0] = 0
    bytes_read: int = Field(default=0, ge=0)
    window_limited: bool = False
    parameters: list[OutputParameter] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None


class ParameterComparison(Schema):
    name: Literal["IBRION", "NSW"]
    status: Literal["matched", "mismatched", "unknown"] = "unknown"
    incar_value: int | None = None
    outcar_value: int | None = None


class ContextComparison(Schema):
    parameters: list[ParameterComparison]
    explanation: str = (
        "Comparison of explicit INCAR values and observed OUTCAR prefix assignments only. "
        "Matching values do not establish run identity. Differences may reflect input edits, "
        "another run, or VASP parameter handling; no cause is established."
    )
    sources: list[str] = Field(default_factory=lambda: ["https://vasp.at/wiki/index.php/INCAR"])


class OszicarEvidence(Schema):
    file: Literal["OSZICAR"] = "OSZICAR"
    byte_offset: int = Field(ge=0)
    text: str


class OszicarElectronicStep(Schema):
    algorithm: Literal["DAV", "RMM", "CG"]
    iteration: int = Field(ge=1)
    energy_ev: float = Field(allow_inf_nan=False)
    delta_energy_ev: float = Field(allow_inf_nan=False)
    delta_band_energy_ev: float = Field(allow_inf_nan=False)
    ncg: int = Field(ge=0)
    rms: float = Field(ge=0, allow_inf_nan=False)
    rms_charge: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    evidence: OszicarEvidence


class OszicarEnergySummary(Schema):
    ionic_step: int = Field(ge=1)
    free_energy_ev: float = Field(allow_inf_nan=False)
    energy_sigma0_ev: float = Field(allow_inf_nan=False)
    reported_delta_energy_ev: float = Field(allow_inf_nan=False)
    evidence: OszicarEvidence


class OszicarObservation(Schema):
    status: Literal["observed", "unknown"] = "unknown"
    read_start: int | None = Field(default=None, ge=0)
    bytes_read: int = Field(default=0, ge=0)
    snapshot_size: int | None = Field(default=None, ge=0)
    last_electronic_step: OszicarElectronicStep | None = None
    last_energy_summary: OszicarEnergySummary | None = None
    issues: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None
    electronic_convergence: Literal["unknown"] = "unknown"
    ionic_convergence: Literal["unknown"] = "unknown"
    normal_termination: Literal["unknown"] = "unknown"
    explanation: str = (
        "Last supported rows in a bounded OSZICAR tail only. New electronic cycles and unsupported, "
        "invalid or incomplete records clear earlier candidates. Row numbers are not total counts. "
        "F, E0 and d E are reported values, not recomputed energies or convergence tests. "
        "Summary d E has mode-dependent meaning; do not equate it with electronic dE. "
        "Run identity and correspondence with OUTCAR are unverified."
    )
    sources: list[str] = Field(default_factory=lambda: ["https://vasp.at/wiki/index.php/OSZICAR"])


class OutputStepCheck(Schema):
    name: Literal["ionic_step", "electronic_step"]
    status: Literal["matched", "mismatched", "unknown"] = "unknown"
    outcar_value: int | None = Field(default=None, ge=1)
    oszicar_value: int | None = Field(default=None, ge=1)
    outcar_evidence: Evidence | None = None
    oszicar_evidence: OszicarEvidence | None = None
    reason: str


class OutputStepComparison(Schema):
    status: Literal["matched", "mismatched", "unknown"] = "unknown"
    checks: list[OutputStepCheck]
    run_identity: Literal["unknown"] = "unknown"
    explanation: str = (
        "Only compare last sampled row numbers. Electronic numbers are compared only when the "
        "observed ionic numbers match and the OSZICAR electronic row precedes its retained summary. "
        "Files are read separately, not as an atomic snapshot. Matching numbers do not establish "
        "run identity or convergence; different numbers do not establish failure or its cause. "
        "No energy, geometry, timestamp or full trajectory comparison is performed."
    )


class ScanReport(Schema):
    directory: str
    files: list[FileInspection]
    calculation_status: Literal["unknown"] = "unknown"
    diagnostics: OutputDiagnosis
    input_context: InputContext
    output_context: OutputContext
    context_comparison: ContextComparison
    # Older saved observations predate OSZICAR parsing; missing is not a fresh scan.
    oszicar: OszicarObservation | None = None
    output_comparison: OutputStepComparison | None = None
