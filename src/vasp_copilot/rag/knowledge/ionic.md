# EDIFFG and ionic structural optimization
Source: https://vasp.at/wiki/index.php/EDIFFG
Keywords: EDIFFG, ionic convergence, structural optimization, force convergence, relaxation
Reviewed: 2026-10-23

Official-source summary: EDIFFG controls the stopping condition for ionic structural optimization. A positive value uses the total-energy change between consecutive ionic steps; a negative value requires the force magnitude on every atom to be smaller than the absolute value of EDIFFG. When set to zero, optimization stops after the number of steps specified by NSW. This parameter does not apply to molecular dynamics simulations.

Project policy: Reaching a step limit does not establish optimization convergence. The current tools do not fully parse EDIFFG and final forces or establish whether input files and output logs belong to the same run. This note therefore explains the parameter without adding a convergence determination. Fixed-ion calculations, electronic self-consistency, and structural optimization should be interpreted separately; preserve unknown when evidence is insufficient.
