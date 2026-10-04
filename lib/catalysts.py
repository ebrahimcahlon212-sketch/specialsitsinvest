#!/usr/bin/env python3
"""A calendar of dated catalysts in undervalued companies.

A browsing model finds companies trading below something measurable, such as
asset value, cash or a minimum buy-out price, where an event on a known date
should close the gap. Python keeps every catalyst across runs, prices the
companies through IBKR, works out the discount to the anchor and the days to
the date, ranks them and writes the calendar page.

Usage
  catalysts.py window MONTHS            print the date window to search
  catalysts.py ingest OUTDIR FILE       keep the model's catalysts, updating ones already known
  catalysts.py tickers OUTDIR           write the IBKR ticker lines for the open catalysts
  catalysts.py set-quotes OUTDIR FILE   attach prices
  catalysts.py render OUTDIR            write the calendar page
  catalysts.py find ID                  print one catalyst as JSON
"""
import datetime
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finder  # noqa: E402

TODAY = datetime.date.today()
STATE = os.path.join(finder.FINDER, "catalysts.json")
CODES = {"trust vote": "TRV", "sale process": "SALE", "ruling": "RUL", "refinancing": "REF", "forced selling": "FS",
         "squeeze-out": "SQZ", "other": "OTH"}
# Only anchors actually paid on the date get a yearly figure. A NAV is reached later, if at all.
PAYOUT_ANCHORS = ("offer", "minimum", "tender")


def load_state():
    return finder.load_json(STATE, {"items": {}})


def cmd_window(months):
    end = TODAY + datetime.timedelta(days=int(months * 30.44))
    print("%s to %s" % (TODAY.isoformat(), end.isoformat()))


def key_of(e):
    return "%s|%s" % (re.sub(r"[^a-z0-9]", "", (e.get("company") or "").lower()), (e.get("type") or "other").lower())


def cmd_ingest(out, path):
    state = load_state()
    items = state["items"]
    new = updated = 0
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"\{.*\}", line)
        if not m:
            continue
        try:
            e = json.loads(m.group(0))
        except ValueError:
            continue
        if not e.get("company") or not e.get("date"):
            continue
        k = key_of(e)
        if k in items:
            items[k].update(dict((a, b) for a, b in e.items() if b not in (None, "", [])))
            items[k]["seen"] = TODAY.isoformat()
            updated += 1
            continue
        base = finder.slug(re.sub(r"\b(plc|PLC|Limited|Ltd|AG|SE|NV|SA)\b", "", e["company"]))[:10] or "CO"
        cid = "CAT-%s-%s" % (base, CODES.get((e.get("type") or "other").lower(), "OTH"))
        while any(v["id"] == cid for v in items.values()):
            cid += "X"
        e.update({"id": cid, "found": TODAY.isoformat(), "seen": TODAY.isoformat()})
        e["ticker"] = str(e.get("ticker") or "").upper().strip()
        items[k] = e
        new += 1
    finder.save_json(STATE, state)
    finder.say("catalysts   %d new, %d updated, %d on the calendar" % (new, updated, len(items)))


def is_london(e):
    return any(w in (e.get("market") or "").lower() for w in ("main market", "aim", "london", "lse"))


def open_items(state):
    return [v for v in state["items"].values() if (v.get("date") or "") >= (TODAY - datetime.timedelta(days=2)).isoformat()]


def cmd_tickers(out):
    state = load_state()
    with open(os.path.join(out, "catalyst-tickers.txt"), "w") as fh:
        for e in open_items(state):
            if not e.get("ticker"):
                continue
            if is_london(e):
                fh.write("%s (London Stock Exchange%s, give the price in pence)\n" % (e["ticker"], (", ISIN " + e["isin"]) if e.get("isin") else ""))
            elif "us" in (e.get("market") or "").lower().split() or re.search(r"nasdaq|nyse", e.get("market") or "", re.I):
                fh.write(e["ticker"] + "\n")
            else:
                fh.write("%s (%s%s, give the price in the local currency)\n" % (e["ticker"], e.get("market") or "European exchange",
                                                                                (", ISIN " + e["isin"]) if e.get("isin") else ""))


def cmd_set_quotes(out, path):
    state = load_state()
    qs = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"\{.*\}", line)
        if not m:
            continue
        try:
            q = json.loads(m.group(0))
            qs[re.sub(r"\s*\(.*$", "", str(q.get("ticker", ""))).upper().strip()] = q
        except ValueError:
            continue
    for e in state["items"].values():
        q = qs.get(e.get("ticker", ""))
        try:
            price = float(q.get("price")) if q else None
        except (TypeError, ValueError):
            price = None
        if price:
            e["price"] = price
            e["price_date"] = q.get("time") or TODAY.isoformat()
    finder.save_json(STATE, state)


def numbers(e):
    out = {}
    try:
        days = (datetime.date.fromisoformat(e["date"]) - TODAY).days
    except (ValueError, KeyError):
        days = None
    out["days"] = days
    a, p = e.get("anchor_value"), e.get("price")
    try:
        a = float(a) if a is not None else None
    except (TypeError, ValueError):
        a = None
    if a and p:
        out["discount"] = 1 - p / a
        out["upside"] = a / p - 1
        kind = (e.get("anchor_kind") or "").lower()
        if days and days > 14 and any(w in kind for w in PAYOUT_ANCHORS):
            out["per_year"] = out["upside"] * 365.0 / days
    return out


