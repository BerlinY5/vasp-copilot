# Public OUTCAR regression samples

Source: materialsproject/pymatgen, tag v2025.6.14, pinned commit `682bfd855dd89264b0ff8d6bee4815f8834cc5ac`. Retrieved: 2026-10-23.

Original paths:

- `tests/files/io/vasp/fixtures/static_silicon/OUTCAR`
- `tests/files/io/vasp/fixtures/relaxation/OUTCAR`

See manifest.json for the exact download URLs, decompressed SHA-256 hashes, and sizes. The full repository MIT license is preserved in LICENSE.pymatgen, including the original authors' copyright notice; that license file applies only to these upstream resources and does not specify a license for the entire project.

Both OUTCAR files come directly from upstream public calculation test directories, and both file headers identify VASP 5.2.12. They were only gzip-compressed: decompressed bytes exactly match the original downloads, with no line selection, content changes, or artificial fragments added. The compressed total is 27531 bytes; the original total is 167498 bytes. No POTCAR files or local private calculation data are included.

test_real_outcar.py uses the Python standard library gzip module to decompress them into pytest temporary directories; pytest manages the temporary files after testing. Tests require neither network access nor an installed pymatgen package and do not modify the compressed samples.

Distinguish three test categories:

1. Complete public logs: verify parameters, the last iteration, termination markers, and evidence offsets.
2. Derived scenarios: explicitly truncate or concatenate public logs in memory to test context resets. These are not authentic upstream failure logs.
3. CLI integration: OUTCAR comes from upstream; INCAR is a minimal input constructed temporarily by the test and is not claimed to be the matching upstream INCAR.

Expected parameters, step numbers, and offsets were determined by directly inspecting the original lines, not generated automatically by the parser under test. Integrity tests verify decompressed size and SHA-256 to detect newline conversions or accidental sample changes.

When updating samples, review their sources, licenses, pinned commits, hashes, and manually determined expectations again; do not merely update snapshots to make failing tests pass.

## Additional OSZICAR sample (2026-10-24)

static_silicon.OSZICAR was copied unchanged from the previously downloaded public-examples/static_silicon/OSZICAR at the same pinned commit: 1314 bytes, without compression or newline conversion. The source path is tests/files/io/vasp/fixtures/static_silicon/OSZICAR; see the oszicar_samples entry in manifest.json for the exact URL, hash, and retrieval date. LICENSE.pymatgen in this directory also applies.

Manual inspection identified the last electronic line at zero-based byte offset 1156, with RMM number 13; the energy summary is at byte 1236, with number 1 and F=E0=-10.645278 eV. tests/test_oszicar.py verifies the original bytes, offsets, and fields. Other parser boundaries use explicitly constructed test records and are not presented as authentic upstream failure logs. A single sample does not represent all VASP versions and modes.