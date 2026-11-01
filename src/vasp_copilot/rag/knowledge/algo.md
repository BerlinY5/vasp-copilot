# ALGO and IALGO output observations
Source: https://vasp.at/wiki/index.php/ALGO
Keywords: ALGO, IALGO, electronic algorithm, post-processing settings
Reviewed: 2026-10-30

Official-source summary: ALGO selects an electronic minimization algorithm or a many-body calculation method; None, Nothing, and Eigenval are post-processing options. IALGO is a lower-level algorithm setting that should be checked against the specific method and version.

Project policy: ALGO and IALGO observations record only the respective values found in the OUTCAR prefix. Observing IALGO=68 alone does not supply an ALGO name or establish an algorithm as the root cause of a problem. Explicit post-processing settings produce only conditional notes whose applicability must be checked; they neither establish a general SCF failure from a not-reached message nor invalidate that message. Whether the current input, sampled output, and final loop belong to the same run still requires verification.
