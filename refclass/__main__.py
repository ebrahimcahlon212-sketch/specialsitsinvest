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
from .locking import job_lock


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "update"):
        command = sub.add_parser(name, help="Import sourced local snapshot; no network calls")
        command.add_argument("--collection", type=Path, action="append", default=[],
                             help="Join staged collections to reviewed snapshot events by candidate_id")
        command.add_argument("--input", type=Path, default=root / "data" / "refclass-input.json")
        command.add_argument("--db", type=Path, default=Path(os.environ.get("REFCLASS_DB", root / "data" / "refclass.sqlite")))
    show = sub.add_parser("show")
    show.add_argument("name")
    show.add_argument("--json", action="store_true")
    show.add_argument("--db", type=Path, default=Path(os.environ.get("REFCLASS_DB", root / "data" / "refclass.sqlite")))
    quality = sub.add_parser("gates", help="Validate a structured quality evidence JSON file")
    quality.add_argument("evidence", type=Path)
    collect = sub.add_parser("collect", help="Collect bounded FDA or EDGAR source candidates for review")
    collect.add_argument("source", choices=("drugs_at_fda", "openfda_crl", "edgar", "ibkr"))
    collect.add_argument("--cache", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--offline", action="store_true", help="Replay only saved cache responses")
    collect.add_argument("--settings", type=Path, default=root / "settings.env")
    collect.add_argument("--since", default="2015-01-01")
    collect.add_argument("--until", default=date.today().isoformat())
    collect.add_argument("--page-size", type=int, default=10)
    collect.add_argument("--max-pages", type=int, default=1)
    collect.add_argument("--search")
    collect.add_argument("--cik")
    collect.add_argument("--bars", type=Path, help="Saved primary IBKR historical JSONL in deal filings/work")
    collect.add_argument("--tickers", nargs="+", default=[])
    collect.add_argument("--max-filings", type=int, default=1)
    collect.add_argument("--max-history", type=int, default=1)
    collect.add_argument("--max-exhibits", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        if args.command == "collect":
            from .collectors.http import Client, saved_contact
            from .collectors import fda, edgar
            with job_lock(args.cache / '.collection.lock'):
                contact = saved_contact(args.settings) if args.source == "edgar" and not args.offline else None
                client = Client(args.cache, contact=contact, offline=args.offline)
                if args.source == "ibkr":
                    from .collectors import ibkr
                    if args.bars is None or not args.tickers:
                        raise ValueError("IBKR ingestion needs --bars and --tickers. Current quotes are not historical bars.")
                    result = ibkr.collect(args.bars, tickers=args.tickers, since=args.since, until=args.until)
                elif args.source == "edgar":
                    result = edgar.collect(client, args.cik, since=args.since, until=args.until,
                                           max_filings=args.max_filings, max_history=args.max_history,
                                           max_exhibits=args.max_exhibits)
                else:
                    result = fda.collect(client, args.source, since=args.since, until=args.until,
                                         page_size=args.page_size, max_pages=args.max_pages, search=args.search)
                result["stage"] = "source_candidates_not_verified_events"
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2) + "\n")
            print(f"Saved {args.output}. Source gaps {result['gap_count']}. Candidates still need verification.")
            return 1 if result["gap_count"] else 0
        if args.command == "gates":
            print(json.dumps(validate(json.loads(args.evidence.read_text())), indent=2))
            return 0
        if args.command in ("build", "update"):
            if not args.input.exists() and not args.collection:
                if not args.db.exists():
                    result = build(args.db, {"as_of": date.today().isoformat(), "events": [], "prices": [], "sessions": [],
                                           "gaps": [f"Snapshot not found. {args.input}"]}, root / "knowledge")
                    print("Saved an empty database with a missing-source gap.", file=sys.stderr)
                raise ValueError(f"Source snapshot not found. {args.input}. Supply FDA, CRL, EDGAR and IBKR data; fixtures are not production data.")
            from .pipeline import assemble
            snapshot = (json.loads(args.input.read_text()) if args.input.exists()
                        else {"as_of": date.today().isoformat(), "events": [], "prices": [], "sessions": []})
            if args.collection:
                snapshot = assemble(snapshot, args.collection)
            result = build(args.db, snapshot, root / "knowledge", update=args.command == "update")
        else:
            if Path(args.name).name != args.name or not (root / "deals" / args.name).is_dir():
                raise ValueError("Deal folder does not exist")
            result = report(args.db, args.name, root / "knowledge")
        from .publication import check
        check(args.db, result)
        print(json.dumps(result, indent=2) if getattr(args, "json", False) else render(result), end="\n")
        return 1 if args.command in ("build", "update") and result["gaps"] else 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        print(f"Stopped. {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
