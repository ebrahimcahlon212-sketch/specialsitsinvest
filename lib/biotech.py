#!/usr/bin/env python3
"""Biotech catalysts: upcoming FDA decisions at listed companies.

US-listed companies state their FDA target action dates, often called PDUFA
dates, in their filings. This searches recent filings for those dates, keeps
the ones still ahead, and adds what Python can work out from the SEC's own
data: cash, how fast the company is burning it, months of runway, and cash per
share once a price is known.

An FDA decision has the same shape as a deal, with a price if approved, a price
if rejected and a probability, so a deep dive's three numbers feed the kit's
usual calculator, sizing, watch and journal.

Usage
  biotech.py scan OUTDIR [DAYS]          find decisions in filings from the last DAYS (default 120)
  biotech.py set-quotes OUTDIR FILE      attach IBKR prices, keyed by ticker
  biotech.py batches OUTDIR              write card prompts for the shortlist
  biotech.py cards OUTDIR FILE...        keep the model's cards
  biotech.py render OUTDIR               write the calendar page
  biotech.py find ID                     print the stored row for a BIO- ID, as JSON
  biotech.py terms DEAL                  turn a deep dive's scenario block into terms.json for the calculator
  biotech.py relabel DEAL                use approval wording in the calculator's tables
"""
import datetime
import glob
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finder  # noqa: E402

TODAY = datetime.date.today()
HORIZON = int(os.environ.get("BIO_HORIZON_MONTHS", "15"))
MAX_COMPANIES = int(os.environ.get("BIO_MAX", "150"))
CARD_MONTHS = int(os.environ.get("BIO_MONTHS", "9"))
MAX_CAP = float(os.environ.get("BIO_MAX_CAP", "5000000000"))
BATCH = 6

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
ABBR = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
        "nov": 11, "dec": 12}
EXACT = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
                   r"Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sept?\.?|Oct\.?|Nov\.?|Dec\.?)\s+(\d{1,2}),?\s+(20\d{2})")
QUARTER = re.compile(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+(?:calendar\s+)?quarter\s+(?:of\s+)?(20\d{2})|\bQ([1-4])\s*(20\d{2})", re.I)
HALF = re.compile(r"\b(first|second)\s+half\s+(?:of\s+)?(20\d{2})|\b(1H|2H|H1|H2)\s*(20\d{2})", re.I)
TRIGGER = re.compile(r"PDUFA|target action date|Prescription Drug User Fee Act", re.I)


def month_end(y, m):
    nxt = datetime.date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return nxt - datetime.timedelta(days=1)


def dates_in(text):
    """Every decision date mentioned near a PDUFA phrase, with the sentence it came from."""
    found = []
    for m in TRIGGER.finditer(text):
        window = text[m.start():m.start() + 320]
        sent_start = text.rfind(".", 0, m.start()) + 1
        sentence = re.sub(r"\s+", " ", text[sent_start:m.start() + 320]).strip()
        e = EXACT.search(window)
        if e:
            mon = e.group(1).lower().rstrip(".")
            mi = MONTHS.get(mon) or ABBR.get(mon[:4] if mon.startswith("sept") else mon[:3])
            try:
                d = datetime.date(int(e.group(3)), mi, int(e.group(2)))
                found.append({"date": d, "approx": False, "text": e.group(0), "sentence": sentence[:420]})
                continue
            except (ValueError, TypeError):
                pass
        q = QUARTER.search(window)
        if q:
            n = q.group(1) or q.group(3)
            qn = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}.get(str(n).lower(), None)
            qn = qn or int(n)
            y = int(q.group(2) or q.group(4))
            found.append({"date": month_end(y, qn * 3), "approx": True, "text": q.group(0), "sentence": sentence[:420]})
            continue
        h = HALF.search(window)
        if h:
            first = (h.group(1) or "").lower() == "first" or (h.group(3) or "").upper() in ("1H", "H1")
            y = int(h.group(2) or h.group(4))
            found.append({"date": month_end(y, 6 if first else 12), "approx": True, "text": h.group(0), "sentence": sentence[:420]})
    return found


