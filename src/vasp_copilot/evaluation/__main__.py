"""Separate offline evaluation entry point; never loads model configuration."""

import argparse
import json
import logging
import sys
from pathlib import Path

from .cases import FixtureError
from .runner import evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate fixed Mock Agent scenarios offline")
    parser.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/pymatgen"),
                        help="Directory containing the two pinned OUTCAR.gz fixtures and static_silicon.OSZICAR")
    parser.add_argument("--output", type=Path, help="Optionally create a new JSON result file; never overwrites")
    args = parser.parse_args(argv)
    if args.output is not None and args.output.suffix.lower() != ".json":
        parser.error("--output must end in .json")
    try:
        report = evaluate(args.fixtures)
    except FixtureError as exc:
        print(json.dumps({"error": {"kind": "fixture_error", "message": str(exc)}}, ensure_ascii=True), file=sys.stderr)
        return 2
    except OSError as exc:
        print(json.dumps({"error": {"kind": "evaluation_error", "message": type(exc).__name__}}), file=sys.stderr)
        return 2
    content = report.model_dump_json(indent=2)
    if args.output is not None:
        target = args.output.expanduser().resolve()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = target.open("x", encoding="utf-8", newline="\n")
            try:
                with handle:
                    handle.write(content + "\n")
            except BaseException:
                try:
                    target.unlink()
                except OSError:
                    pass
                raise
        except OSError as exc:
            print(json.dumps({"error": {"kind": "evaluation_output_error", "message": type(exc).__name__}}), file=sys.stderr)
            return 2
    # ASCII JSON also works when stdout is a legacy Windows PowerShell pipe.
    print(json.dumps(report.model_dump(), ensure_ascii=True, indent=2))
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    # Expected error scenarios are described in JSON, not emitted as alarming logs.
    logging.basicConfig(level=logging.CRITICAL)
    raise SystemExit(main())
