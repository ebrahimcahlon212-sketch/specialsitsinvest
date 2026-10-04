#!/usr/bin/env python3
"""UK takeover situations from the Takeover Panel's Disclosure Table.

The Panel publishes, as a CSV file updated through the day, every UK company
in an offer period, with each bidder, when the bidder was identified, and any
Rule 2.6 "put up or shut up" deadline. A bidder whose own shares need no
disclosure is almost always offering cash.

run.sh calls these commands.
  uk.py fetch OUTDIR              read the table, pick new and changed situations
  uk.py set-quotes OUTDIR FILE    attach prices from IBKR (JSON lines keyed by ISIN)
  uk.py batches OUTDIR            write the batches the model reads
"""
import csv
import datetime
import hashlib
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finder  # noqa: E402

UK_CSV = "https://www.thetakeoverpanel.org.uk/new/disclosuretable/v3/disclosuretable.csv"
STATE = os.path.join(finder.FINDER, "uk_state.json")
UK_MAX = int(os.environ.get("FINDER_UK_MAX", "12"))
SECTIONS = {"ADDITIONS", "DELETIONS", "OTHER AMENDMENTS", "DISCLOSURE TABLE", "NOTES:"}


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\r", " ").replace("\n", " ")).strip()


def after_colon(s):
    return clean(s.split(":", 1)[1]) if ":" in s else clean(s)


