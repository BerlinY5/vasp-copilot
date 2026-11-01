# OUTCAR output and inspection scope
Source: https://vasp.at/wiki/index.php/OUTCAR
Keywords: OUTCAR, output file, termination, timing
Reviewed: 2026-10-23

Official-source summary: OUTCAR is VASP's detailed text output. It can contain input parameter summaries, electronic step information, stress, and atomic forces. Settings such as NWRITE affect the amount of output detail.

Project policy: A file's existence or readability establishes only that the file was obtained. Timing markers in the tail are log observations; by themselves they do not prove successful completion of the whole calculation or replace electronic and ionic convergence checks. Information gaps outside the sampled windows or caused by truncated or concatenated logs still require verification. Public output examples can be inspected without complete input files, but they do not establish that the calculation can be rerun.
