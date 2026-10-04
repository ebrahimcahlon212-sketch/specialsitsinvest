#!/usr/bin/env python3
"""UK special situations beyond takeovers, such as investment trust tenders,
wind-downs, liquidations, returns of capital and demergers.

A browsing model finds and cards them in one step. This file keeps track of
what has been seen, prepares the tickers for IBKR prices, and stores the cards.

Usage
  ukevents.py window OUTDIR          print the date range to search, since the last run
  ukevents.py ingest OUTDIR FILE     keep the new events from the model's reply
  ukevents.py set-quotes OUTDIR FILE attach London prices from IBKR, keyed by ticker
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finder  # noqa: E402

STATE = os.path.join(finder.FINDER, "uk_events_state.json")
CODES = {"tender offer": "TND", "wind-down": "WND", "liquidation": "LIQ", "return of capital": "ROC",
         "demerger": "DMG", "compulsory acquisition": "CMP", "rights issue": "RTS"}


def cmd_window(out):
    state = finder.load_json(STATE, {"last_run": None, "seen": {}})
    today = datetime.date.today()
    override = os.environ.get("FINDER_UK_EVENTS_DAYS", "").strip()
    if override.isdigit():
        start = today - datetime.timedelta(days=min(int(override), 45))
    else:
        start = today - datetime.timedelta(days=7)
        if state.get("last_run"):
            last = datetime.date.fromisoformat(state["last_run"])
            start = max(today - datetime.timedelta(days=14), last - datetime.timedelta(days=1))
    print("%s to %s" % (start.isoformat(), today.isoformat()))


def cmd_ingest(out, path):
    state = finder.load_json(STATE, {"last_run": None, "seen": {}})
    data = finder.load_json(os.path.join(out, "uk_events.json"), {"new": []})
    have = set(e["id"] for e in data["new"])
    added = 0
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"\{.*\}", line)
        if not m:
            continue
        try:
            e = json.loads(m.group(0))
        except ValueError:
            continue
        if not e.get("company"):
            continue
        key = (e.get("url") or "") or "%s|%s|%s" % (e["company"], e.get("event"), e.get("date"))
        if key in state["seen"]:
            continue
        base = finder.slug(e["company"].replace(" plc", "").replace(" PLC", ""))[:10] or "UK"
        cid = "UKE-%s-%s" % (base, CODES.get((e.get("event") or "").lower(), "EVT"))
        i = 2
        while cid in have:
            cid = "UKE-%s-%s%d" % (base, CODES.get((e.get("event") or "").lower(), "EVT"), i)
            i += 1
        rec = {"id": cid, "company": e["company"], "ticker": str(e.get("ticker") or "").upper().strip(),
               "isin": e.get("isin") or "", "category": "uk event", "event": e.get("event") or "other",
               "found": datetime.date.today().isoformat(), "stage": e.get("event") or "",
               "card": dict(e, type="uk event", source=e.get("url") or "", stage=e.get("event") or "")}
        data["new"].append(rec)
        have.add(cid)
        state["seen"][key] = datetime.date.today().isoformat()
        added += 1
    state["last_run"] = datetime.date.today().isoformat()
    cutoff = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
    state["seen"] = dict((k, v) for k, v in state["seen"].items() if v >= cutoff)
    finder.save_json(STATE, state)
    finder.save_json(os.path.join(out, "uk_events.json"), data)
    with open(os.path.join(out, "uk-events-tickers.txt"), "w") as fh:
        for r in data["new"]:
            if r["ticker"] and not r.get("quote"):
                fh.write("%s (London Stock Exchange%s, give the price in pence)\n" % (
                    r["ticker"], (", ISIN " + r["isin"]) if r.get("isin") else ""))
    finder.say("UK events  %d new" % added)


def cmd_set_quotes(out, path):
    data = finder.load_json(os.path.join(out, "uk_events.json"), {"new": []})
    qs = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"\{.*\}", line)
        if not m:
            continue
        try:
            q = json.loads(m.group(0))
            t = re.sub(r"\s*\(.*$", "", str(q.get("ticker", ""))).upper().strip()
            qs[t] = q
        except ValueError:
            continue
    n = 0
    for r in data["new"]:
        q = qs.get(r.get("ticker", "").upper())
        try:
            price = float(q.get("price")) if q else None
        except (TypeError, ValueError):
            price = None
        if price is None:
            continue
        r["quote"] = {"price": price, "bid": q.get("bid"), "ask": q.get("ask"), "date": q.get("time") or "",
                      "source": "IBKR, pence" + ((", " + q["note"]) if q.get("note") else "")}
        n += 1
    finder.save_json(os.path.join(out, "uk_events.json"), data)
    if n:
        finder.say("%d UK event price%s from IBKR" % (n, "" if n == 1 else "s"))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "window":
        cmd_window(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "ingest":
        cmd_ingest(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 4 and sys.argv[1] == "set-quotes":
        cmd_set_quotes(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