def concept(cik, tag):
    url = "https://data.sec.gov/api/xbrl/companyconcept/CIK%s/us-gaap/%s.json" % (finder.cik10(cik), tag)
    try:
        raw = finder.get(url)
    except Exception:
        return []
    if not raw:
        return []
    try:
        return json.loads(raw.decode("utf-8", "replace")).get("units", {}).get("USD", [])
    except ValueError:
        return []


def finances(cik):
    """Latest cash and short-term investments, and the monthly operating cash burn, from XBRL."""
    cash_facts = concept(cik, "CashAndCashEquivalentsAtCarryingValue")
    if not cash_facts:
        return {}
    latest = max(cash_facts, key=lambda f: f.get("end", ""))
    end = latest["end"]
    cash = float(latest["val"])
    for tag in ("ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"):
        same = [f for f in concept(cik, tag) if f.get("end") == end]
        if same:
            cash += float(same[-1]["val"])
            break
    burn = None
    flows = [f for f in concept(cik, "NetCashProvidedByUsedInOperatingActivities") if f.get("start") and f.get("end")]
    if flows:
        f = max(flows, key=lambda x: (x["end"], x["start"]))
        days = (datetime.date.fromisoformat(f["end"]) - datetime.date.fromisoformat(f["start"])).days
        if days > 20:
            months = days / 30.44
            burn = max(0.0, -float(f["val"]) / months)
    out = {"cash": cash, "cash_date": end, "burn_month": burn}
    if burn:
        out["runway_months"] = cash / burn
    return out


def cmd_scan(out, days):
    finder.need_contact()
    os.makedirs(out, exist_ok=True)
    start = (TODAY - datetime.timedelta(days=days)).isoformat()
    newest = {}
    for phrase in ('"PDUFA"', '"target action date"'):
        try:
            hits = finder.efts(phrase, start, TODAY.isoformat(), forms="10-Q,10-K,8-K")
        except Exception as e:
            finder.say("search for %s failed (%s)" % (phrase, e))
            continue
        for h in hits:
            src = h.get("_source", {})
            ciks = [finder.cik10(c) for c in (src.get("ciks") or [])]
            if not ciks or not src.get("adsh"):
                continue
            fname = (h.get("_id") or "").split(":", 1)[-1]
            rec = {"cik": ciks[0], "adsh": src["adsh"], "file": fname, "form": finder.norm_form(src.get("form")),
                   "date": src.get("file_date") or ""}
            if rec["cik"] not in newest or rec["date"] > newest[rec["cik"]]["date"]:
                newest[rec["cik"]] = rec
    finder.say("biotech     %d companies mention a decision date in filings since %s" % (len(newest), start))
    rows = []
    horizon = TODAY + datetime.timedelta(days=int(HORIZON * 30.44))
    for n, rec in enumerate(sorted(newest.values(), key=lambda r: r["date"], reverse=True)[:MAX_COMPANIES]):
        info = finder.company(rec["cik"])
        if not info.get("tickers"):
            continue
        url = "https://www.sec.gov/Archives/edgar/data/%d/%s/%s" % (int(rec["cik"]), rec["adsh"].replace("-", ""), rec["file"])
        raw = finder.get(url, limit=6000000)
        if not raw:
            continue
        text = finder.html_to_text(raw)
        ahead = [d for d in dates_in(text) if TODAY - datetime.timedelta(days=3) <= d["date"] <= horizon]
        if not ahead:
            continue
        uniq = {}
        for d in sorted(ahead, key=lambda x: (x["date"], x["approx"])):
            uniq.setdefault((d["date"], d["approx"]), d)
        ahead = list(uniq.values())
        first = ahead[0]
        windows, last_end = [], -1
        for m in TRIGGER.finditer(text):
            if m.start() < last_end or len(windows) >= 3:
                continue
            lo, hi = max(0, m.start() - 1500), min(len(text), m.start() + 1500)
            windows.append(re.sub(r"\s+", " ", text[lo:hi]).strip())
            last_end = hi
        ticker = info["tickers"][0].upper()
        exch = (info.get("exchanges") or [""])[0]
        row = {"id": "BIO-" + ticker, "company": info["name"], "ticker": ticker, "cik": rec["cik"], "exchange": exch,
               "otc": exch.upper() in ("OTC", "OTCBB", "PINK"), "decision_date": first["date"].isoformat(),
               "approx": first["approx"], "date_text": first["text"], "context": first["sentence"],
               "other_dates": [{"date": d["date"].isoformat(), "approx": d["approx"], "context": d["sentence"]} for d in ahead[1:4]],
               "filing": {"form": rec["form"], "date": rec["date"], "url": url}, "found": TODAY.isoformat(),
               "excerpts": windows}
        row.update(finances(rec["cik"]))
        row["shares"] = finder.shares_outstanding(rec["cik"])
        rows.append(row)
    rows.sort(key=lambda r: r["decision_date"])
    finder.save_json(os.path.join(out, "biotech.json"), {"rows": rows})
    with open(os.path.join(out, "biotech-tickers.txt"), "w") as fh:
        for r in rows:
            if not r["otc"]:
                fh.write(r["ticker"] + "\n")
    finder.say("biotech     %d upcoming decisions in the next %d months" % (len(rows), HORIZON))


