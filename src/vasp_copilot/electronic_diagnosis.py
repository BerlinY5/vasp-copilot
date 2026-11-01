"""Interpret an explicit last-loop report without reconstructing VASP convergence."""

from .iterations import NOT_REACHED, REACHED
from .schemas import ElectronicSettings, ElectronicSettingConsideration, ElectronicStepDiagnosis, IterationObservation


def _diagnose_message(iteration: IterationObservation) -> ElectronicStepDiagnosis:
    """Pure rule: usable header plus one explicit, unambiguous loop-stop report."""
    result = ElectronicStepDiagnosis(
        ionic_step=iteration.ionic_step, electronic_step=iteration.electronic_step,
        summary="The last sampled electronic loop has no reliable, unique stop message, so a local anomaly diagnosis cannot be generated.",
        limitations=[
            "This interprets only the program report for the last identifiable loop in the sampled window. Total free-energy and band-energy changes were not recalculated; a not-reached message does not establish that either quantity failed to fall below EDIFF. This does not diagnose every ionic step.",
            "Run identity, EDIFF/NELM, ICHARG, and algorithm settings have not been verified. Special modes and manually concatenated logs still require inspection.",
            "This local diagnosis leaves overall electronic convergence, ionic convergence, and normal termination as unknown.",
        ],
        sources=["https://gitlab.com/ase/ase/-/issues/1429",
                 "https://vasp.at/wiki/index.php/EDIFF", "https://vasp.at/wiki/index.php/NELM"],
    )
    if (iteration.header is None or iteration.issues or iteration.ionic_step is None
            or iteration.electronic_step is None or len(iteration.markers) != 1):
        return result
    marker = iteration.markers[0]
    if marker.byte_offset <= iteration.header.byte_offset:
        return result
    message = marker.text.strip().strip("- \t")
    if iteration.status == "not_reached_marker" and message == NOT_REACHED.decode("ascii"):
        result.status = "reported_not_reached"
        result.severity = "warning"
        result.summary = "The program explicitly reports that the last sampled electronic loop did not reach EDIFF; review the self-consistent results for this step."
        result.impact = "Review the energies, forces, and other results reported after this loop carefully. This rule cannot establish failure of the entire calculation or identify a root cause."
        result.recommendations = [
            "First verify the origin and completeness of OUTCAR and check the job records for this loop to avoid mixing inputs and outputs from different runs.",
            "Check EDIFF, NELM, ICHARG, and ALGO/IALGO from the same run. These settings have not been extracted here, so NELM exhaustion cannot be claimed.",
            "Review the electronic iteration trajectory and calculation mode. If self-consistency is difficult, consult the official documentation on algorithms and charge mixing; do not increase NELM solely because of this message.",
            "Fixed-step calculations with EDIFF=0, non-self-consistent calculations, and special response modes require separate interpretation. These are suggestions for manual review; no parameters are changed and no calculations are submitted automatically.",
        ]
    elif iteration.status == "reached_marker" and message == REACHED.decode("ascii"):
        result.status = "not_triggered"
        result.summary = "The last sampled loop reports reaching EDIFF, so this not-reached-message rule was not triggered. This is not an overall convergence verdict."
    else:
        return result
    result.evidence = [iteration.header.model_copy(deep=True), marker.model_copy(deep=True)]
    return result


def diagnose_electronic_step(iteration: IterationObservation, settings: ElectronicSettings | None = None) -> ElectronicStepDiagnosis:
    """Keep the message verdict; add qualified context from separately scoped settings."""
    result = _diagnose_message(iteration)
    if settings is None:
        return result
    result.limitations[1] = "The OUTCAR prefix settings have not been verified to belong to the same run as the last sampled loop. Special modes, unread content between windows, and concatenated logs still require review."
    if settings.issues:
        if result.status == "reported_not_reached":
            result.recommendations[1] = "The parameter sample has run-boundary issues, so the prefix settings cannot be applied to this loop. Obtain the complete output from the same run for review first."
        return result
    observed = {p.name: p for p in settings.parameters if p.status == "observed"}
    if result.status == "reported_not_reached":
        values = ", ".join(f"{p.name}={p.value}" for p in observed.values()) or "no reliable parameters"
        missing = ", ".join(p.name for p in settings.parameters if p.status != "observed")
        result.recommendations[1] = (f"The prefix contains {values}; verify that these settings belong to the same run as this loop. "
                                     + (f"No reliable {missing} was obtained; defaults are not filled in and ALGO is not inferred from IALGO." if missing else ""))
    def add(kind, summary, names, relation=None):
        result.settings_considerations.append(ElectronicSettingConsideration(
            kind=kind, summary=summary, relation=relation,
            evidence=[e.model_copy(deep=True) for name in names for e in observed[name].evidence],
        ))
    ediff, icharg, algo, nelm = (observed.get(name) for name in ("EDIFF", "ICHARG", "ALGO", "NELM"))
    if ediff and ediff.value == 0:
        add("ediff_zero", "The prefix contains EDIFF=0. If it belongs to this loop, interpret it in the context of a fixed number of electronic steps; step numbers do not establish non-convergence. The observed message remains unchanged.", ["EDIFF"])
    if icharg and icharg.value >= 10:
        add("fixed_charge", f"The prefix contains ICHARG={icharg.value}. If it belongs to this loop, first review the fixed-charge/non-self-consistent context and whether the settings apply; ordinary self-consistency conclusions do not apply directly.", ["ICHARG"])
        result.sources.append("https://vasp.at/wiki/index.php/ICHARG")
    if algo and algo.value.casefold() in {"none", "nothing", "eigenval"}:
        add("postprocessing", f"The prefix explicitly contains ALGO={algo.value}. If it belongs to this loop, review it in the postprocessing context; the not-reached message cannot directly establish an ordinary self-consistency failure.", ["ALGO"])
        result.sources.append("https://vasp.at/wiki/index.php/ALGO")
    if nelm and iteration.header is not None and iteration.electronic_step is not None and not iteration.issues:
        number, limit = iteration.electronic_step, nelm.value
        relation = "below" if number < limit else "equal" if number == limit else "above"
        symbol = {"below": "<", "equal": "=", "above": ">"}[relation]
        consideration = ElectronicSettingConsideration(
            kind="sampled_step_vs_nelm", relation=relation,
            summary=f"The last sampled electronic step number {number} {symbol} prefix NELM={limit} is only a numerical relation. Run association is unverified; this does not establish exhaustion of the limit or the reason for stopping.",
            evidence=[iteration.header.model_copy(deep=True), *[e.model_copy(deep=True) for e in nelm.evidence]],
        )
        result.settings_considerations.append(consideration)
    return result
