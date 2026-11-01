"""Command-line entry point with JSON output."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .inspection import scan_directory
from .agent.loop import AgentLoop
from .agent.progress import StderrProgressReporter
from .agent.mock import MockBackend
from .tools.file_inspection import create_registry
from .agent.deepseek import DeepSeekBackend
from .config import ConfigurationError, DeepSeekConfig
from .storage.repository import RunRepository, StoragePathError, StorageRecordError, StorageSchemaError
from .reports.generator import ReportPathError, export_markdown

STORAGE_ERRORS = (OSError, sqlite3.Error, StorageSchemaError, StorageRecordError, StoragePathError)


def query_history(args: argparse.Namespace) -> int:
    try:
        repository = RunRepository(args.db)
        if args.history:
            result = {"database": str(repository.path), "runs": [row.model_dump() for row in repository.list_runs(args.limit)]}
        else:
            record = repository.get(args.show_run if args.show_run is not None else args.export_run)
            if record is None:
                print(json.dumps({"error": {"kind": "run_not_found", "message": "No saved run with this ID"}}), file=sys.stderr)
                return 2
            result = record.model_dump()
    except STORAGE_ERRORS as exc:
        print(json.dumps({"error": {"kind": "storage_error", "message": type(exc).__name__}}), file=sys.stderr)
        return 2
    if args.export_run is not None:
        try:
            output = args.output if args.output is not None else Path("reports/generated") / f"run-{record.summary.id}.md"
            path = export_markdown(record, output)
        except (OSError, ReportPathError) as exc:
            print(json.dumps({"error": {"kind": "report_error", "message": type(exc).__name__}}), file=sys.stderr)
            return 2
        result = {"status": "exported", "run_id": record.summary.id, "path": str(path)}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only VASP file inspection")
    parser.add_argument("directory", type=Path, nargs="?", help="Calculation directory")
    parser.add_argument("--agent", action="store_true", help="Use the agent loop (Mock by default)")
    parser.add_argument("--progress", action="store_true",
                        help="Show agent stage progress on stderr; stdout remains a single JSON result")
    parser.add_argument("--backend", choices=["mock", "deepseek"], default="mock", help="Agent decision backend")
    parser.add_argument("--question", default="Please inspect this calculation directory", help="Question recorded in the agent state")
    parser.add_argument("--max-steps", type=int, default=6,
                        help="Maximum decisions including final answer; a batch counts once, at most 8 calls per decision (1-100)")
    parser.add_argument("--require-knowledge", action="store_true",
                        help="Require a successful local knowledge search before a DeepSeek final answer (zero hits allowed)")
    history = parser.add_mutually_exclusive_group()
    history.add_argument("--save-history", action="store_true", help="Save this agent run to a local SQLite database")
    history.add_argument("--history", action="store_true", help="List recent saved runs without calling any backend")
    history.add_argument("--show-run", type=int, metavar="ID", help="Read one saved run including tool evidence")
    history.add_argument("--export-run", type=int, metavar="ID", help="Export a saved run as Markdown without model calls")
    parser.add_argument("--output", type=Path, help="New report .md path (default: reports/generated/run-ID.md); never overwrites")
    parser.add_argument("--db", type=Path, help="History database path (default: data/local/diagnostics.sqlite3 under current directory)")
    parser.add_argument("--limit", type=int, help="Number of recent runs to list (1-100, default 10)")
    args = parser.parse_args(argv)
    history_query = args.history or args.show_run is not None or args.export_run is not None
    if args.progress and (not args.agent or history_query):
        parser.error("--progress requires --agent and cannot be used for history queries")
    if args.require_knowledge and (not args.agent or args.backend != "deepseek" or history_query):
        parser.error("--require-knowledge requires --agent --backend deepseek and cannot be used for history queries")
    if args.output is not None and args.export_run is None:
        parser.error("--output requires --export-run")
    if args.db is not None and not (history_query or args.save_history):
        parser.error("--db requires --save-history, --history, --show-run or --export-run")
    if args.limit is not None and (not args.history or not 1 <= args.limit <= 100):
        parser.error("--limit requires --history and a value in 1-100")
    args.db = args.db if args.db is not None else Path("data/local/diagnostics.sqlite3")
    args.limit = args.limit if args.limit is not None else 10
    if history_query:
        if args.directory is not None or args.agent or args.backend != "mock":
            parser.error("History queries cannot be combined with a directory or agent backend")
        if args.show_run is not None and args.show_run < 1:
            parser.error("--show-run requires a positive ID")
        if args.export_run is not None and args.export_run < 1:
            parser.error("--export-run requires a positive ID")
        return query_history(args)
    if args.directory is None:
        parser.error("A calculation directory is required")
    if args.save_history and not args.agent:
        parser.error("--save-history requires --agent")
    if args.backend != "mock" and not args.agent:
        parser.error("--backend deepseek requires --agent")
    if args.agent:
        if not 1 <= args.max_steps <= 100 or not args.question.strip():
            parser.error("Agent requires max-steps in 1-100 and a nonempty question")
        try:
            backend = DeepSeekBackend(DeepSeekConfig.from_env()) if args.backend == "deepseek" else MockBackend()
        except ConfigurationError as exc:
            print(json.dumps({"error": {"kind": "configuration_error", "message": str(exc)}}), file=sys.stderr)
            return 2
        required = ("search_knowledge",) if args.require_knowledge else ()
        progress = StderrProgressReporter(sys.stderr) if args.progress else None
        run = AgentLoop(backend, create_registry(allowed_directory=args.directory), args.max_steps,
                        required_tools=required, on_progress=progress).run(args.question, str(args.directory))
        payload = run.model_dump()
        if args.save_history:
            try:
                repository = RunRepository(args.db)
                saved = repository.save(run, args.backend)
                payload["history_record"] = {"status": "saved", "run_id": saved.id,
                                             "saved_at": saved.saved_at, "database": str(repository.path)}
            except STORAGE_ERRORS as exc:
                payload["history_record"] = {"status": "error", "error": {"kind": "storage_error", "message": type(exc).__name__}}
                print(json.dumps(payload, ensure_ascii=True, indent=2))
                return 2
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 0 if run.status == "completed" else 2
    try:
        report = scan_directory(args.directory)
    except (OSError, RuntimeError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0
