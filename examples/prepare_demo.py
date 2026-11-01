"""Prepare the pinned public example locally, without network or overwrites."""

import gzip
import hashlib
import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    fixtures = root / "tests" / "fixtures" / "pymatgen"
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
    outcar = manifest["samples"]["static_silicon"]
    oszicar = manifest["oszicar_samples"]["static_silicon"]
    contents = {
        "OUTCAR": gzip.decompress((fixtures / outcar["path"]).read_bytes()),
        "OSZICAR": (fixtures / oszicar["path"]).read_bytes(),
    }
    for name, metadata, size_key in (
        ("OUTCAR", outcar, "uncompressed_bytes"),
        ("OSZICAR", oszicar, "bytes"),
    ):
        content = contents[name]
        if (len(content) != metadata[size_key]
                or hashlib.sha256(content).hexdigest() != metadata["sha256"]):
            raise ValueError(f"Bundled {name} differs from its provenance manifest")

    destination = root / "data" / "local" / "demo" / "static_silicon"
    if not destination.resolve().is_relative_to(root):
        raise ValueError("Demo directory resolves outside the repository")
    for name, content in contents.items():
        target = destination / name
        if target.is_symlink():
            raise FileExistsError(f"Refusing a symbolic-link target: {target}")
        if target.exists() and target.read_bytes() != content:
            raise FileExistsError(f"Refusing to overwrite different data: {target}")
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in contents.items():
        target = destination / name
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(content)
    print(destination)
    print("Source: pinned pymatgen fixtures; see tests/fixtures/pymatgen/README.md")
    print("Only OUTCAR and OSZICAR are prepared; input files are not fabricated.")


if __name__ == "__main__":
    main()
