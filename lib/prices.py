#!/usr/bin/env python3
"""Refresh prices everywhere with one IBKR request, then let Python redo the numbers.

Usage
  prices.py collect OUTDIR          list the tickers on the latest shortlist and in every deal, and the UK ISINs
  prices.py apply OUTDIR QUOTES     save the new prices for the shortlist and each deal
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finder  # noqa: E402
import quotes  # noqa: E402

KIT = finder.KIT


def deal_dirs():
    return sorted(d for d in glob.glob(os.path.join(KIT, "deals", "*")) if os.path.isdir(os.path.join(d, "filings")))


def cmd_collect(out):
    tickers = []
    data = finder.load_json(os.path.join(out, "candidates.json"), {"new": []})
    cards = finder.read_cards(out) if os.path.isdir(out) else {}
    for rec in data["new"]:
        c = cards.get(rec.get("id", ""))
        if not c:
            continue
        for t in (rec.get("ticker"), c.get("acquirer_ticker"), c.get("target_ticker")):
            if t:
                tickers.append(str(t).upper())
    uk_deals = []
    for d in deal_dirs():
        uk = quotes.uk_info(d)
        if uk:
            if uk.get("isin"):
                uk_deals.append((uk["isin"], uk.get("company", "")))
            continue
        tickers += quotes.deal_tickers(d)
    tickers = [t for t in dict.fromkeys(tickers) if re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", t)]
    ev = finder.load_json(os.path.join(out, "uk_events.json"), {"new": []})
    for r in ev["new"]:
        if r.get("ticker"):
            tickers.append("%s (London Stock Exchange%s, give the price in pence)" % (
                r["ticker"], (", ISIN " + r["isin"]) if r.get("isin") else ""))
    with open(os.path.join(out, "refresh-tickers.txt"), "w") as fh:
        fh.write("".join(t + "\n" for t in tickers))
    uk = finder.load_json(os.path.join(out, "uk.json"), {"new": []})
    isins = [(c["isin"], c["company"]) for c in uk["new"] if c.get("isin") and cards.get(c.get("id", ""))]
    isins = list(dict.fromkeys(isins + uk_deals))
    with open(os.path.join(out, "refresh-isins.txt"), "w") as fh:
        fh.write("".join("%s %s\n" % i for i in isins))
    print("  refresh     %d tickers and %d UK shares" % (len(tickers), len(isins)))


def cmd_apply(out, qpath):
    qs = quotes.read_quotes(qpath)
    good = {}
    for q in qs:
        try:
            good[str(q["ticker"]).upper()] = {"price": float(q.get("price")), "bid": q.get("bid"), "ask": q.get("ask"),
                                              "date": q.get("time") or "", "time": q.get("time") or "",
                                              "source": "IBKR" + ((", " + q["note"]) if q.get("note") else "")}
        except (TypeError, ValueError):
            continue
    ppath = os.path.join(out, "prices.json")
    allp = finder.load_json(ppath, {})
    allp.update(good)
    finder.save_json(ppath, allp)
    data = finder.load_json(os.path.join(out, "candidates.json"), {"new": []})
    for rec in data["new"]:
        t = (rec.get("ticker") or "").upper()
        if t in good:
            rec["quote"] = good[t]
    finder.save_json(os.path.join(out, "candidates.json"), data)
    for d in deal_dirs():
        mine = set(quotes.deal_tickers(d))
        keep = [q for q in qs if str(q.get("ticker", "")).upper() in mine]
        if not keep:
            continue
        tmp = os.path.join(d, "out", "quotes-refresh.jsonl")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        with open(tmp, "w") as fh:
            fh.write("".join(json.dumps(q) + "\n" for q in keep))
        quotes.fill(d, tmp)
    print("  refresh     %d new price%s saved" % (len(good), "" if len(good) == 1 else "s"))


def cmd_apply_uk(qpath):
    """Put London prices, keyed by ISIN, into each UK deal's market.md."""
    qs = {}
    for line in open(qpath, encoding="utf-8", errors="replace"):
        m = re.search(r"\{.*\}", line)
        if not m:
            continue
        try:
            q = json.loads(m.group(0))
            qs[str(q.get("isin", "")).upper()] = q
        except ValueError:
            continue
    for d in deal_dirs():
        uk = quotes.uk_info(d)
        if not uk or not uk.get("isin") or not uk.get("ticker"):
            continue
        q = qs.get(uk["isin"].upper())
        if not q or q.get("price") is None:
            continue
        tmp = os.path.join(d, "out", "quotes-refresh.jsonl")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        with open(tmp, "w") as fh:
            fh.write(json.dumps({"ticker": uk["ticker"], "price": q["price"], "time": q.get("time", ""),
                                 "note": "pence" + ((", " + q["note"]) if q.get("note") else "")}) + "\n")
        quotes.fill(d, tmp)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "collect":
        cmd_collect(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "apply":
        cmd_apply(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3 and sys.argv[1] == "apply-uk":
        cmd_apply_uk(sys.argv[2])
    else:
        sys.exit(__doc__)
