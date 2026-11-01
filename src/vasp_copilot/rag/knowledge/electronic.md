# EDIFF and electronic self-consistency loops
Source: https://vasp.at/wiki/index.php/EDIFF
Keywords: EDIFF, electronic convergence, electronic self-consistency, self-consistency, SCF
Reviewed: 2026-10-30

Official-source summary: EDIFF controls the stopping condition for electronic self-consistency loops in eV. The energy-change stopping condition is met when both the total free-energy change and the band-energy change between consecutive electronic steps are below this threshold. When EDIFF is zero, the number of electronic steps specified by NELM is performed.

Project policy: The official definition provides a general explanation, not numerical verification of this run. The parser associates explicit messages only with the final sampled loop and does not recalculate total free-energy or band-energy changes. A not-reached message establishes only what the file reports; it does not establish that either energy change was above, or not below, EDIFF. Conditional explanations must not present unchecked numerical judgments as facts. A reached_marker likewise does not prove overall convergence; special modes, log provenance, and loop association still require verification. The project reports local log warnings without describing them as independently verified physical failures or inferring ionic relaxation convergence.
