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
    collect.add_argument("source", choices=("drugs_at_fda", "openfda_crl", "edgar", "ibkr", "massive"))
    collect.add_argument("--cache", type=Path, help="Offline cache override; live downloads always use data/refclass/raw/source/date")
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
    collect.add_argument("--history-years", type=int, default=2, help="Massive plan history, default free-tier two years")
    collect.add_argument("--max-exhibits", type=int, default=2)
    profile = sub.add_parser('profile', help='Validate and save a deal profile from primary deal documents')
    profile.add_argument('name')
    profile.add_argument('--input', type=Path, required=True)
    acceptance = sub.add_parser('acceptance', help='Verify live phase-one criteria for Savara')
    acceptance.add_argument('--db', type=Path, default=Path(os.environ.get('REFCLASS_DB', root / 'data/refclass.sqlite')))
    acceptance.add_argument('--targets', type=Path, required=True)
    prepare = sub.add_parser('prepare-review', help='Assemble candidates and independent review prompts')
    prepare.add_argument('--collection', type=Path, action='append', required=True)
    prepare.add_argument('--output', type=Path, required=True)
    review = sub.add_parser('review', help='Reconcile two saved independent model CSV reviews')
    review.add_argument('--prepared', type=Path)
    review.add_argument('--reviews', type=Path, nargs=2)
    review.add_argument('--output', type=Path)
    review.add_argument('--resolve', type=Path, help='Ebrahim CSV decisions, preserving both original model reviews')
    args = parser.parse_args(argv)
    try:
        if args.command == 'profile':
            from .profile import verify_profile
            folder = root / 'deals' / args.name
            if Path(args.name).name != args.name or not folder.is_dir():
                raise ValueError('Deal folder does not exist')
            profile = json.loads(args.input.read_text())
            verify_profile(profile, folder)
            (folder / 'refclass.json').write_text(json.dumps(profile, indent=2) + '\n')
            print(f'Saved sourced profile in {folder / "refclass.json"}')
            return 0
        if args.command == 'acceptance':
            from .acceptance import evaluate
            print(evaluate(args.db, root / 'knowledge', args.targets))
            return 0
        if args.command == 'prepare-review':
            from .review import prepare
            prepare(args.collection, args.output)
            print(f'Saved code-assembled candidates and two review prompts in {args.output}')
            return 0
        if args.command == 'review':
            from .review import reconcile
            if not any((args.prepared, args.reviews, args.output, args.resolve)):
                from .review import pending_reviews
                rows = list(pending_reviews(root / 'data/refclass'))
                print('\n'.join(rows) if rows else 'No current saved disagreements under data/refclass.')
                return 0
            if not all((args.prepared, args.reviews, args.output)):
                raise ValueError('Reconciliation needs --prepared, --reviews and --output.')
            count = reconcile(args.prepared, args.reviews, args.output, args.resolve)
            print(f'{count} disagreements for Ebrahim. See {args.output / "disagreements.csv"}')
            return 1 if count else 0
        if args.command == "collect":
            from .collectors.http import Client, saved_contact
            from .collectors import fda, edgar
            if not args.offline:
                args.cache = root / 'data/refclass/raw' / args.source / date.today().isoformat()
            elif args.cache is None:
                raise ValueError('Offline replay needs --cache.')
            with job_lock(args.cache / '.collection.lock'):
                contact = saved_contact(args.settings) if args.source == "edgar" and not args.offline else None
                client = Client(args.cache, contact=contact, offline=args.offline)
                if args.source == "massive":
                    from .collectors import massive
                    if not args.tickers:
                        raise ValueError('Massive collection needs --tickers, including historical delisted symbols.')
                    client = massive.Client(args.cache, settings=args.settings, offline=args.offline)
                    result = massive.collect(client, tickers=args.tickers, since=args.since, until=args.until,
                                             history_years=args.history_years)
                elif args.source == "ibkr":
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
                raise ValueError(f"Source snapshot not found. {args.input}. Supply FDA, CRL, EDGAR and Massive data; fixtures are not production data.")
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