def rank(e):
    n = numbers(e)
    return (-int(e.get("score") or 0), -(n.get("upside") or 0), n.get("days") if n.get("days") is not None else 9999)


def esc(s):
    return html.escape(str(s if s is not None else ""))


def pct(x):
    return "" if x is None else "%.0f%%" % (x * 100)


def cmd_render(out):
    state = load_state()
    items = sorted(open_items(state), key=rank)
    unit = lambda e: "p" if is_london(e) else ""
    L = ["# Dated catalysts", "", "Found from announcements and reports, priced and calculated by Python on %s. The discount is the gap "
         "between the price and the stated anchor, which is only as good as the anchor itself." % TODAY.isoformat(), "",
         "| Date | Company | Type | Anchor | Price | Discount | Score | The question |", "|---|---|---|---|---|---|---|---|"]
    for e in items:
        n = numbers(e)
        L.append("| %s%s | %s (%s) | %s | %s %s | %s | %s | %s | %s |" % (
            e["date"], " ~" if e.get("approx") else "", e["company"], e.get("ticker", ""), e.get("type", ""),
            e.get("anchor_kind", ""), ("%s%s" % (e["anchor_value"], unit(e))) if e.get("anchor_value") is not None else "",
            ("%s%s" % (e["price"], unit(e))) if e.get("price") else "", pct(n.get("discount")), e.get("score", ""),
            (e.get("key_question") or "").replace("|", "/")))
    with open(os.path.join(out, "catalysts.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    cards = []
    for e in items:
        n = numbers(e)
        facts = []
        for label, k in (("What happens", "summary"), ("How value unlocks", "how_value_unlocks"), ("The question to answer", "key_question"),
                         ("Who must sell", "forced_selling"), ("Watch out for", "red_flags")):
            if e.get(k):
                facts.append("<dt>%s</dt><dd>%s</dd>" % (label, esc(e[k])))
        calc = []
        if e.get("anchor_value") is not None:
            calc.append("%s of %s%s (%s)" % (esc(e.get("anchor_kind") or "Anchor"), esc(e["anchor_value"]), unit(e), esc(e.get("anchor_date") or "")))
        if e.get("price"):
            calc.append("price %s%s" % (esc(e["price"]), unit(e)))
        if n.get("discount") is not None:
            calc.append("a %s discount, %s upside to the anchor" % (pct(n["discount"]), pct(n["upside"])))
        if n.get("per_year") is not None:
            calc.append("about %s a year if paid on the date" % pct(n["per_year"]))
        if calc:
            facts.append("<dt>Worked out</dt><dd>%s</dd>" % ", ".join(calc))
        srcs = " ".join('<a href="%s">source</a>' % esc(u) for u in (e.get("sources") or [])[:3])
        cards.append('<article class="card"><h3>%s <span class="t">%s</span></h3><p class="meta">%s · %s%s · %s days · score %s</p>'
                     '<dl>%s</dl><p class="act"><code>./run.sh promote %s</code> %s</p></article>' % (
                         esc(e["company"]), esc(e.get("ticker")), esc(e.get("type")), esc(e["date"]), " (estimate)" if e.get("approx") else "",
                         esc(n.get("days")), esc(e.get("score")), "".join(facts), esc(e["id"]), srcs))
    page = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dated catalysts</title><style>
:root{--bg:#fbfaf7;--ink:#1d1d1b;--muted:#6b6a64;--rule:#e2dfd6;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--ink:#ecebe6;--muted:#a3a29c;--rule:#33322e;--card:#1e1e1b}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:860px;margin:0 auto;padding:1.2rem}h1{font-size:1.5rem}.meta{color:var(--muted);font-size:.85rem}
.card{background:var(--card);border:1px solid var(--rule);border-radius:10px;padding:1rem;margin:1rem 0}.card h3{margin:.1rem 0}
.t{color:var(--muted);font-weight:500}dl{display:grid;grid-template-columns:11rem 1fr;gap:.25rem .8rem;font-size:.9rem}
dt{color:var(--muted)}dd{margin:0}.act code{font-size:.8rem}@media (max-width:600px){dl{grid-template-columns:1fr}}
</style></head><body><main><h1>Dated catalysts</h1><p class="meta">%d open catalysts, best first, priced on %s. The discount is only as
good as the anchor, so check the source before acting.</p>%s</main></body></html>""" % (len(items), TODAY.isoformat(), "".join(cards) or "<p>None yet.</p>")
    with open(os.path.join(out, "catalysts.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    finder.say("catalysts   %d open on the calendar" % len(items))


def cmd_find(cid):
    for e in load_state()["items"].values():
        if e["id"].upper() == cid.upper():
            print(json.dumps(e))
            return
    sys.exit("No catalyst called %s. The IDs are on the catalysts page." % cid)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "window":
        cmd_window(int(a[1]))
    elif len(a) == 3 and a[0] == "ingest":
        cmd_ingest(a[1], a[2])
    elif len(a) == 2 and a[0] == "tickers":
        cmd_tickers(a[1])
    elif len(a) == 3 and a[0] == "set-quotes":
        cmd_set_quotes(a[1], a[2])
    elif len(a) == 2 and a[0] == "render":
        cmd_render(a[1])
    elif len(a) == 2 and a[0] == "find":
        cmd_find(a[1])
    else:
        sys.exit(__doc__)