def parse_date(s):
    """'17:00 27-Oct-2026' or '07:00 08-Sep-2026' to a date, or None."""
    m = re.search(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", s or "")
    if not m:
        return None
    try:
        return datetime.datetime.strptime("%s-%s-%s" % m.groups(), "%d-%b-%Y").date()
    except ValueError:
        return None


def parse_table(text):
    """Return (table date text, offerees in the main table)."""
    rows = list(csv.reader(io.StringIO(text)))
    section, date_text = None, ""
    offerees, cur, offeror = [], None, None
    for row in rows:
        cells = [clean(c) for c in row]
        first = cells[0] if cells else ""
        if not first and len(cells) > 1 and not any(cells):
            continue
        if first.upper() in SECTIONS:
            section = first.upper()
            cur = offeror = None
            continue
        if re.match(r"^\d{1,2} [A-Z][a-z]+ \d{4}$", first) and not date_text:
            date_text = first
            continue
        if section != "DISCLOSURE TABLE":
            continue
        if first.upper().startswith("OFFEREE:"):
            name = after_colon(first)
            name = re.sub(r"\s*\(?See Note 9 below\)?", "", name, flags=re.I).strip()
            cur = {"name": name, "lei": after_colon(cells[2]) if len(cells) > 2 else "", "commenced": "",
                   "securities": [], "offerors": []}
            offerees.append(cur)
            offeror = None
        elif cur is None:
            continue
        elif first.lower().startswith("offer period commenced"):
            cur["commenced"] = after_colon(first)
        elif first.upper().startswith("OFFEROR:"):
            offeror = {"name": after_colon(first), "identified": "", "deadline": "", "cash_likely": False,
                       "securities": []}
            cur["offerors"].append(offeror)
        elif first.lower().startswith("offeror identified") and offeror is not None:
            offeror["identified"] = after_colon(first)
        elif first.lower().startswith("rule 2.6") and offeror is not None:
            offeror["deadline"] = after_colon(first)
        elif first.lower().startswith("disclosure of dealings") and offeror is not None:
            offeror["cash_likely"] = True
        elif len(cells) > 1 and cells[1].upper().startswith("ISIN"):
            sec = {"class": first, "isin": after_colon(cells[1]),
                   "nsi": int(re.sub(r"[^\d]", "", cells[2]) or 0) if len(cells) > 2 else 0}
            (offeror["securities"] if (offeror is not None and offeror.get("deadline")) else cur["securities"]).append(sec)
    return date_text, offerees


def describe(o):
    """Plain facts the model and the page use, worked out from the table alone."""
    named = [b for b in o["offerors"] if b["name"].lower() != "no named offeror"]
    deadlines = [parse_date(b["deadline"]) for b in named if parse_date(b["deadline"])]
    if not named:
        stage = "no named bidder (a sale process or an unnamed approach)"
    elif deadlines:
        stage = "possible offer, the bidder must make a firm offer or walk away by the deadline"
    else:
        stage = "bidder named with no deadline, usually a firm offer already announced"
    main = next((s for s in o["securities"] if s.get("isin")), {})
    return {"stage": stage, "deadline": min(deadlines).isoformat() if deadlines else "",
            "bidders": "; ".join("%s (%s)" % (b["name"], "cash likely" if b["cash_likely"] else "offer may include shares")
                                 for b in named) or "none named",
            "isin": main.get("isin", ""), "nsi": main.get("nsi", 0), "share_class": main.get("class", "")}


def signature(o):
    return hashlib.sha1(json.dumps([(b["name"], b["deadline"]) for b in o["offerors"]]).encode()).hexdigest()[:12]


def cmd_fetch(out):
    os.makedirs(out, exist_ok=True)
    try:
        raw = finder.get(UK_CSV, sec=False)
    except Exception as e:
        finder.say("could not read the Takeover Panel table (%s)" % e)
        raw = None
    if not raw:
        with open(os.path.join(out, "uk-isins.txt"), "w") as fh:
            fh.write("")
        return
    date_text, offerees = parse_table(raw.decode("utf-8-sig", "replace"))
    state = finder.load_json(STATE, {"offerees": {}})
    today = datetime.date.today()
    existing = finder.load_json(os.path.join(out, "uk.json"), {"new": [], "departed": [], "table_date": ""})
    have = set(c["key"] for c in existing["new"])
    fresh, seen_keys = [], set()
    for o in offerees:
        info = describe(o)
        key = info["isin"] or o["name"]
        seen_keys.add(key)
        sig = signature(o)
        prev = state["offerees"].get(key)
        if prev and prev.get("sig") == sig:
            prev["last_seen"] = today.isoformat()
            continue
        if key in have:
            continue
        cid = "UK-" + (finder.slug(o["name"].replace(" plc", "").replace(" Limited", ""))[:14] or key[-6:])
        fresh.append(dict(info, key=key, id=cid, company=o["name"], commenced=o["commenced"],
                          change="new" if not prev else "changed", sig=sig,
                          offerors=o["offerors"], category="uk offer", found=today.isoformat()))
    departed = [v["name"] for k, v in state["offerees"].items() if k not in seen_keys and v.get("last_seen") != "gone"]
    for k in list(state["offerees"]):
        if k not in seen_keys:
            state["offerees"][k]["last_seen"] = "gone"

    # Nearest deadlines first, then firm offers, then open processes
    def order(c):
        dl = c["deadline"] or "9999"
        firm = 0 if "firm offer" in c["stage"] else 1
        return (0 if c["deadline"] else 1, dl, firm, c["company"])
    fresh.sort(key=order)
    queued, waiting = fresh[:UK_MAX], fresh[UK_MAX:]
    for c in queued:
        c["pending"] = True
        prev = state["offerees"].get(c["key"]) or {}
        state["offerees"][c["key"]] = {"name": c["company"], "sig": c["sig"],
                                       "first_seen": prev.get("first_seen", today.isoformat()), "last_seen": today.isoformat()}
    for c in waiting:
        state["offerees"].setdefault(c["key"], {"name": c["company"], "sig": "", "first_seen": today.isoformat()})
        state["offerees"][c["key"]]["last_seen"] = today.isoformat()
    if waiting:
        finder.say("%d more UK situation%s will get cards on later runs (limit %d per run)" % (
            len(waiting), "" if len(waiting) == 1 else "s", UK_MAX))
    existing["new"] += queued
    existing["departed"] = sorted(set(existing.get("departed", []) + departed))
    existing["table_date"] = date_text
    finder.save_json(os.path.join(out, "uk.json"), existing)
    finder.save_json(STATE, state)
    with open(os.path.join(out, "uk-isins.txt"), "w") as fh:
        fh.write("".join("%s %s\n" % (c["isin"], c["company"]) for c in queued if c["isin"]))
    finder.say("UK table %s, %d companies in an offer period, %d new or changed" % (
        date_text or "(no date)", len(offerees), len(fresh)))


def cmd_set_quotes(out, qpath, everyone=False):
    data = finder.load_json(os.path.join(out, "uk.json"), {"new": []})
    quotes = {}
    for line in open(qpath, encoding="utf-8", errors="replace"):
        m = re.search(r"\{.*\}", line)
        if not m:
            continue
        try:
            q = json.loads(m.group(0))
            quotes[str(q.get("isin", "")).upper()] = q
        except ValueError:
            continue
    n = 0
    for c in data["new"]:
        q = quotes.get(c.get("isin", "").upper())
        if not q or not (everyone or c.get("pending")):
            continue
        try:
            price = float(q.get("price"))
        except (TypeError, ValueError):
            continue
        unit = str(q.get("currency") or "GBX").upper()
        c["quote"] = {"price": price, "date": q.get("time") or "",
                      "source": "IBKR, %s%s" % ("pence" if unit in ("GBX", "GBP PENCE", "PENCE") else unit,
                                               (", " + q["note"]) if q.get("note") else "")}
        if q.get("ticker"):
            c["ticker"] = str(q["ticker"]).upper()
        pounds = price / 100.0 if unit in ("GBX", "GBP PENCE", "PENCE") else price
        if c.get("nsi"):
            c["market_cap_gbp"] = pounds * c["nsi"]
        n += 1
    finder.save_json(os.path.join(out, "uk.json"), data)
    finder.say("%d UK price%s from IBKR" % (n, "" if n == 1 else "s"))


def cmd_batches(out):
    data = finder.load_json(os.path.join(out, "uk.json"), {"new": []})
    todo = [c for c in data["new"] if c.get("pending")]
    prior = len([f for f in os.listdir(out) if f.startswith("uk-batch-")]) if os.path.isdir(out) else 0
    files = []
    for i in range(0, len(todo), 6):
        chunk = todo[i:i + 6]
        path = os.path.join(out, "uk-batch-%02d.md" % (prior + len(files) + 1))
        lines = ["## UK situations for this run", "",
                 "| ID | Company | ISIN | Shares in issue | Offer period since | Bidders | Stage | Rule 2.6 deadline | Price | Market cap |",
                 "|---|---|---|---|---|---|---|---|---|---|"]
        for c in chunk:
            q = c.get("quote")
            cap = c.get("market_cap_gbp")
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                c["id"], c["company"], c.get("isin") or "unknown", "{:,}".format(c["nsi"]) if c.get("nsi") else "unknown",
                c.get("commenced") or "unknown", c["bidders"].replace("|", "/"), c["stage"], c["deadline"] or "none",
                ("%s (%s)" % (q["price"], q["source"])) if q else "none",
                ("about £%.0f million" % (cap / 1e6)) if cap else "unknown"))
            c.pop("pending", None)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        files.append(path)
    finder.save_json(os.path.join(out, "uk.json"), data)
    with open(os.path.join(out, "uk-batches-new.txt"), "w") as fh:
        fh.write("".join(f + "\n" for f in files))
    finder.say("%d UK batch%s for the models" % (len(files), "" if len(files) == 1 else "es"))


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "fetch":
        cmd_fetch(args[0])
    elif cmd == "set-quotes" and len(args) in (2, 3):
        cmd_set_quotes(args[0], args[1], len(args) == 3 and args[2] == "--all")
    elif cmd == "batches":
        cmd_batches(args[0])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
