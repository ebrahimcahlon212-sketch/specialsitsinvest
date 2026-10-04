"""Phase 1 event prices from explicit, sourced snapshots. No network or orders.

Sessions are supplied exchange sessions, including early closes. Missing bars
never define a holiday and never move an event's window. Prices retain both
unadjusted and split-adjusted closes; all returns use the latter.
"""
from contextlib import closing
from datetime import date, datetime, time
import hashlib
import json
from pathlib import Path
import sqlite3
from statistics import median
from zoneinfo import ZoneInfo

from .locking import job_lock
from .math import abnormal_return, positive, raw_return

EASTERN = ZoneInfo("America/New_York")
SOURCES = ("drugs_at_fda", "openfda_crl", "edgar", "ibkr")
TYPES = ("approval", "crl", "refusal_to_file", "extension", "resubmission_accepted")


def conventions(knowledge):
    result = {}
    for name in ("rules", "features"):
        content = (Path(knowledge) / f"refclass-{name}.md").read_bytes()
        first = content.decode().splitlines()[0]
        if not first.endswith("version 1"):
            raise ValueError(f"Unsupported {name} version. Update the engine and its tests first.")
        result[f"{name}_version"] = 1
        result[f"{name}_sha256"] = hashlib.sha256(content).hexdigest()
    return result


def announcement(value):
    if len(value) == 10:
        # Date-only announcements assume after close, with an explicit flag.
        return datetime.combine(date.fromisoformat(value), time(23, 59), EASTERN), True
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("Announcement timestamp requires a timezone, or a date for unknown time")
    return instant.astimezone(EASTERN), False


def session_dates(announced_at, sessions):
    instant, unknown = announcement(announced_at)
    rows = sorted(sessions, key=lambda row: row["date"])
    pre, following = [], []
    for row in rows:
        day = date.fromisoformat(row["date"])
        opened = datetime.combine(day, time.fromisoformat(row["open"]), EASTERN)
        closed = datetime.combine(day, time.fromisoformat(row["close"]), EASTERN)
        if not opened < closed:
            raise ValueError("Session open must precede close")
        if closed <= instant:
            pre.append(row["date"])
        if opened > instant:
            following.append(row["date"])
    if not pre or len(following) < 2:
        raise ValueError("Session coverage does not include the pre-news close and two following sessions")
    return pre[-1], following[0], following[1], unknown


def reaction(event, prices, sessions):
    _, unknown = announcement(event["announced_at"])
    result = {"status": "unpriced", "unknown_time": unknown, "reason": None,
              "offering_within_5d": None}
    try:
        pre, one, two, _ = session_dates(event["announced_at"], sessions)
    except ValueError as exc:
        result["reason"] = str(exc)
        return result
    dates = (pre, one, two)
    result.update(pre_date=pre, day1_date=one, day2_date=two)
    lookup = {(row["ticker"], row["date"]): row for row in prices}
    result["price_sources"] = []
    for ticker, prefix in ((event["ticker"], ""), ("XBI", "xbi_")):
        for label, day in zip(("pre", "day1", "day2"), dates):
            row = lookup.get((ticker, day))
            if row is None or row.get("adjusted_close") is None:
                result["reason"] = f"Missing split-adjusted close for {ticker} on {day}"
                return result
            try:
                result[prefix + label + "_close"] = positive(row["adjusted_close"])
                result[prefix + label + "_unadjusted_close"] = positive(row["close"])
            except (ValueError, TypeError) as exc:
                result["reason"] = f"Invalid close for {ticker} on {day}. {exc}"
                return result
            result["price_sources"].append({"ticker": ticker, "date": day, "source": row["source"]})
    for day in ("day1", "day2"):
        result[day + "_raw"] = raw_return(result["pre_close"], result[day + "_close"])
        result[day + "_abnormal"] = abnormal_return(
            result["pre_close"], result[day + "_close"], result["xbi_pre_close"], result["xbi_" + day + "_close"])
    result["status"] = "priced"
    following = sorted(s["date"] for s in sessions if s["date"] >= one)[:5]
    offerings = event.get("offering_dates")
    if offerings is not None:
        if any(day in following for day in offerings):
            result["offering_within_5d"] = True
        elif len(following) == 5 and event.get("offering_coverage_through", "") >= following[-1]:
            result["offering_within_5d"] = False
    return result


