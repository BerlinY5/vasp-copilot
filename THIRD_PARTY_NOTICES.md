# Third-party material and samples

## pymatgen test samples

The two compressed OUTCAR files and one OSZICAR in `tests/fixtures/pymatgen/` come from
[materialsproject/pymatgen](https://github.com/materialsproject/pymatgen), pinned to commit
`682bfd855dd89264b0ff8d6bee4815f8834cc5ac`.

- Upstream MIT license and copyright notice: [LICENSE.pymatgen](tests/fixtures/pymatgen/LICENSE.pymatgen).
- Exact sources, sizes, and SHA-256 hashes: [manifest.json](tests/fixtures/pymatgen/manifest.json).
- Acquisition and transformation details: [Sample notes](tests/fixtures/pymatgen/README.md).

`examples/prepare_demo.py` only decompresses, verifies, and copies these samples; it does not download other data.
Distinguish the original samples from cases deliberately truncated, replaced, or concatenated in tests.
This repository does not distribute the VASP program or POTCAR files.

## Knowledge notes

Notes in `src/vasp_copilot/rag/knowledge/` retain their own reference sources and review dates.
“Official-source summary” is the project's paraphrase; “Project policy” describes project rules and must not be attributed to external sources.

## Project source-code license

No overall license has yet been specified for the project source code. The upstream MIT license above applies only to the corresponding third-party resources;
it does not automatically license the entire VASP-Copilot project.