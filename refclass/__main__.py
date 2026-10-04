"""Read-only reporting and explicit snapshot imports for phase 1."""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import sqlite3
import sys

from .engine import build, render, report
from .quality import validate


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "update"):
        command = sub.add_parser(name, help="Import sourced local snapshot; no network calls")
        command.add_argument("--input", type=Path, default=root / "data" / "refclass-input.json")
        command.add_argument("--db", type=Path, default=Path(os.environ.get("REFCLASS_DB", root / "data" / "refclass.sqlite")))
    show = sub.add_parser("show")
    show.add_argument("name")
    show.add_argument("--json", action="store_true")
    show.add_argument("--db", type=Path, default=Path(os.environ.get("REFCLASS_DB", root / "data" / "refclass.sqlite")))
    quality = sub.add_parser("gates", help="Validate a structured quality evidence JSON file")
    quality.add_argument("evidence", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "gates":
            print(json.dumps(validate(json.loads(args.evidence.read_text())), indent=2))
            return 0
        if args.command in ("build", "update"):
            if not args.input.exists():
                if not args.db.exists():
                    result = build(args.db, {"as_of": date.today().isoformat(), "events": [], "prices": [], "sessions": [],
                                           "gaps": [f"Snapshot not found. {args.input}"]}, root / "knowledge")
                    print(render(result))
                raise ValueError(f"Source snapshot not found. {args.input}. Supply FDA, CRL, EDGAR and IBKR data; fixtures are not production data.")
            result = build(args.db, json.loads(args.input.read_text()), root / "knowledge", update=args.command == "update")
        else:
            if Path(args.name).name != args.name or not (root / "deals" / args.name).is_dir():
                raise ValueError("Deal folder does not exist")
            result = report(args.db, args.name, root / "knowledge")
        print(json.dumps(result, indent=2) if getattr(args, "json", False) else render(result), end="\n")
        return 1 if args.command in ("build", "update") and result["gaps"] else 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        print(f"Stopped. {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