def exclusion(event, as_of):
    when, _ = announcement(event["announced_at"])
    if not date(2015, 1, 1) <= when.date() <= date.fromisoformat(as_of):
        return "Outside the event window"
    if event["event_type"] not in TYPES:
        return "Unsupported event type"
    if event.get("application") not in ("NDA", "BLA") or event.get("original") is not True:
        return "Not an original NDA or BLA"
    if event.get("listed_us") is not True:
        return "US listing at the event is not established"
    return None


def market_value(event, prices, sessions):
    """Unadjusted pre-news price times contemporaneous common shares, USD."""
    try:
        pre = session_dates(event["announced_at"], sessions)[0]
        as_of = date.fromisoformat(event["shares_as_of"])
        instant, _ = announcement(event["announced_at"])
        if as_of >= instant.date() or not event.get("shares_source"):
            return None
        close = next(p["close"] for p in prices if p["ticker"] == event["ticker"] and p["date"] == pre)
        return positive(close) * positive(event["shares"])
    except (ValueError, TypeError, KeyError, StopIteration):
        return None


def reconcile_tags(event):
    """Agreement is computed from distinct taggers, never accepted as an input."""
    event = dict(event)
    tags = [dict(tag) for tag in event.get("tags", [])]
    agreed = {}
    for feature in {tag["feature"] for tag in tags}:
        observations = [tag for tag in tags if tag["feature"] == feature]
        valid = all(tag.get("tagger") and tag.get("locator") for tag in observations)
        values = {json.dumps(tag["value"], sort_keys=True) for tag in observations}
        readers = {tag.get("tagger") for tag in observations}
        match = valid and len(readers) >= 2 and len(values) == 1
        for tag in observations:
            tag["agreed"] = match
        if match:
            agreed[feature] = observations[0]["value"]
    event["tags"] = tags
    for feature in ("first_product", "same_day_news"):
        event[feature] = {"yes": True, "no": False}.get(agreed.get(feature))
    return event


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT PRIMARY KEY, company TEXT NOT NULL, ticker TEXT NOT NULL,
 drug TEXT, application TEXT, event_type TEXT, announced_at TEXT,
 goal_date TEXT, source TEXT, payload TEXT NOT NULL, exclusion TEXT,
 market_value REAL);
CREATE TABLE IF NOT EXISTS tags (
 event_id TEXT, feature TEXT, value TEXT, tagger TEXT, locator TEXT, agreed INTEGER,
 PRIMARY KEY(event_id, feature, tagger));
CREATE TABLE IF NOT EXISTS prices (
 ticker TEXT, date TEXT, close REAL, adjusted_close REAL, source TEXT,
 PRIMARY KEY(ticker, date));