def load_rows(out):
    return finder.load_json(os.path.join(out, "biotech.json"), {"rows": []})


def cmd_set_quotes(out, path):
    data = load_rows(out)
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
    for r in data["rows"]:
        q = qs.get(r["ticker"])
        try:
            price = float(q.get("price")) if q else None
        except (TypeError, ValueError):
            price = None
        if price:
            r["price"] = price
            r["price_date"] = q.get("time") or ""
            if r.get("shares"):
                r["market_cap"] = price * r["shares"]
                if r.get("cash") is not None:
                    r["cash_per_share"] = r["cash"] / r["shares"]
    finder.save_json(os.path.join(out, "biotech.json"), data)


def shortlist(rows):
    limit = TODAY + datetime.timedelta(days=int(CARD_MONTHS * 30.44))
    return [r for r in rows if not r["otc"] and r["decision_date"] <= limit.isoformat()
            and (r.get("market_cap") is None or r["market_cap"] <= MAX_CAP)]


def cmd_batches(out):
    data = load_rows(out)
    todo = [r for r in shortlist(data["rows"]) if not r.get("card")]
    for old in glob.glob(os.path.join(out, "bio-batch-*.md")):
        os.remove(old)
    for i in range(0, len(todo), BATCH):
        with open(os.path.join(out, "bio-batch-%d.md" % (i // BATCH + 1)), "w", encoding="utf-8") as fh:
            for r in todo[i:i + BATCH]:
                fh.write("## %s, %s (%s)\n\nDecision date %s%s, from %s filed %s, %s\n\n" % (
                    r["id"], r["company"], r["ticker"], r["decision_date"], " (approximate)" if r["approx"] else "",
                    r["filing"]["form"], r["filing"]["date"], r["filing"]["url"]))
                fh.write("Sentence: %s\n\n" % r["context"])
                for k, ex in enumerate(r.get("excerpts", []), 1):
                    fh.write("Excerpt %d from the filing:\n%s\n\n" % (k, ex))
                for o in r.get("other_dates", []):
                    fh.write("Other date %s: %s\n\n" % (o["date"], o["context"]))
                fin = []
                if r.get("cash") is not None:
                    fin.append("cash and short-term investments %s at %s" % (finder.money(r["cash"]), r.get("cash_date")))
                if r.get("runway_months"):
                    fin.append("about %.0f months of runway at the latest burn" % r["runway_months"])
                if r.get("market_cap"):
                    fin.append("market value about %s" % finder.money(r["market_cap"]))
                if fin:
                    fh.write("Figures worked out by Python: %s.\n\n" % "; ".join(fin))
    n = (len(todo) + BATCH - 1) // BATCH
    print(n)


def cmd_cards(out, paths):
    data = load_rows(out)
    by_id = dict((r["id"], r) for r in data["rows"])
    n = 0
    for p in paths:
        for line in open(p, encoding="utf-8", errors="replace"):
            m = re.search(r"\{.*\}", line)
            if not m:
                continue
            try:
                c = json.loads(m.group(0))
            except ValueError:
                continue
            r = by_id.get(str(c.get("id", "")).upper())
            if r:
                r["card"] = c
                n += 1
    finder.save_json(os.path.join(out, "biotech.json"), data)
    finder.say("biotech     %d cards" % n)


def esc(s):
    return html.escape(str(s if s is not None else ""))


def cmd_render(out):
    data = load_rows(out)
    rows = data["rows"]
    L = ["# Upcoming FDA decisions", "",
         "Found in filings by Python on %s. Dates come from the companies' own filings, and approximate dates are "
         "the end of the period they give. Cash, burn and runway come from the SEC's XBRL data." % TODAY.isoformat(), "",
         "| Decision | Company | Ticker | Market value | Cash per share | Price | Runway | Score | Drug and use |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        c = r.get("card") or {}
        L.append("| %s%s | %s | %s%s | %s | %s | %s | %s | %s | %s |" % (
            r["decision_date"], " (approx.)" if r["approx"] else "", r["company"], r["ticker"], " (OTC)" if r["otc"] else "",
            finder.money(r.get("market_cap")), "$%.2f" % r["cash_per_share"] if r.get("cash_per_share") is not None else "",
            "$%.2f" % r["price"] if r.get("price") else "", "%.0f months" % r["runway_months"] if r.get("runway_months") else "",
            c.get("score", ""), (("%s for %s" % (c.get("drug", ""), c.get("indication", ""))) if c else r["context"][:90]).replace("|", "/")))
    with open(os.path.join(out, "biotech.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    cards = []
    for r in sorted(shortlist(rows), key=lambda r: (-(r.get("card") or {}).get("score", 0) if isinstance((r.get("card") or {}).get("score"), int) else 0, r["decision_date"])):
        c = r.get("card") or {}
        facts = []
        for label, key in (("Drug", "drug"), ("Use", "indication"), ("Application", "application"), ("Type", "modality"),
                           ("Review", "review"), ("Advisory committee", "adcom"), ("Manufacturing", "manufacturing"),
                           ("How much rides on it", "value_share"), ("Why it may be mispriced", "why_mispriced"),
                           ("Watch out for", "red_flags")):
            if c.get(key):
                facts.append("<dt>%s</dt><dd>%s</dd>" % (label, esc(c[key])))
        if r.get("cash_per_share") is not None and r.get("price"):
            facts.append("<dt>Cash, worked out</dt><dd>$%.2f a share against a $%.2f price%s</dd>" % (
                r["cash_per_share"], r["price"], ", about %.0f months of runway" % r["runway_months"] if r.get("runway_months") else ""))
        cards.append('<article class="card"><h3>%s <span class="t">%s</span></h3><p class="meta">Decision %s%s · '
                     'score %s</p><p>%s</p><dl>%s</dl><p class="act"><code>./run.sh promote %s</code> · '
                     '<a href="%s">source filing</a></p></article>' % (
                         esc(r["company"]), esc(r["ticker"]), esc(r["decision_date"]), " (approx.)" if r["approx"] else "",
                         esc(c.get("score", "not reviewed")), esc(c.get("summary") or r["context"]), "".join(facts),
                         esc(r["id"]), esc(r["filing"]["url"])))
    table = "".join("<tr><td>%s%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(r["decision_date"]), " ~" if r["approx"] else "", esc(r["company"]), esc(r["ticker"]),
        esc(finder.money(r.get("market_cap"))), esc("%.0f mo" % r["runway_months"] if r.get("runway_months") else "")) for r in rows)
    page = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Upcoming FDA decisions</title><style>
:root{--bg:#fbfaf7;--ink:#1d1d1b;--muted:#6b6a64;--rule:#e2dfd6;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--ink:#ecebe6;--muted:#a3a29c;--rule:#33322e;--card:#1e1e1b}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:860px;margin:0 auto;padding:1.2rem}h1{font-size:1.5rem}h2{font-size:1.15rem;margin-top:2rem}
.meta{color:var(--muted);font-size:.85rem}.card{background:var(--card);border:1px solid var(--rule);border-radius:10px;padding:1rem;margin:1rem 0}
.card h3{margin:.1rem 0}.t{color:var(--muted);font-weight:500}dl{display:grid;grid-template-columns:11rem 1fr;gap:.25rem .8rem;font-size:.9rem}
dt{color:var(--muted)}dd{margin:0}.act code{font-size:.8rem}.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%%;font-size:.85rem}td{padding:.3rem .5rem;border-bottom:1px solid var(--rule)}
@media (max-width:600px){dl{grid-template-columns:1fr}}</style></head><body><main>
<h1>Upcoming FDA decisions</h1><p class="meta">%d decisions in the next %d months, found in filings on %s. Cards cover smaller
companies with a decision in the next %d months. Dates come from the companies' filings, so check the source before acting.</p>
<h2>Shortlist</h2>%s<h2>Every decision found</h2><div class="scroll"><table>%s</table></div></main></body></html>""" % (
        len(rows), HORIZON, TODAY.isoformat(), CARD_MONTHS, "".join(cards) or "<p>No shortlisted decisions.</p>", table)
    with open(os.path.join(out, "biotech.html"), "w", encoding="utf-8") as fh:
        fh.write(page)


def cmd_find(cid):
    for path in sorted(glob.glob(os.path.join(finder.FINDER, "*", "biotech.json")), reverse=True):
        for r in finder.load_json(path, {"rows": []})["rows"]:
            if r["id"].upper() == cid.upper():
                print(json.dumps(r))
                return
    sys.exit("No biotech decision called %s. The IDs are on the biotech page." % cid)


def cmd_terms(deal):
    out = os.path.join(deal, "out")
    text = open(os.path.join(out, "biotech.md"), encoding="utf-8", errors="replace").read()
    m = re.search(r"<<<BEGIN SCENARIOS>>>(.*?)<<<END SCENARIOS>>>", text, re.S)
    if not m:
        sys.exit("The deep dive didn't include its scenario numbers, so the calculator wasn't run.")
    try:
        s = json.loads(re.search(r"\{.*\}", m.group(1), re.S).group(0))
    except (ValueError, AttributeError):
        sys.exit("The scenario numbers weren't valid JSON.")
    info = finder.load_json(os.path.join(deal, "deal.json"), {})
    t = {"structure": "cash", "target_ticker": (info.get("ticker") or "").upper(), "currency": "USD",
         "cash_per_share": float(s["price_if_approved"]), "break_price": float(s["price_if_rejected"]), "costs_pct": 0,
         "close_scenarios": [{"date": s["decision_date"], "prob": float(s["prob_approval"])}], "kind": "binary decision"}
    with open(os.path.join(out, "terms.json"), "w") as fh:
        json.dump(t, fh, indent=1)
    print("  terms       approval %s, rejection %s, %s chance, decision %s" % (
        s["price_if_approved"], s["price_if_rejected"], s["prob_approval"], s["decision_date"]))


def cmd_relabel(deal):
    path = os.path.join(deal, "out", "calc.md")
    if not os.path.exists(path):
        return
    text = open(path, encoding="utf-8").read()
    for a, b in (("Deal value per share", "Price if approved, estimated"), ("If the deal breaks", "If rejected, estimated"),
                 ("Chance of closing the market implies", "Chance of approval the price implies"),
                 ("Chance of closing, report's estimate", "Chance of approval, deep dive's estimate"),
                 ("when the deal doesn't happen", "if the FDA rejects it"), ("Gain if completed", "Gain if approved"),
                 ("Loss if not", "Loss if rejected"), ("Closing date", "Decision date")):
        text = text.replace(a, b)
    open(path, "w", encoding="utf-8").write(text)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "scan":
        cmd_scan(a[1], int(a[2]) if len(a) > 2 else 120)
    elif len(a) == 3 and a[0] == "set-quotes":
        cmd_set_quotes(a[1], a[2])
    elif len(a) == 2 and a[0] == "batches":
        cmd_batches(a[1])
    elif len(a) >= 3 and a[0] == "cards":
        cmd_cards(a[1], a[2:])
    elif len(a) == 2 and a[0] == "render":
        cmd_render(a[1])
    elif len(a) == 2 and a[0] == "find":
        cmd_find(a[1])
    elif len(a) == 2 and a[0] == "terms":
        cmd_terms(a[1])
    elif len(a) == 2 and a[0] == "relabel":
        cmd_relabel(a[1])
    else:
        sys.exit(__doc__)
