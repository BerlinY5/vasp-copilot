# NELM and electronic self-consistency troubleshooting
Source: https://vasp.at/wiki/index.php/NELM
Keywords: NELM, electronic iteration limit, SCF problems, EDIFF not reached, SCF failure
Reviewed: 2026-10-30

Official-source summary: NELM sets the maximum number of steps allowed in an electronic self-consistency loop. When self-consistency is difficult, the official documentation recommends reviewing settings such as the electronic optimization algorithm and charge mixing rather than only increasing the iteration count.

Project policy: A final step number equal to NELM does not establish that the iteration limit was exhausted or that convergence failed; a count does not identify the stopping reason. electronic_settings records EDIFF, NELM, ICHARG, ALGO, and IALGO from the OUTCAR prefix. missing means no observation was retained, and ambiguous means no single value can be selected; neither supplies a default. The association between the prefix and the final electronic loop remains unverified, so numerical comparisons and mode explanations are only conditional notes. When a run restart is detected, old settings are not applied to the tail loop. Local not-reached messages retain their meaning as program reports and are not invalidated by special settings. The project does not automatically change parameters or restart calculations.