CREATE TABLE IF NOT EXISTS reactions (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (date TEXT PRIMARY KEY, open TEXT, close TEXT);
"""


def build(db, snapshot, knowledge, update=False):
    """Import a complete snapshot or merge an incremental one, atomically.

    All four sources must explicitly describe coverage. This is an import
    boundary, not a claim that a normalized file constitutes a full FDA census.
    """
    db = Path(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    rules = conventions(knowledge)
    with job_lock(str(db) + ".lock"), closing(sqlite3.connect(db)) as connection, connection:
        connection.executescript(SCHEMA)
        if update:
            previous = dict(connection.execute("SELECT key,value FROM metadata"))
            for key, value in rules.items():
                if key in previous and json.loads(previous[key]) != value:
                    raise ValueError("Rules or features changed. Rebuild before updating.")
            old_events = [json.loads(row[0]) for row in connection.execute("SELECT payload FROM events")]
            connection.row_factory = sqlite3.Row
            old_prices = [dict(row) for row in connection.execute("SELECT * FROM prices")]
            old_sessions = [dict(row) for row in connection.execute("SELECT * FROM sessions")]
            connection.row_factory = None
            snapshot = dict(snapshot)
            for key, old, identity in (("events", old_events, lambda x: x["event_id"]),
                                       ("prices", old_prices, lambda x: (x["ticker"], x["date"])),
                                       ("sessions", old_sessions, lambda x: x["date"])):
                merged = {identity(row): row for row in old}
                merged.update({identity(row): row for row in snapshot.get(key, [])})
                snapshot[key] = list(merged.values())
            snapshot["fixture"] = bool(snapshot.get("fixture") or json.loads(previous.get("fixture", "false")))
            coverage = json.loads(previous.get("coverage", "{}"))
            coverage.update(snapshot.get("coverage", {}))
            snapshot["coverage"] = coverage
            snapshot["gaps"] = sorted(set(json.loads(previous.get("gaps", "[]")) + snapshot.get("gaps", [])))
        as_of = snapshot["as_of"]
        date.fromisoformat(as_of)
        events, prices, sessions = (snapshot.get(key, []) for key in ("events", "prices", "sessions"))
        seen = set()
        prepared = []
        for event in events:
            if not snapshot.get("fixture"):
                event = reconcile_tags(event)
            for key in ("event_id", "company", "ticker", "event_type", "announced_at", "source", "locator"):
                if not event.get(key):
                    raise ValueError(f"Event is missing {key}")
            if event["event_id"] in seen:
                raise ValueError("Duplicate event_id in snapshot")
            seen.add(event["event_id"])
            excluded = exclusion(event, as_of)
            prepared.append((event, excluded, market_value(event, prices, sessions),
                             reaction(event, prices, sessions) if not excluded else {"status": "excluded", "reason": excluded}))
        # Validate provenance and dates before replacing any data.
        for row in prices:
            date.fromisoformat(row["date"])
            if not row.get("source"):
                raise ValueError("Price source is required")
        for row in sessions:
            date.fromisoformat(row["date"])
            if time.fromisoformat(row["open"]) >= time.fromisoformat(row["close"]):
                raise ValueError("Session open must precede close")
        coverage = snapshot.get("coverage", {})
        metadata = dict(rules, as_of=as_of, fixture=bool(snapshot.get("fixture")),
                        coverage=coverage, gaps=sorted(set(snapshot.get("gaps", []) +
                                                          [f"{s}. Source not supplied" for s in SOURCES if not coverage.get(s)])),
                        summary_convention="Median and linearly interpolated 25th/75th percentiles (type 7)")
        for table in ("events", "prices", "sessions", "reactions", "tags", "metadata"):
            connection.execute("DELETE FROM " + table)
        connection.executemany("INSERT INTO metadata VALUES (?,?)", [(k, json.dumps(v)) for k, v in metadata.items()])
        for event, excluded, cap, r in prepared:
            connection.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (*[event.get(k) for k in ("event_id", "company", "ticker", "drug", "application", "event_type",
                                                         "announced_at", "goal_date", "source")], json.dumps(event), excluded, cap))
            connection.execute("INSERT INTO reactions VALUES (?,?)", (event["event_id"], json.dumps(r)))
            for tag in event.get("tags", []):
                connection.execute("INSERT INTO tags VALUES (?,?,?,?,?,?)", (event["event_id"], tag["feature"],
                                   json.dumps(tag["value"]), tag["tagger"], tag["locator"], int(tag.get("agreed", False))))
        connection.executemany("INSERT INTO prices VALUES (?,?,?,?,?)",
                               [(p["ticker"], p["date"], p.get("close"), p.get("adjusted_close"), p["source"]) for p in prices])
        connection.executemany("INSERT INTO sessions VALUES (?,?,?)",
                               [(s["date"], s["open"], s["close"]) for s in sessions])
    return report(db, "all", knowledge)


def distribution(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "median": None, "q1": None, "q3": None}
    def percentile(fraction):
        index = (len(values) - 1) * fraction
        lo = int(index)
        hi = min(lo + 1, len(values) - 1)
        return values[lo] + (values[hi] - values[lo]) * (index - lo)
    return dict(n=len(values), median=median(values), q1=percentile(.25), q3=percentile(.75))


def summarize(rows):
    results = {}
    for kind in TYPES:
        subset = [row for row in rows if row[0]["event_type"] == kind]
        priced = [r for _, r, _ in subset if r["status"] == "priced"]
        result = dict(count=len(subset), priced=len(priced), unpriced=len(subset) - len(priced), thin=len(subset) < 10)
        for key in ("day1_raw", "day2_raw", "day1_abnormal", "day2_abnormal"):
            result[key] = distribution([r[key] for r in priced])
        known_offerings = [r["offering_within_5d"] for r in priced if r["offering_within_5d"] is not None]
        result["offering_within_5d"] = {"known": len(known_offerings), "yes": sum(known_offerings),
                                       "unknown": len(subset) - len(known_offerings)}
        results[kind] = result
    return results


def report(db, name, knowledge):
    rules = conventions(knowledge)
    db = Path(db)
    if not db.exists():
        raise ValueError("No reference-class database. Run refclass build with a sourced snapshot first.")
    with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        metadata = {k: json.loads(v) for k, v in connection.execute("SELECT key,value FROM metadata")}
        if any(metadata.get(key) != value for key, value in rules.items()):
            raise ValueError("Rules or features changed. Rebuild before reporting.")
        stored = list(connection.execute("SELECT e.payload,r.payload,e.market_value,e.exclusion FROM events e JOIN reactions r USING(event_id)"))
    rows = [(json.loads(e), json.loads(r), cap) for e, r, cap, excluded in stored if not excluded]
    first = [row for row in rows if row[0].get("first_product") is True]
    core = [row for row in first if row[2] is not None and row[2] < 3_000_000_000]
    classes = []
    for label, subset in (("A. Every eligible event", rows), ("B. First US product", first),
                           ("C. First product under $3 billion", core)):
        classes.append(dict(label=label, count=len(subset), thin=len(subset) < 10, **summarize(subset),
                            without_same_day_news=summarize([r for r in subset if r[0].get("same_day_news") is False])))
    return dict(metadata, deal=name, found=len(stored), eligible=len(rows), excluded=len(stored) - len(rows),
                unpriced=sum(r["status"] == "unpriced" for _, r, _ in rows),
                unknown_time=sum(r.get("unknown_time", False) for _, r, _ in rows),
                unknown_market_value=sum(cap is None for _, _, cap in rows), classes=classes,
                unknown_first_product=sum(e.get("first_product") is None for e, _, _ in rows),
                events=[dict(event=e, reaction=r, market_value=cap) for e, r, cap in rows])


def render(result):
    lines = [f'Event-price reference class for {result["deal"]}',
             f'Rules version {result["rules_version"]}, SHA-256 {result["rules_sha256"]}',
             f'Features version {result["features_version"]}, SHA-256 {result["features_sha256"]}',
             f'As of {result["as_of"]}. {result["summary_convention"]}.',
             'Returns = adjusted post close / adjusted pre close - 1; abnormal = stock return - XBI return.']
    if result["fixture"]:
        lines.append("SYNTHETIC fixture metadata and XBI. This is not a historical census or a live-use result.")
    lines += [f'Found {result["found"]}. Eligible {result["eligible"]}. Excluded {result["excluded"]}. '
              f'Unpriced {result["unpriced"]}. Unknown announcement time {result["unknown_time"]}. '
              f'Unknown market value {result["unknown_market_value"]}. '
              f'Unknown first-product status {result["unknown_first_product"]}. Source gaps {len(result["gaps"])}.']
    lines.extend("Source gap. " + gap for gap in result["gaps"])
    lines.extend(f"Source coverage. {key}. {value}" for key, value in result["coverage"].items())
    lines.append("No approval probabilities or likelihood ratios in phase 1. Live use requires the phase 2 backtest.")
    def fmt(summary):
        if summary["median"] is None:
            return "not available (n=0)"
        return f'{summary["median"]:.2%} [{summary["q1"]:.2%}, {summary["q3"]:.2%}] (n={summary["n"]})'
    for cls in result["classes"]:
        lines += ["", f'{cls["label"]}, count {cls["count"]}' + (", thin" if cls["thin"] else ""),
                  "| Outcome | News filter | Events | Unpriced | Day one abnormal median [Q1, Q3] | Day two abnormal median [Q1, Q3] |",
                  "|---|---|---:|---:|---|---|"]
        for sensitivity, summary in (("All", cls), ("Without same-day takeover/financing", cls["without_same_day_news"])):
            for kind in TYPES:
                row = summary[kind]
                lines.append(f'| {kind} | {sensitivity} | {row["count"]} | {row["unpriced"]} | '
                             f'{fmt(row["day1_abnormal"])} | {fmt(row["day2_abnormal"])} |')
    lines += ["", "Event windows and inputs"]
    for row in result["events"]:
        e, r = row["event"], row["reaction"]
        flag = " Unknown announcement time, assumed after close." if r.get("unknown_time") else ""
        lines.append(f'{e["company"]} ({e["event_type"]}). [{e["source"]}, {e["locator"]}].{flag}')
        if r["status"] == "unpriced":
            lines.append("Unpriced. " + r["reason"])
        else:
            for label in ("pre", "day1", "day2"):
                lines.append(f'{label} {r[label + "_date"]}. Stock {r[label + "_close"]:.2f}, XBI {r["xbi_" + label + "_close"]:.2f}.')
            lines.append(f'Raw returns {r["day1_raw"]:.2%}, {r["day2_raw"]:.2%}. '
                         f'Abnormal returns {r["day1_abnormal"]:.2%}, {r["day2_abnormal"]:.2%}.')
            for source in r["price_sources"]:
                lines.append(f'[{source["source"]}, {source["ticker"]} {source["date"]}]')
    return "\n".join(lines) + "\n"
