# INCAR settings and OUTCAR parameter comparison
Source: https://vasp.at/wiki/index.php/INCAR
Keywords: INCAR, IBRION, NSW, parameter checking, parameter mismatch, input-output, input settings, parameter comparison
Reviewed: 2026-10-28

Official-source summary: INCAR is VASP's main input file. Its tags select algorithms and set parameters. VASP writes its interpretation of INCAR data to OUTCAR, and the official documentation recommends checking whether this matches the intended settings.

Project policy: input_context describes only explicit IBRION/NSW values in the current INCAR and the input intent; output_context records only parameters sampled from the OUTCAR prefix. context_comparison checks the two parameters separately: mismatched means the observed values differ without establishing why, while matched does not prove that the files belong to the same run. Parameter comparison must remain distinct from step-number comparison in output_comparison. Even if one comparison differs and the other agrees, neither calculation failure, run identity, nor electronic or ionic convergence is established. Check file provenance, job records, and input backups first, and mark any possible explanation as unverified. The project does not modify files automatically.
