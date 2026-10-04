#!/usr/bin/env python3
"""Find new special situations in SEC filings and keep tracked deals up to date.

run.sh calls these commands.
  finder.py fetch OUTDIR [DAYS]       collect new candidates, update tracked deals, write triage batches
  finder.py render OUTDIR             turn the models' cards into the shortlist page
  finder.py promote ID [NAME]         start a deal folder from a candidate
  finder.py track NAME TICKER_OR_CIK  follow new filings for an existing deal folder

The SEC asks every automated visitor to identify itself, so SEC_CONTACT (your
name and email) must be set. run.sh reads it from settings.env.
"""
import datetime
import glob
import gzip
import hashlib
import html
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prep import _HTMLText  # noqa: E402

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINDER = os.path.join(KIT, "finder")
STATE = os.path.join(FINDER, "state.json")
CONTACT = os.environ.get("SEC_CONTACT", "").strip()
MOCK = os.environ.get("FINDER_MOCK_DIR")
PRICES = os.environ.get("FINDER_PRICES", "stooq").lower()
MAX_TRIAGE = int(os.environ.get("FINDER_MAX", "40"))
BATCH = int(os.environ.get("FINDER_BATCH", "8"))
FOLLOW_DAYS = 120

# Forms that signal a situation on their own, with their category and a sort priority.
INDEX_FORMS = {
    "SC TO-T": ("tender offer", 1), "SC 14D9": ("tender offer", 2),
    "DEFM14A": ("merger", 3), "PREM14A": ("merger", 3), "SC 13E3": ("merger", 3),
    "SC TO-I": ("tender offer", 5), "10-12B": ("spin-off", 5), "S-4": ("merger", 6),
    "SC 13D": ("early signal", 7),
}
# Full-text searches of 8-Ks: category, phrase, 8-K items that must be present, priority.
SEARCHES = [
    ("merger", '"Agreement and Plan of Merger"', {"1.01"}, 4),
    ("bankruptcy", '"Chapter 11"', {"1.03"}, 5),
    ("spin-off", '"independent publicly traded company"', None, 6),
    ("early signal", '"restructuring support agreement"', None, 5),
    ("early signal", '"forbearance agreement"', None, 7),
    ("early signal", '"strategic alternatives"', {"7.01", "8.01", "5.02"}, 7),
    ("early signal", '"Rights Agreement"', {"3.03"}, 7),
    ("liquidation", '"plan of complete liquidation"', None, 3, "8-K,PRE 14A,DEF 14A,DEFA14A"),
    ("liquidation", '"plan of dissolution"', None, 3, "8-K,PRE 14A,DEF 14A,DEFA14A"),
    ("post-reorganization", '"emerged from chapter 11"', None, 5),
    ("post-reorganization", '"plan of reorganization became effective"', None, 5),
]
TRACK_FORMS = re.compile(r"^(8-K|425|DEFM14|PREM14|DEFA14A|DEF 14A|SC TO|SC 14D9|SC 13E3|S-4|10-12|10-Q|10-K|"
                         r"SC 13D|SCHEDULE 13D|6-K|20-F)", re.I)


# ---------------------------------------------------------------------------
# Fetching

_last = [0.0]


def _mock(url):
    path = os.path.join(MOCK, hashlib.md5(url.encode()).hexdigest() + ".dat")
    return open(path, "rb").read() if os.path.exists(path) else None


def get(url, limit=None, sec=True):
    """Return the body of url as bytes, or None if it does not exist."""
    if MOCK:
        data = _mock(url)
        return data[:limit] if (data is not None and limit) else data
    if sec:
        wait = 0.15 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
    headers = {"User-Agent": CONTACT if sec else "Mozilla/5.0 (special-sits-kit)"}
    if not limit:
        headers["Accept-Encoding"] = "gzip"
    for attempt in range(4):
        try:
            _last[0] = time.time()
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                body = r.read(limit) if limit else r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.GzipFile(fileobj=io.BytesIO(body)).read()
                return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 403 and attempt < 1:
                time.sleep(3)
                continue
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 + attempt * 3)
                continue
            raise
        except (urllib.error.URLError, OSError):
            if attempt < 3:
                time.sleep(2 + attempt * 3)
                continue
            raise
    return None


def say(msg):
    print("  " + msg, flush=True)


def need_contact():
    if not CONTACT and not MOCK:
        sys.exit('The SEC asks for a name and email on automated requests. Run ./run.sh contact "Your Name you@example.com" first.')


def load_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)


def norm_form(f):
    return re.sub(r"^SCHEDULE\s+", "SC ", (f or "").upper().strip())


def cik10(c):
    return "%010d" % int(str(c).strip())


def html_to_text(raw):
    s = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    if "<" not in s[:5000] and "<html" not in s.lower()[:5000]:
        return s
    p = _HTMLText()
    try:
        p.feed(s)
        p.close()
    except Exception:
        pass
    return p.text()


# ---------------------------------------------------------------------------
# EDGAR sources

def daily_index_url(d):
    return "https://www.sec.gov/Archives/edgar/daily-index/%d/QTR%d/master.%s.idx" % (
        d.year, (d.month - 1) // 3 + 1, d.strftime("%Y%m%d"))


def daily_index(d):
    try:
        raw = get(daily_index_url(d))
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return None
        raise
    if raw is None:
        return None
    rows = []
    for line in raw.decode("latin-1").splitlines():
        parts = line.split("|")
        if len(parts) < 5 or not parts[0].strip().isdigit():
            continue
        fname = parts[-1].strip()
        acc = os.path.basename(fname).replace(".txt", "")
        rows.append({"cik": cik10(parts[0]), "company": "|".join(parts[1:-3]).strip(),
                     "form": norm_form(parts[-3]), "accession": acc})
    return rows


def efts_url(q, start, end, frm=0, forms="8-K"):
    return "https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(
        {"q": q, "forms": forms, "dateRange": "custom", "startdt": start, "enddt": end, "from": frm})


def efts(q, start, end, forms="8-K", limit=600):
    hits, frm = [], 0
    while frm < limit:
        raw = get(efts_url(q, start, end, frm, forms))
        if raw is None:
            break
        data = json.loads(raw.decode("utf-8", "replace"))
        page = data.get("hits", {}).get("hits", [])
        if not page:
            break
        hits.extend(page)
        total = data.get("hits", {}).get("total", {}).get("value", 0)
        frm += len(page)
        if frm >= total:
            break
    return hits


def submissions_url(c):
    return "https://data.sec.gov/submissions/CIK%s.json" % cik10(c)


_companies = {}


def company(c):
    c = cik10(c)
    if c in _companies:
        return _companies[c]
    info = {"cik": c, "name": "", "tickers": [], "exchanges": [], "sic": "", "recent": []}
    try:
        raw = get(submissions_url(c))
    except Exception:
        info["error"] = True
        return info
    if raw:
        d = json.loads(raw.decode("utf-8", "replace"))
        info.update({"name": d.get("name") or "", "tickers": [t for t in (d.get("tickers") or []) if t],
                     "exchanges": [e for e in (d.get("exchanges") or []) if e],
                     "sic": d.get("sicDescription") or ""})
        rec = (d.get("filings") or {}).get("recent") or {}
        n = len(rec.get("accessionNumber", []))
        for i in range(n):
            def col(k):
                v = rec.get(k) or []
                return v[i] if i < len(v) else ""
            info["recent"].append({"accession": col("accessionNumber"), "date": col("filingDate"),
                                   "form": norm_form(col("form")), "doc": col("primaryDocument"),
                                   "desc": col("primaryDocDescription"), "items": col("items")})
    _companies[c] = info
    return info


def shares_url(c):
    return "https://data.sec.gov/api/xbrl/companyconcept/CIK%s/dei/EntityCommonStockSharesOutstanding.json" % cik10(c)


def shares_outstanding(c):
    """The latest reported share count, or None."""
    try:
        raw = get(shares_url(c))
    except Exception:
        return None
    if not raw:
        return None
    try:
        facts = json.loads(raw.decode("utf-8", "replace")).get("units", {}).get("shares", [])
    except ValueError:
        return None
    if not facts:
        return None
    latest = max(f.get("end", "") for f in facts)
    vals = [f.get("val") for f in facts if f.get("end") == latest and isinstance(f.get("val"), (int, float))]
    return max(vals) if vals else None


def money(v):
    if v is None:
        return "unknown"
    if v >= 1e9:
        return "$%.1f billion" % (v / 1e9)
    return "$%.0f million" % (v / 1e6) if v >= 1e6 else "$%.1f million" % (v / 1e6)


def index_url(c, acc):
    return "https://www.sec.gov/Archives/edgar/data/%d/%s/%s-index.htm" % (int(c), acc.replace("-", ""), acc)


def filing_docs(c, acc):
    """List the documents in a filing from its index page."""
    raw = get(index_url(c, acc))
    docs = []
    if not raw:
        return docs
    page = raw.decode("utf-8", "replace")
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
        m = re.search(r"(/Archives/edgar/data/[^\"'?#<>\s]+)", row)
        if not m or len(cells) < 4:
            continue
        path = m.group(1)
        name = path.rsplit("/", 1)[-1]
        if not re.search(r"\.(htm|html|txt)$", name, re.I):
            continue
        text = [html.unescape(re.sub(r"<[^>]+>", " ", x)).strip() for x in cells]
        if "complete submission" in text[1].lower() or re.match(r"^\d{10}-\d{2}-\d{6}\.txt$", name):
            continue
        docs.append({"url": "https://www.sec.gov" + path, "name": name,
                     "desc": re.sub(r"\s+", " ", text[1]), "type": re.sub(r"\s+", " ", text[3]).upper()})
    return docs


def quote(ticker):
    """A delayed last price from Stooq, or None. Best effort only."""
    if PRICES == "off" or not ticker:
        return None
    sym = ticker.lower().replace(".", "-") + ".us"
    try:
        raw = get("https://stooq.com/q/l/?s=%s&f=sd2t2ohlcv&h&e=csv" % sym, sec=False)
    except Exception:
        return None
    if not raw:
        return None
    lines = raw.decode("utf-8", "replace").strip().splitlines()
    if len(lines) < 2:
        return None
    head, vals = lines[0].split(","), lines[1].split(",")
    row = dict(zip(head, vals))
    try:
        return {"price": float(row.get("Close", "")), "date": row.get("Date", ""), "source": "Stooq, delayed"}
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Choosing and excerpting documents

def pick_docs(form, docs):
    if not docs:
        return []
    primary = next((d for d in docs if norm_form(d["type"]) == form), docs[0])
    chosen = [primary]
    ex99 = [d for d in docs if d["type"].startswith("EX-99") and d is not primary]
    if form == "8-K" or form == "10-12B" or form.startswith("SC TO"):
        if form.startswith("SC TO"):
            offer = [d for d in ex99 if "(A)(1)" in d["type"] or "OFFER TO" in d["desc"].upper()]
            ex99 = offer or ex99
        chosen += ex99[:1]
    return chosen


def excerpt(form, docs):
    limits = {"8-K": (6000, 14000), "SC TO-T": (6000, 22000), "SC TO-I": (6000, 22000), "10-12B": (4000, 26000)}
    first, rest = limits.get(form, (26000, 0))
    parts = []
    for i, d in enumerate(docs):
        raw = get(d["url"], limit=3000000)
        if not raw:
            continue
        text = re.sub(r"\n{3,}", "\n\n", html_to_text(raw)).strip()
        cap = first if i == 0 else rest
        parts.append("===== %s (%s) =====\n%s" % (d["name"], d["type"] or "document", text[:cap]))
    return "\n\n".join(parts)


def parse_display(name):
    m = re.match(r"^(.*?)\s*(?:\(([^()]*)\))?\s*\(CIK\s*(\d+)\)\s*$", name or "")
    if not m:
        return name, []
    tickers = [t.strip() for t in (m.group(2) or "").split(",") if t.strip()]
    return m.group(1).strip(), tickers


def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "", s or "").upper()


# ---------------------------------------------------------------------------
# fetch

def cmd_fetch(out, days=None):
    need_contact()
    os.makedirs(out, exist_ok=True)
    os.makedirs(FINDER, exist_ok=True)
    state = load_json(STATE, {"last_index_date": None, "seen": {}, "seen_cik_type": {}, "cards": {}})
    today = datetime.date.today()
    if days:
        start = today - datetime.timedelta(days=int(days))
    elif state.get("last_index_date"):
        start = datetime.date.fromisoformat(state["last_index_date"]) + datetime.timedelta(days=1)
    else:
        start = today - datetime.timedelta(days=1)
    # A daily run looks back at most 10 days. Asking for more, as in ./run.sh find 30, allows up to 45.
    start = max(start, today - datetime.timedelta(days=45 if days else 10))

    raw_cands = {}

    def add(acc, form, category, priority, ciks, names=None, filer=None):
        if acc in state["seen"] or acc in raw_cands:
            return
        raw_cands[acc] = {"accession": acc, "form": form, "category": category, "priority": priority,
                          "ciks": list(dict.fromkeys(ciks)), "names": names or {}, "filer": filer or ciks[0]}

    # 1. Daily form indexes
    d, last_ok = start, state.get("last_index_date")
    while d < today:
        if d.weekday() < 5:
            try:
                rows = daily_index(d)
            except Exception as e:
                say("could not read the index for %s (%s), skipping it" % (d.isoformat(), e))
                d += datetime.timedelta(days=1)
                continue
            if rows is None:
                say("no index yet for %s" % d.isoformat())
            else:
                last_ok = d.isoformat()
                by_acc = {}
                for r in rows:
                    by_acc.setdefault(r["accession"], []).append(r)
                n = 0
                for acc, rs in by_acc.items():
                    form = rs[0]["form"]
                    if form in INDEX_FORMS:
                        cat, pri = INDEX_FORMS[form]
                        add(acc, form, cat, pri, [r["cik"] for r in rs], {r["cik"]: r["company"] for r in rs})
                        n += 1
                say("index %s, %d filings, %d of interest" % (d.isoformat(), len(by_acc), n))
        d += datetime.timedelta(days=1)

    # 2. Full-text searches of 8-Ks, which appear here within minutes of filing
    s_start = start.isoformat()
    for entry in SEARCHES:
        cat, phrase, items, pri = entry[:4]
        forms = entry[4] if len(entry) > 4 else "8-K"
        allowed = set(norm_form(f) for f in forms.split(","))
        try:
            hits = efts(phrase, s_start, today.isoformat(), forms=forms)
        except Exception as e:
            say("full-text search for %s failed (%s)" % (cat, e))
            continue
        n = 0
        for h in hits:
            src = h.get("_source", {})
            if norm_form(src.get("form")) not in allowed:
                continue
            if items and not items & set(src.get("items") or []):
                continue
            ciks = [cik10(c) for c in (src.get("ciks") or [])]
            if not ciks or not src.get("adsh"):
                continue
            names = {}
            for c, dn in zip(ciks, src.get("display_names") or []):
                names[c] = parse_display(dn)[0]
            before = len(raw_cands)
            add(src["adsh"], "8-K", cat, pri, ciks, names)
            n += len(raw_cands) - before
        say("search %s, %d new filings" % (cat if cat in ("merger", "bankruptcy", "spin-off") else phrase.strip('"'), n))

    # 3. Keep situations involving a listed company, and mark repeats of earlier finds
    cands, follow, skipped = [], [], 0
    run_keys = {}
    now = today.isoformat()
    for acc, c in sorted(raw_cands.items(), key=lambda kv: kv[1]["priority"]):
        infos = [company(x) for x in c["ciks"]]
        if any(i.get("error") for i in infos):
            say("could not look up the company for %s, will try again next run" % acc)
            continue
        listed = [i for i in infos if i["tickers"]]
        state["seen"][acc] = now
        if not listed and c["category"] != "spin-off":
            skipped += 1
            continue
        main = listed[0] if listed else infos[0]
        key = "%s|%s" % (main["cik"], c["category"])
        prior = state["seen_cik_type"].get(key)
        rec = {"accession": acc, "form": c["form"], "category": c["category"], "priority": c["priority"],
               "cik": main["cik"], "company": main["name"] or c["names"].get(main["cik"], ""),
               "ticker": main["tickers"][0] if main["tickers"] else "", "tickers": main["tickers"], "exchange": ", ".join(main["exchanges"]),
               "others": [{"cik": i["cik"], "name": i["name"], "tickers": i["tickers"]} for i in infos if i is not main],
               "index_url": index_url(c["filer"], acc), "filer": c["filer"], "found": now}
        if key in run_keys:
            run_keys[key].setdefault("related", []).append({"form": rec["form"], "index_url": rec["index_url"]})
        elif prior and (today - datetime.date.fromisoformat(prior)).days <= FOLLOW_DAYS:
            rec["earlier"] = state.get("cards", {}).get(key, {})
            follow.append(rec)
        else:
            run_keys[key] = rec
            cands.append(rec)
    say("%d new situations, %d filings on earlier finds, %d without a listed company" % (
        len(cands), len(follow), skipped))

    # 4. Excerpts and quotes for the ones the models will read
    existing = load_json(os.path.join(out, "candidates.json"), {"new": [], "follow": [], "updates": []})
    taken = set(x["id"] for x in existing["new"])
    triage = cands[:MAX_TRIAGE]
    for rec in cands[MAX_TRIAGE:]:
        rec["id"] = "%s-%s" % (slug(rec["ticker"]), rec["accession"][-6:])
        rec["untriaged"] = "Over the daily limit of %d" % MAX_TRIAGE
    for rec in triage:
        base = "%s-%s" % (slug(rec["ticker"]) or rec["cik"][-6:], slug(rec["form"]))
        cid, i = base, 2
        while cid in taken:
            cid = "%s-%d" % (base, i)
            i += 1
        taken.add(cid)
        rec["id"] = cid
        try:
            docs = filing_docs(rec["filer"], rec["accession"])
            chosen = pick_docs(rec["form"], docs)
            text = excerpt(rec["form"], chosen) if chosen else ""
        except Exception as e:
            say("could not download %s (%s)" % (rec["accession"], e))
            docs, text = [], ""
        rec["docs"] = docs
        rec["shares_out"] = shares_outstanding(rec["cik"]) if rec.get("ticker") else None
        rec["odd_lot_text"] = bool(re.search(r"odd[\s-]lot", text or "", re.I))
        folder = os.path.join(out, "candidates", cid)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "excerpt.txt"), "w", encoding="utf-8") as fh:
            fh.write(text or "The filing's documents could not be downloaded.")
        rec["quote"] = quote(rec["ticker"]) if PRICES == "stooq" else None
        save_json(os.path.join(folder, "meta.json"), {k: v for k, v in rec.items() if k != "docs"})
        state["seen_cik_type"]["%s|%s" % (rec["cik"], rec["category"])] = now
        say("%-22s %-8s %s" % (cid, rec["form"], rec["company"][:40]))

    # 5. Tracked deals
    updates = update_tracked(today)

    existing["new"] += cands
    existing["follow"] += follow
    existing["updates"] += updates
    # 6. The models read these next, once prices are in
    for rec in triage:
        rec["pending"] = True
    save_json(os.path.join(out, "candidates.json"), existing)
    tickers = list(dict.fromkeys(r["ticker"] for r in triage if r.get("ticker")))
    with open(os.path.join(out, "tickers-new.txt"), "w") as fh:
        fh.write("".join(t + "\n" for t in tickers))

    state["last_index_date"] = last_ok
    cutoff = (today - datetime.timedelta(days=45)).isoformat()
    state["seen"] = dict((k, v) for k, v in state["seen"].items() if v >= cutoff)
    save_json(STATE, state)


def update_tracked(today):
    import gather as gather_mod
    updates = []
    for path in sorted(glob.glob(os.path.join(KIT, "deals", "*", "deal.json"))):
        deal_dir = os.path.dirname(path)
        name = os.path.basename(deal_dir)
        d = load_json(path, {})
        if not d.get("cik"):
            continue
        have = set(d.get("have", []))
        last = d.get("last_checked") or today.isoformat()
        new = [r for r in company(d["cik"])["recent"] if r["date"] >= last and r["accession"] not in have
               and TRACK_FORMS.match(r["form"])]
        if not new:
            continue
        try:
            added = gather_mod.gather(deal_dir, quiet=True)
        except Exception as e:
            say("could not update %s (%s)" % (name, e))
            continue
        for r in sorted(new, key=lambda r: r["date"]):
            desc = r["desc"] if r["desc"] and norm_form(r["desc"]) != r["form"] else ""
            updates.append({"deal": name, "form": r["form"], "date": r["date"], "desc": desc, "items": r["items"],
                            "saved": bool(added), "index_url": index_url(d["cik"], r["accession"])})
        d = load_json(path, {})
        d["have"] = sorted(set(d.get("have", [])) | set(r["accession"] for r in new))[-400:]
        save_json(path, d)
        say("tracked %s, %d new filing%s" % (name, len(new), "" if len(new) == 1 else "s"))
    return updates


def cmd_set_quotes(out, qpath):
    data = load_json(os.path.join(out, "candidates.json"), {"new": []})
    quotes = {}
    for line in open(qpath, encoding="utf-8", errors="replace"):
        m = re.search(r"\{.*\}", line)
        if not m:
            continue
        try:
            q = json.loads(m.group(0))
        except ValueError:
            continue
        try:
            quotes[str(q.get("ticker", "")).upper()] = {"price": float(q.get("price")), "date": q.get("time") or "",
                                                       "source": "IBKR" + (", " + q["note"] if q.get("note") else "")}
        except (TypeError, ValueError):
            continue
    n = 0
    for rec in data["new"]:
        if rec.get("pending") and rec.get("ticker", "").upper() in quotes:
            rec["quote"] = quotes[rec["ticker"].upper()]
            n += 1
    save_json(os.path.join(out, "candidates.json"), data)
    say("%d price%s from IBKR" % (n, "" if n == 1 else "s"))


def cmd_fill_quotes(out):
    """Use Stooq for any pending candidate that still has no price."""
    if PRICES == "off":
        return
    data = load_json(os.path.join(out, "candidates.json"), {"new": []})
    n = 0
    for rec in data["new"]:
        if rec.get("pending") and not rec.get("quote") and rec.get("ticker"):
            rec["quote"] = quote(rec["ticker"])
            n += bool(rec["quote"])
    save_json(os.path.join(out, "candidates.json"), data)
    if n:
        say("%d price%s from Stooq" % (n, "" if n == 1 else "s"))


def cmd_requeue(out):
    data = load_json(os.path.join(out, "candidates.json"), {"new": []})
    cards = read_cards(out)
    n = 0
    for rec in data["new"]:
        if rec.get("id") and rec["id"] not in cards and os.path.isdir(os.path.join(out, "candidates", rec["id"])):
            rec["pending"] = True
            rec.pop("untriaged", None)
            n += 1
    save_json(os.path.join(out, "candidates.json"), data)
    say("%d card%s to write again" % (n, "" if n == 1 else "s"))


def quote_text(q):
    if not q:
        return "none"
    when = " on %s" % q["date"] if q.get("date") else ""
    return "%s%s (%s)" % (q["price"], when, q.get("source") or "")


def covered_ciks():
    """Companies that already have a deal folder, so the hunt doesn't research them twice."""
    out, sources = set(), set()
    for path in glob.glob(os.path.join(KIT, "deals", "*", "deal.json")):
        d = load_json(path, {})
        if d.get("cik"):
            out.add(d["cik"])
        out.update(d.get("related_ciks") or [])
        if d.get("source"):
            sources.add(d["source"])
    return out, sources


def cmd_pick(out, min_score, max_n):
    data = load_json(os.path.join(out, "candidates.json"), {"new": []})
    cards = read_cards(out)
    covered, sources = covered_ciks()
    rows = []
    for rec in data["new"]:
        c = cards.get(rec.get("id", ""))
        if not c or rec.get("category") == "early signal" or rec["id"] in sources:
            continue
        ciks = set([rec["cik"]] + [o["cik"] for o in rec.get("others", [])])
        if ciks & covered or score_of(c) < int(min_score):
            continue
        rows.append(rec)
    rows.sort(key=lambda r: (-score_of(cards[r["id"]]), r["priority"]))
    taken, chosen = set(), []
    for rec in rows:
        if rec["cik"] in taken:
            continue
        base = (slug(rec.get("ticker")) or rec["cik"][-6:]).lower()
        name, i = base, 2
        while os.path.exists(os.path.join(KIT, "deals", name)):
            name = "%s-%d" % (base, i)
            i += 1
        chosen.append("%s %s" % (rec["id"], name))
        taken.add(rec["cik"])
        if len(chosen) >= int(max_n):
            break
    print("\n".join(chosen))


def cmd_batches(out):
    data = load_json(os.path.join(out, "candidates.json"), {"new": []})
    todo = [r for r in data["new"] if r.get("pending")]
    prior = len(glob.glob(os.path.join(out, "batch-*.md")))
    files = []
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        path = os.path.join(out, "batch-%02d.md" % (prior + len(files) + 1))
        lines = ["## Candidates for this run", "",
                 "| ID | Type | Form | Filed | Company | Ticker | Exchange | Quote | Market cap | Odd lot mentioned | Excerpt | Details |",
                 "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in chunk:
            qs = quote_text(r.get("quote"))
            q = r.get("quote")
            cap = r["shares_out"] * float(q["price"]) if (q and r.get("shares_out")) else None
            r["market_cap"] = cap
            rel = os.path.relpath(os.path.join(out, "candidates", r["id"]), KIT)
            meta = os.path.join(out, "candidates", r["id"], "meta.json")
            if os.path.exists(meta):
                save_json(meta, dict((k, v) for k, v in r.items() if k not in ("docs", "pending")))
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s/excerpt.txt | %s/meta.json |" % (
                r["id"], r["category"], r["form"], r["found"], r["company"].replace("|", "/"), r["ticker"],
                r.get("exchange") or "unknown", qs.replace("|", "/"), money(cap),
                "yes" if r.get("odd_lot_text") else "no", rel, rel))
            r.pop("pending", None)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        files.append(path)
    save_json(os.path.join(out, "candidates.json"), data)
    with open(os.path.join(out, "batches-new.txt"), "w") as fh:
        fh.write("\n".join(files) + ("\n" if files else ""))
    say("%d batch%s for the models" % (len(files), "" if len(files) == 1 else "es"))


# ---------------------------------------------------------------------------
# render

def read_cards(out):
    cards = {}
    for path in sorted(glob.glob(os.path.join(out, "cards-*.txt"))):
        text = open(path, encoding="utf-8", errors="replace").read().strip()
        objs = []
        try:
            data = json.loads(text)
            objs = data if isinstance(data, list) else [data]
        except ValueError:
            for line in text.splitlines():
                m = re.search(r"\{.*\}", line)
                if not m:
                    continue
                try:
                    objs.append(json.loads(m.group(0)))
                except ValueError:
                    continue
        for o in objs:
            if isinstance(o, dict) and o.get("id"):
                cards[str(o["id"]).strip()] = o
    return cards


def uk_pence(q, payout=None):
    """London cards compare prices in pence. Converts a quote that arrived in pounds, and says so."""
    try:
        import calc
        p = float(q.get("price"))
    except Exception:
        return q
    src = (str(q.get("source") or "") + " " + str(q.get("note") or "")).upper()
    unit = str(q.get("currency") or "").upper()
    pounds = unit == "GBP" or ("GBP" in src and "PENCE" not in src and "GBX" not in src)
    pay = calc.num(payout)
    if not pounds and pay and 0 < p < pay / 20.0:
        pounds = True  # a price this far below the payout is almost certainly in pounds
    if pounds:
        return dict(q, price=round(p * 100.0, 4), source=(q.get("source") or "IBKR") + ", converted from pounds to pence")
    return q


def card_calc(rec, prices_all):
    """Exact spread and return per year for a card, from its fields and the freshest price."""
    try:
        import calc
    except Exception:
        return {}
    c = rec.get("card") or {}
    is_uk = str(rec.get("category") or "").startswith("uk")
    tgt = (rec.get("ticker") or c.get("ticker") or rec.get("id") or "").upper()
    alt = (c.get("target_ticker") or "").upper().strip()
    if alt and alt != tgt:
        if not prices_all.get(alt):
            return {"note": "Priced on the buyer's shares, so the spread needs a refresh with ./run.sh prices"}
        tgt = alt
        rec = dict(rec, quote=prices_all[alt])
    terms = {"structure": c.get("structure"), "target_ticker": tgt, "currency": "GBX" if is_uk else "USD",
             "cash_per_share": c.get("cash_per_share"), "stock_ratio": c.get("stock_ratio"),
             "acquirer_ticker": c.get("acquirer_ticker") or "", "expected_close": c.get("expected_close"),
             "costs_pct": c.get("costs_pct") if is_uk else 0, "trust_per_share": c.get("trust_per_share"),
             "redemption_date": c.get("expected_close"),
             "proceeds_may_be_withheld": c.get("proceeds_may_be_withheld"),
             "otc": is_otc(rec)}
    if c.get("cvr_max"):
        terms["cvr"] = {"min_payout": c.get("cvr_min"), "max_payout": c.get("cvr_max"),
                        "earliest_payment": c.get("cvr_payment_date")}
    prices = {}
    q = prices_all.get(tgt) or rec.get("quote")
    if q and is_uk:
        q = uk_pence(q, c.get("cash_per_share"))
    if q:
        prices[tgt] = q
    acq = (terms["acquirer_ticker"] or "").upper()
    if acq and prices_all.get(acq):
        prices[acq] = prices_all[acq]
    if not prices.get(tgt):
        return {}
    tp, tf = calc.num(c.get("tender_price")), calc.num(c.get("tender_fraction"))
    if tp and tf and 0 < tf <= 1:
        terms["structure"] = "partial_tender"
        terms["cash_per_share"] = None
        terms["tender"] = {"price": tp, "shares_sought": tf * 1000.0, "shares_outstanding": 1000.0, "shares_held_by_bidder": 0,
                           "expiry": c.get("expected_close"), "back_end_prices": {"today's price": calc.num(prices[tgt].get("price"))}}
    res, warn = calc.compute(terms, prices)
    tn = res.get("tender")
    if tn and tn.get("rows"):
        cur_ = terms["currency"]
        r_all, r_half = tn["rows"][0], tn["rows"][2]
        out_t = {"price_text": "%s (%s)" % (calc.fmt(res["price"], cur_), res["price_source"]),
                 "spread_text": "%s if every holder tenders (%s of your shares bought), %s if half do, with the rest kept at today's price" % (
                     calc.pct(r_all["results"][0]["return"]), calc.pct(r_all["accepted"]), calc.pct(r_half["results"][0]["return"]))}
        if r_all["results"][0].get("per_year") is not None:
            out_t["per_year"] = r_all["results"][0]["per_year"]
            out_t["per_year_text"] = "%s a year if every holder tenders" % calc.pct(r_all["results"][0]["per_year"])
        return out_t
    cur = terms["currency"]
    out = {"price_text": "%s (%s)" % (calc.fmt(res["price"], cur), res["price_source"])}
    if res.get("spread_pct") is not None and res["spread_pct"] < -0.25 and not res.get("cvr"):
        return {"note": "The payout looks more than 25% below the price, which usually means the inputs are wrong, so check the card"}
    if res.get("spread_pct") is not None and res["spread_pct"] > 1.0 and not res.get("cvr"):
        return {"note": "The payout looks more than double the price, which usually means pounds and pence were mixed up or the inputs are wrong, so check the card"}
    for sc in res.get("scenarios") or []:
        if sc.get("days") is not None and sc["days"] < 14:
            sc["per_year"] = None
    if res.get("spread_pct") is not None:
        out["spread_text"] = "%s a share, %s%s" % (calc.fmt(res["spread"], cur), calc.pct(res["spread_pct"]),
                                                  " after stamp duty" if (is_uk and res.get("costs_pct")) else "")
        if res.get("cvr"):
            out["spread_text"] += " before the CVR"
    if res.get("scenarios") and res["scenarios"][0].get("per_year") is not None:
        s0 = res["scenarios"][0]
        out["per_year"] = s0["per_year"]
        out["per_year_text"] = "%s a year to %s (%d days)" % (calc.pct(s0["per_year"]), s0["date"], s0["days"])
    if res.get("spac"):
        sp = res["spac"]
        out["spread_text"] = "%s below the trust value of %s" % (calc.pct(sp["return"]), calc.fmt(sp["trust"], cur))
        if sp.get("per_year") is not None:
            out["per_year"] = sp["per_year"]
            out["per_year_text"] = "%s a year to %s" % (calc.pct(sp["per_year"]), sp["date"])
    if res.get("withheld_case"):
        if res.get("spac") and res["spac"].get("return_withheld") is not None:
            out["withheld_text"] = "%s if the redemption counts as a dividend" % calc.pct(res["spac"]["return_withheld"])
        elif res.get("tender") and res["tender"].get("odd_lot_return_withheld") is not None:
            out["withheld_text"] = "%s on an odd lot if the payment counts as a dividend" % calc.pct(res["tender"]["odd_lot_return_withheld"])
        else:
            out["withheld_text"] = "US tax may be withheld from the whole payment if it counts as a dividend"
    if res.get("cvr"):
        rows = res["cvr"]["rows"]
        out["cvr_text"] = "; ".join("%s %s" % (r["label"], calc.pct(r["return"])) for r in rows)
    if warn and "spread_text" not in out:
        out["note"] = warn[0]
    return out


def is_otc(rec):
    ex = (rec.get("exchange") or "").upper()
    return bool(ex) and all(e.strip() == "OTC" for e in ex.split(","))


def rank_year(rec):
    py = (rec.get("calc") or {}).get("per_year")
    return py * 100 if py is not None else annual_of(rec.get("card") or {})


def annual_of(card):
    try:
        return float(card.get("annualized_pct"))
    except (TypeError, ValueError):
        return -1e9


def score_of(card):
    try:
        return max(1, min(5, int(round(float(card.get("score", 0))))))
    except (TypeError, ValueError):
        return 0


def cmd_render(out):
    from quality_gate import preflight
    preflight(out)
    data = load_json(os.path.join(out, "candidates.json"), {"new": [], "follow": [], "updates": []})
    cards = read_cards(out)
    state = load_json(STATE, {"seen": {}, "seen_cik_type": {}, "cards": {}})
    state.setdefault("cards", {})
    date = os.path.basename(out.rstrip("/"))
    good, low, unread = [], [], []
    for rec in data["new"]:
        card = cards.get(rec.get("id", ""))
        if card:
            rec["card"] = card
            state["cards"]["%s|%s" % (rec["cik"], rec["category"])] = {
                "headline": card.get("headline", ""), "score": score_of(card), "date": rec["found"], "id": rec["id"]}
            (good if score_of(card) >= 3 else low).append(rec)
        else:
            unread.append(rec)
    def deal_key(r):
        name = re.sub(r"[^a-z0-9]", "", ((r["card"].get("company") or r["company"]) or "").lower())
        name = re.sub(r"(incorporated|inc|corporation|corp|plc|ltd|limited|holdings|group|co)$", "", name)
        return (name, r["card"].get("type") or r["category"])
    merged, seen_keys = [], {}
    for r in sorted(good + low, key=lambda r: -score_of(r["card"])):
        key = deal_key(r)
        if key in seen_keys:
            seen_keys[key].setdefault("also", []).append(r["id"])
            continue
        seen_keys[key] = r
        merged.append(r)
    good = [r for r in merged if score_of(r["card"]) >= 3]
    low = [r for r in merged if score_of(r["card"]) < 3]
    prices_all = load_json(os.path.join(out, "prices.json"), {})
    for rec in good + low:
        rec["calc"] = card_calc(rec, prices_all)
    good.sort(key=lambda r: (-score_of(r["card"]), -rank_year(r), r["priority"]))
    low.sort(key=lambda r: (-score_of(r["card"]), -rank_year(r), r["priority"]))
    save_json(STATE, state)

    uk = load_json(os.path.join(out, "uk.json"), {"new": [], "departed": [], "table_date": ""})
    uk_good, uk_low, uk_unread = [], [], []
    for rec in uk["new"]:
        card = cards.get(rec.get("id", ""))
        if card:
            rec["card"] = card
            rec.setdefault("ticker", card.get("ticker") or "")
            rec["priority"] = 5
            (uk_good if score_of(card) >= 3 else uk_low).append(rec)
        else:
            uk_unread.append(rec)
    for lst in (uk_good, uk_low):
        for rec in lst:
            rec["calc"] = card_calc(rec, prices_all)
        lst.sort(key=lambda r: (-score_of(r["card"]), -rank_year(r), r["company"]))
    uk_view = {"good": uk_good, "low": uk_low, "unread": uk_unread, "departed": uk.get("departed", []),
               "table_date": uk.get("table_date", "")}

    md = ["# Special situations, %s" % date, ""]
    if data["updates"]:
        md += ["## Updates on deals you track", ""]
        for u in data["updates"]:
            md.append("- %s. %s%s filed %s. %s" % (u["deal"], u["form"], (" " + u["desc"].lower()) if u["desc"] else "", u["date"],
                                                    ("Saved to its filings folder. Run ./run.sh %s update." % u["deal"]) if u["saved"] else ""))
        md.append("")
    md += ["## New situations", ""]
    for r in good:
        c = r["card"]
        md += ["### %s (%s), %s, score %d of 5" % (r["company"], r["ticker"], c.get("type") or r["category"], score_of(c)),
               "", c.get("headline", ""), ""]
        for label, key in (("How the money is made", "how_money"), ("For you", "fits_investor"), ("Terms", "terms"),
                           ("Key dates", "key_dates"), ("Spread", "spread"), ("Per year", "annualized"),
                           ("Odd-lot priority", "odd_lot"), ("Why it may be mispriced", "why_mispriced"),
                           ("Watch out for", "red_flags")):
            if c.get(key):
                md.append("- %s. %s" % (label, c[key]))
        for x in r.get("related") or []:
            md.append("- Related filing, %s. %s" % (x["form"], x["index_url"]))
        done = report_links().get(r["id"])
        md += ["- Filing. %s" % r["index_url"],
               ("- Full report in deals/%s/out/viewer.html" % done) if done else
               "- To start a full report, run `./run.sh promote %s`" % r["id"], ""]
    if not good:
        md += ["Nothing new scored 3 or higher.", ""]
    if low:
        md += ["## Probably not worth your time", ""]
        md += ["- %s (%s), score %d. %s" % (r["company"], r["ticker"], score_of(r["card"]), r["card"].get("headline", ""))
               for r in low]
        md.append("")
    if unread:
        md += ["## Not reviewed", ""]
        md += ["- %s (%s), %s. %s" % (r["company"], r["ticker"], r["form"], r["index_url"]) for r in unread]
        md.append("")
    if data["follow"]:
        md += ["## New filings on earlier finds", ""]
        md += ["- %s (%s), %s. %s" % (r["company"], r["ticker"], r["form"], r["index_url"]) for r in data["follow"]]
        md.append("")
    if uk_good or uk_low or uk_unread or uk_view["departed"]:
        md += ["## UK situations", ""]
        for r in uk_good:
            c = r["card"]
            md += ["### %s (%s), %s, score %d of 5" % (r["company"], c.get("ticker") or "no ticker", c.get("stage") or r["stage"],
                                                     score_of(c)), "", c.get("headline", ""), ""]
            for label, key in (("How the money is made", "how_money"), ("For you", "fits_investor"), ("Terms", "terms"),
                               ("Key dates", "key_dates"), ("Spread", "spread"), ("Per year", "annualized"),
                               ("Watch out for", "red_flags"), ("Source", "source")):
                if c.get(key):
                    md.append("- %s. %s" % (label, c[key]))
            md.append("")
        if uk_low:
            md += ["- %s, score %d. %s" % (r["company"], score_of(r["card"]), r["card"].get("headline", "")) for r in uk_low]
            md.append("")
        if uk_view["departed"]:
            md += ["No longer in an offer period since the last run. %s" % ", ".join(uk_view["departed"]), ""]
    with open(os.path.join(out, "shortlist.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    page = render_html(date, data, good, low, unread, uk_view, [out])
    with open(os.path.join(out, "shortlist.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    with open(os.path.join(FINDER, "latest.html"), "w", encoding="utf-8") as fh:
        fh.write(page.replace('href="../../deals/', 'href="../deals/'))
    say("shortlist   %s (%d worth a look, %d low, %d not reviewed)" % (
        os.path.relpath(os.path.join(out, "shortlist.html"), KIT), len(good), len(low), len(unread)))


def esc(s):
    return html.escape(str(s or ""))


def report_links():
    """Map a card's ID to the viewer of the deal made from it."""
    links = {}
    for path in glob.glob(os.path.join(KIT, "deals", "*", "deal.json")):
        d = load_json(path, {})
        name = os.path.basename(os.path.dirname(path))
        if d.get("source") and os.path.exists(os.path.join(KIT, "deals", name, "out", "viewer.html")):
            links[d["source"]] = name
    return links


def render_html(date, data, good, low, unread, uk_view=None, out_dir_for_events=None):
    links = report_links()
    uk_view = uk_view or {"good": [], "low": [], "unread": [], "departed": [], "table_date": ""}

    def card_html(r):
        c = r["card"]
        sc = score_of(c)
        dots = "".join('<span class="dot%s"></span>' % (" on" if i < sc else "") for i in range(5))
        rows = ""
        k = r.get("calc") or {}
        skip = set(["spread", "annualized"]) if k.get("spread_text") else set()
        if k.get("spread_text"):
            rows += "<dt>Spread, calculated</dt><dd>%s at %s</dd>" % (esc(k["spread_text"]), esc(k.get("price_text", "")))
        if k.get("per_year_text"):
            rows += "<dt>Per year, calculated</dt><dd>%s</dd>" % esc(k["per_year_text"])
        if k.get("cvr_text"):
            rows += "<dt>With the CVR</dt><dd>%s</dd>" % esc(k["cvr_text"])
        if k.get("note"):
            rows += "<dt>Calculator</dt><dd>%s</dd>" % esc(k["note"])
        if k.get("withheld_text"):
            rows += "<dt>If US tax is withheld</dt><dd>%s</dd>" % esc(k["withheld_text"])
        if r.get("also"):
            rows += "<dt>Same deal</dt><dd>Also found in %s</dd>" % esc(", ".join(r["also"]))
        if is_otc(r):
            rows += "<dt>Exchange</dt><dd>Trades over the counter, which generally can't be held in an ISA</dd>"
        for label, key in (("How the money is made", "how_money"), ("For you", "fits_investor"), ("Terms", "terms"),
                           ("Key dates", "key_dates"), ("Spread", "spread"), ("Per year", "annualized"),
                           ("Odd-lot priority", "odd_lot"), ("Why it may be mispriced", "why_mispriced"),
                           ("Watch out for", "red_flags")):
            if c.get(key) and key not in skip:
                rows += "<dt>%s</dt><dd>%s</dd>" % (label, esc(c[key]))
        is_uk = str(r.get("category") or "").startswith("uk")
        rel = r.get("related") or []
        if rel:
            rows += "<dt>Related filings</dt><dd>%s</dd>" % ", ".join(
                '<a href="%s" rel="noopener">%s</a>' % (esc(x["index_url"]), esc(x["form"])) for x in rel)
        q = r.get("quote")
        qline = '<p class="quote">Last price %s</p>' % esc(quote_text(q)) if q else ""
        if r.get("market_cap_gbp"):
            small = r["market_cap_gbp"] < 250e6
            capv = r["market_cap_gbp"]
            capt = ("£%.1f billion" % (capv / 1e9)) if capv >= 1e9 else ("£%.0f million" % (capv / 1e6))
            qline += '<p class="quote">Market cap about %s%s</p>' % (capt, ' <span class="small">small company</span>' if small else "")
        if r.get("market_cap"):
            small = r["market_cap"] < 300e6
            qline += '<p class="quote">Market cap about %s%s</p>' % (esc(money(r["market_cap"])),
                                                                 ' <span class="small">small company</span>' if small else "")
        return ('<article class="card"><header><div class="who"><span class="tick">%s</span> %s</div>'
                '<span class="chip">%s</span></header><p class="head">%s</p>%s<dl>%s</dl>'
                '<div class="scoreline"><span class="dots" aria-hidden="true">%s</span>'
                '<span>Score %d of 5. %s</span></div>'
                '<div class="actions">%s<a href="%s" rel="noopener">Open the source</a>%s</div>'
                '</article>') % (esc(r.get("ticker") or c.get("ticker") or ("UK" if is_uk else "")),
                                 esc(c.get("company") or r["company"]),
                                 esc(("UK, " + (c.get("stage") or r.get("stage", ""))) if is_uk else (c.get("type") or r["category"])),
                                 esc(c.get("headline")), qline, rows, dots, sc, esc(c.get("score_reason")),
                                 ('<a class="report" href="../../deals/%s/out/viewer.html">Open the full report</a>' % esc(links[r["id"]]))
                                 if r["id"] in links else "",
                                 esc(c.get("source") or "https://www.thetakeoverpanel.org.uk/disclosure/disclosure-table") if is_uk
                                 else esc(r["index_url"]),
                                 "" if r["id"] in links else
                                 '<code>./run.sh promote %s</code><button type="button" class="copy" data-cmd="./run.sh promote %s">Copy</button>'
                                 % (esc(r["id"]), esc(r["id"])))

    parts = []
    if data["updates"]:
        items = "".join('<li><b>%s</b>. %s%s, filed %s. <a href="%s" rel="noopener">Filing</a>%s</li>' % (
            esc(u["deal"]), esc(u["form"]), (", " + esc(u["desc"].lower())) if u["desc"] else "", esc(u["date"]), esc(u["index_url"]),
            (" Saved to its filings folder. Run ./run.sh %s update to update the report." % esc(u["deal"])) if u["saved"] else "")
            for u in data["updates"])
        parts.append('<section><h2>Updates on deals you track</h2><ul class="plain">%s</ul></section>' % items)
    parts.append('<section><h2>New situations</h2>%s</section>' % (
        "".join(card_html(r) for r in good) or '<p class="empty">Nothing new scored 3 or higher this time.</p>'))
    if low:
        items = "".join('<li><b>%s</b> (%s), score %d. %s</li>' % (
            esc(r["company"]), esc(r["ticker"]), score_of(r["card"]), esc(r["card"].get("headline"))) for r in low)
        parts.append('<details><summary>Probably not worth your time (%d)</summary><ul class="plain">%s</ul></details>'
                     % (len(low), items))
    if unread:
        items = "".join('<li><b>%s</b> (%s), %s. %s <a href="%s" rel="noopener">Filing</a></li>' % (
            esc(r["company"]), esc(r["ticker"]), esc(r["form"]), esc(r.get("untriaged", "")),
            esc(r["index_url"])) for r in unread)
        parts.append('<details><summary>Not reviewed (%d)</summary><ul class="plain">%s</ul></details>' % (len(unread), items))
    if data["follow"]:
        items = "".join('<li><b>%s</b> (%s), %s. %s <a href="%s" rel="noopener">Filing</a></li>' % (
            esc(r["company"]), esc(r["ticker"]), esc(r["form"]),
            ("Earlier card said " + esc(r["earlier"].get("headline"))) if r.get("earlier", {}).get("headline") else "",
            esc(r["index_url"])) for r in data["follow"])
        parts.append('<details><summary>New filings on earlier finds (%d)</summary><ul class="plain">%s</ul></details>'
                     % (len(data["follow"]), items))
    if uk_view["good"] or uk_view["low"] or uk_view["unread"] or uk_view["departed"]:
        intro = ('<p class="meta">From the Takeover Panel list dated %s. Cards are written from official announcements, '
                 'so check the source before acting.</p>' % esc(uk_view["table_date"] or "today"))
        parts.append('<section><h2>UK situations</h2>%s%s</section>' % (
            intro, "".join(card_html(r) for r in uk_view["good"]) or '<p class="empty">No UK situation scored 3 or higher.</p>'))
        if uk_view["low"]:
            items = "".join('<li><b>%s</b>, score %d. %s</li>' % (esc(r["company"]), score_of(r["card"]),
                                                               esc(r["card"].get("headline"))) for r in uk_view["low"])
            parts.append('<details><summary>UK, probably not worth your time (%d)</summary><ul class="plain">%s</ul></details>'
                         % (len(uk_view["low"]), items))
        if uk_view["unread"]:
            items = "".join('<li><b>%s</b>. %s %s</li>' % (esc(r["company"]), esc(r["stage"]), esc(r.get("untriaged", "")))
                            for r in uk_view["unread"])
            parts.append('<details><summary>UK, not reviewed (%d)</summary><ul class="plain">%s</ul></details>'
                         % (len(uk_view["unread"]), items))
        if uk_view["departed"]:
            parts.append('<details><summary>UK, no longer in an offer period (%d)</summary><p>%s</p></details>'
                         % (len(uk_view["departed"]), esc(", ".join(uk_view["departed"]))))
    ev = load_json(os.path.join(out_dir_for_events[0], "uk_events.json"), {"new": []}) if out_dir_for_events else {"new": []}
    ev_good = [e for e in ev["new"] if score_of(e.get("card") or {}) >= 3]
    ev_low = [e for e in ev["new"] if score_of(e.get("card") or {}) < 3]
    prices_ev = load_json(os.path.join(out_dir_for_events[0], "prices.json"), {}) if out_dir_for_events else {}
    for e in ev["new"]:
        e["calc"] = card_calc(e, prices_ev)
    ev_good.sort(key=lambda r: (-score_of(r["card"]), -rank_year(r), r["company"]))
    if ev_good or ev_low:
        parts.append('<section><h2>UK events</h2><p class="meta">Tenders, wind-downs, liquidations, returns of capital and demergers '
                     'from recent announcements. Check the source before acting.</p>%s</section>' % (
                         "".join(card_html(r) for r in ev_good) or '<p class="empty">No UK event scored 3 or higher.</p>'))
        if ev_low:
            items = "".join('<li><b>%s</b>, score %d. %s</li>' % (esc(r["company"]), score_of(r["card"]), esc(r["card"].get("headline")))
                            for r in ev_low)
            parts.append('<details><summary>UK events, probably not worth your time (%d)</summary><ul class="plain">%s</ul></details>'
                         % (len(ev_low), items))
    ins = load_json(os.path.join(out_dir_for_events[0], "insiders.json"), {}) if out_dir_for_events else {}
    if ins.get("companies"):
        rows_i = "".join('<tr><td><a href="%s" rel="noopener">%s</a></td><td>%s</td><td>%d</td><td>%s</td><td>$%s</td><td>%s</td></tr>' % (
            esc(g["filings"][0]), esc(g["company"]), esc(g["ticker"]), len(g["buyers"]),
            esc("; ".join(b["name"] + (" (%s)" % b["role"] if b["role"] else "") for b in g["buyers"][:3])),
            "{:,.0f}".format(g["value"]), esc(money(g.get("market_cap")))) for g in ins["companies"][:25])
        parts.append('<section><h2>Insider buying in smaller companies</h2><p class="meta">Open-market purchases by directors and '
                     'officers over the last %d days. A starting point for research, not a signal on its own.</p>'
                     '<div class="scroll"><table class="ins"><tr><th>Company</th><th>Ticker</th><th>Buyers</th><th>Who</th>'
                     '<th>Bought</th><th>Market cap</th></tr>%s</table></div></section>' % (ins.get("days", 0), rows_i))
    meta = "%d worth a look, %d low, %d not reviewed" % (len(good), len(low), len(unread))
    if ev_good or ev_low:
        meta += ", plus %d UK event%s" % (len(ev_good) + len(ev_low), "" if len(ev_good) + len(ev_low) == 1 else "s")
    if uk_view["good"] or uk_view["low"]:
        meta += ", plus %d UK" % (len(uk_view["good"]) + len(uk_view["low"]))
    return SHORTLIST.replace("%%DATE%%", esc(date)).replace("%%META%%", esc(meta)).replace("%%BODY%%", "".join(parts))


SHORTLIST = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Special situations, %%DATE%%</title>
<style>
:root{--paper:#EEF1F4;--sheet:#FFFFFF;--ink:#18202B;--ink2:#55606E;--rule:#D6DCE3;--flag:#0E6D76;--flagbg:#D9EEEF;--flagink:#08474D;
--serif:Charter,"Bitstream Charter","Sitka Text",Cambria,Georgia,serif;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#0E1217;--sheet:#161C23;--ink:#E3E8EE;--ink2:#9AA5B2;--rule:#29313B;--flag:#4CC0C9;--flagbg:#113A3F;--flagink:#A7E6EA;color-scheme:dark}}
:root[data-theme="dark"]{--paper:#0E1217;--sheet:#161C23;--ink:#E3E8EE;--ink2:#9AA5B2;--rule:#29313B;--flag:#4CC0C9;--flagbg:#113A3F;--flagink:#A7E6EA;color-scheme:dark}
*,*::before,*::after{box-sizing:inherit}
html{scroll-padding-top:env(safe-area-inset-top,0px)}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 var(--sans)}
main{max-width:46rem;margin:0 auto;padding:1.2rem .9rem 3rem}
h1{font-size:1.3rem;margin:.2rem 0 .1rem;letter-spacing:-.01em}
.meta{color:var(--ink2);font-size:.85rem;margin:0 0 1.2rem}
h2{font-size:1rem;margin:1.6rem 0 .7rem;color:var(--ink2)}
.card{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:1rem 1.05rem;margin:0 0 .9rem}
.card header{display:flex;justify-content:space-between;align-items:flex-start;gap:.6rem}
.who{font-weight:650;font-size:.95rem}
.tick{display:inline-block;font:700 .78rem/1.2 var(--sans);padding:.2rem .7rem .2rem .45rem;background:var(--flagbg);color:var(--flagink);clip-path:polygon(0 0,100% 0,calc(100% - 6px) 50%,100% 100%,0 100%);margin-right:.25rem;vertical-align:.1em}
.chip{flex:none;font-size:.75rem;color:var(--ink2);border:1px solid var(--rule);border-radius:999px;padding:.15rem .55rem}
.head{font:1.05rem/1.45 var(--serif);margin:.6rem 0 .4rem}
.quote{font-size:.8rem;color:var(--ink2);margin:0 0 .4rem}
.scroll{overflow-x:auto}
table.ins{border-collapse:collapse;font-size:.8rem;width:100%}
table.ins th,table.ins td{text-align:left;padding:.35rem .5rem;border-bottom:1px solid var(--rule);vertical-align:top}
.small{font-weight:650;color:var(--flagink);background:var(--flagbg);border-radius:999px;padding:.05rem .45rem;margin-left:.3rem}
dl{margin:.4rem 0 .6rem}dt{font-size:.78rem;font-weight:650;color:var(--ink2);margin-top:.5rem}dd{margin:.1rem 0 0;font-size:.92rem}
.scoreline{display:flex;align-items:center;gap:.6rem;font-size:.84rem;color:var(--ink2);border-top:1px solid var(--rule);padding-top:.6rem}
.dots{display:inline-flex;gap:3px;flex:none}.dot{width:9px;height:9px;border-radius:2px;background:var(--rule)}.dot.on{background:var(--flag)}
.actions{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem;margin-top:.6rem;font-size:.85rem}
.actions a{color:var(--flag);font-weight:600}
.actions a.report{color:var(--sheet);background:var(--flag);padding:.3rem .6rem;border-radius:6px;text-decoration:none}
.actions code{font:.78rem var(--mono);background:var(--paper);padding:.25rem .45rem;border-radius:5px;overflow-x:auto;max-width:100%}
button.copy{font:600 .78rem var(--sans);color:var(--ink);background:transparent;border:1px solid var(--rule);border-radius:6px;padding:.25rem .55rem;cursor:pointer}
details{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:.7rem 1rem;margin:.9rem 0}
summary{cursor:pointer;font-weight:650;font-size:.92rem}
ul.plain{margin:.6rem 0 0;padding-left:1.1rem;font-size:.9rem}ul.plain li{margin:.35rem 0}
ul.plain a,section a{color:var(--flag)}
.empty{color:var(--ink2)}
:focus-visible{outline:2px solid var(--flag);outline-offset:2px}
</style></head>
<body><main>
<h1>Special situations, %%DATE%%</h1>
<p class="meta">%%META%%. Scores come from a model reading the filing excerpt, so treat them as a reading order, not a verdict.</p>
%%BODY%%
</main>
<script>
document.addEventListener("click",function(e){var b=e.target.closest("button.copy");if(!b)return;var t=b.getAttribute("data-cmd");
function done(){b.textContent="Copied";setTimeout(function(){b.textContent="Copy"},1500)}
if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(done,function(){})}else{var r=document.createRange();r.selectNodeContents(b.previousElementSibling);var s=getSelection();s.removeAllRanges();s.addRange(r)}});
</script>
</body></html>
"""


# ---------------------------------------------------------------------------
# promote and track

def find_candidate(cid):
    for path in sorted(glob.glob(os.path.join(FINDER, "*", "candidates.json")), reverse=True):
        data = load_json(path, {})
        for r in data.get("new", []) + data.get("follow", []):
            if r.get("id", "").lower() == cid.lower():
                return r
    return None


def new_deal(name):
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", name):
        sys.exit("Use a plain deal name with letters, numbers, dots, dashes or underscores.")
    deal = os.path.join(KIT, "deals", name)
    if os.path.exists(deal):
        sys.exit("deals/%s already exists." % name)
    os.makedirs(os.path.join(deal, "filings"))
    shutil.copyfile(os.path.join(KIT, "templates", "market.md"), os.path.join(deal, "market.md"))
    return deal


def find_uk(cid):
    for path in sorted(glob.glob(os.path.join(FINDER, "*", "uk.json")), reverse=True):
        data = load_json(path, {})
        for c in data.get("new", []):
            if c.get("id", "").lower() == cid.lower():
                return c, read_cards(os.path.dirname(path)).get(c["id"], {})
    for path in sorted(glob.glob(os.path.join(FINDER, "*", "uk_events.json")), reverse=True):
        for c in load_json(path, {}).get("new", []):
            if c.get("id", "").lower() == cid.lower():
                return c, c.get("card") or {}
    return None, None


def remember_promoted(name):
    with open(os.path.join(KIT, ".last_promoted"), "w") as fh:
        fh.write(name + "\n")


def cmd_promote_uk(cid, name=None):
    c, card = find_uk(cid)
    if not c:
        sys.exit("No UK situation called %s. The IDs are on the shortlist page." % cid)
    ticker = (card.get("ticker") or c.get("ticker") or "").upper()
    base = c["company"].lower().replace(" plc", "").replace(" limited", "")
    name = name or re.sub(r"[^a-z0-9]+", "", base)[:14]
    deal = new_deal(name)
    save_json(os.path.join(deal, "deal.json"), {
        "market": "UK", "company": c["company"], "ticker": ticker, "isin": c.get("isin", ""),
        "category": c.get("category") or "uk offer",
        "currency": "GBX", "source": c["id"], "roles": {ticker: "target"} if ticker else {},
        "stage": card.get("stage") or c.get("stage", ""), "source_url": card.get("source", ""),
        "bidders": c.get("bidders", ""), "deadline": c.get("deadline", ""),
        "last_checked": datetime.date.today().isoformat()})
    save_json(os.path.join(deal, "card.json"), card)
    q = c.get("quote")
    if q and ticker:
        mpath = os.path.join(deal, "market.md")
        text = open(mpath, encoding="utf-8").read()
        text = text.replace("| | | | |\n| | | | |\n", "| %s | %s | %s | %s (%s) |\n| | | | |\n" % (
            ticker, "target", q["price"], q.get("date", ""), q.get("source", "")), 1)
        open(mpath, "w", encoding="utf-8").write(text)
    remember_promoted(name)
    say("created deals/%s for %s. Its documents come from official websites, not EDGAR" % (name, c["company"]))


def cmd_promote_bio(cid, name=None):
    need_contact()
    row = None
    for path in sorted(glob.glob(os.path.join(FINDER, "*", "biotech.json")), reverse=True):
        row = next((r for r in load_json(path, {"rows": []})["rows"] if r["id"].upper() == cid.upper()), None)
        if row:
            break
    if not row:
        sys.exit("No biotech decision called %s. The IDs are on the biotech page." % cid)
    name = name or row["ticker"].lower()
    deal = new_deal(name)
    keep = dict((k, row.get(k)) for k in ("decision_date", "approx", "date_text", "context", "other_dates", "cash", "cash_date",
                                         "burn_month", "runway_months", "shares", "price", "market_cap", "cash_per_share", "card"))
    save_json(os.path.join(deal, "deal.json"), {
        "cik": row["cik"], "ticker": row["ticker"], "company": row["company"], "category": "biotech decision",
        "related_ciks": [], "source": row["id"], "roles": {row["ticker"]: "listed company"}, "have": [],
        "last_checked": datetime.date.today().isoformat(), "biotech": keep})
    if row.get("price"):
        mpath = os.path.join(deal, "market.md")
        text = open(mpath, encoding="utf-8").read()
        text = text.replace("| | | | |\n| | | | |\n", "| %s | %s | %s | %s (%s) |\n| | | | |\n" % (
            row["ticker"], "Listed company", row["price"], row.get("price_date", ""), "IBKR"), 1)
        open(mpath, "w", encoding="utf-8").write(text)
    import gather as gather_mod
    gather_mod.gather(deal)
    remember_promoted(name)
    say("created deals/%s for the FDA decision due %s" % (name, row["decision_date"]))
    say("next, run ./run.sh %s biotech" % name)


def cmd_promote_cat(cid, name=None):
    e = next((v for v in load_json(os.path.join(FINDER, "catalysts.json"), {"items": {}})["items"].values()
              if v["id"].upper() == cid.upper()), None)
    if not e:
        sys.exit("No catalyst called %s. The IDs are on the catalysts page." % cid)
    ticker = (e.get("ticker") or "").upper()
    base = re.sub(r"\b(plc|limited|ltd|ag|se|nv|sa)\b", "", e["company"].lower())
    name = name or re.sub(r"[^a-z0-9]+", "", base)[:14]
    us = bool(re.search(r"nasdaq|nyse|\bus\b", e.get("market") or "", re.I))
    deal = new_deal(name)
    info = {"company": e["company"], "ticker": ticker, "isin": e.get("isin", ""), "category": "catalyst, %s" % e.get("type", "other"),
            "source": e["id"], "roles": {ticker: "listed company"} if ticker else {}, "catalyst": e,
            "last_checked": datetime.date.today().isoformat()}
    if us:
        need_contact()
        cik, _ = resolve(ticker)
        info.update({"cik": cik, "related_ciks": [], "have": []})
    else:
        london = any(w in (e.get("market") or "").lower() for w in ("main market", "aim", "london", "lse"))
        info.update({"market": "UK", "currency": "GBX" if london else "", "source_url": (e.get("sources") or [""])[0]})
    save_json(os.path.join(deal, "deal.json"), info)
    if e.get("price") and ticker:
        mpath = os.path.join(deal, "market.md")
        text = open(mpath, encoding="utf-8").read()
        text = text.replace("| | | | |\n| | | | |\n", "| %s | %s | %s | %s (%s) |\n| | | | |\n" % (
            ticker, "listed company", e["price"], e.get("price_date", ""), "IBKR"), 1)
        open(mpath, "w", encoding="utf-8").write(text)
    if us:
        import gather as gather_mod
        gather_mod.gather(deal)
    remember_promoted(name)
    say("created deals/%s for %s, a %s due %s" % (name, e["company"], e.get("type", "catalyst"), e.get("date", "")))
    say("next, run ./run.sh %s, or ./run.sh %s fundamentals for the value anchor" % (name, name))


def cmd_promote(cid, name=None):
    if cid.upper().startswith(("UK-", "UKE-")):
        return cmd_promote_uk(cid, name)
    if cid.upper().startswith("CAT-"):
        return cmd_promote_cat(cid, name)
    if cid.upper().startswith("BIO-"):
        return cmd_promote_bio(cid, name)
    need_contact()
    rec = find_candidate(cid)
    if not rec:
        sys.exit("No candidate called %s. The IDs are on the shortlist page." % cid)
    name = name or (rec.get("ticker") or rec["cik"]).lower()
    deal = new_deal(name)
    roles = {}
    if rec.get("ticker"):
        roles[rec["ticker"].upper()] = "listed company"
    for o in rec.get("others", []):
        if o.get("tickers"):
            roles.setdefault(o["tickers"][0].upper(), "related company")
    save_json(os.path.join(deal, "deal.json"), {
        "cik": rec["cik"], "ticker": rec.get("ticker"), "company": rec["company"], "category": rec["category"],
        "related_ciks": [o["cik"] for o in rec.get("others", [])], "source": rec["id"], "roles": roles,
        "have": [], "last_checked": datetime.date.today().isoformat()})
    q = rec.get("quote")
    if q:
        mpath = os.path.join(deal, "market.md")
        text = open(mpath, encoding="utf-8").read()
        text = text.replace("| | | | |\n| | | | |\n", "| %s | %s | %s | %s (%s) |\n| | | | |\n" % (
            rec["ticker"], "Listed company", q["price"], q["date"], q["source"]), 1)
        open(mpath, "w", encoding="utf-8").write(text)
    import gather as gather_mod
    gather_mod.gather(deal)
    remember_promoted(name)
    say("created deals/%s. The finder will add this company's new filings each time it runs" % name)
    say("next, run ./run.sh %s" % name)


def resolve(ident):
    """Return (CIK, ticker) for a ticker or a CIK."""
    ident = ident.strip()
    if ident.isdigit():
        return cik10(ident), None
    raw = get("https://www.sec.gov/files/company_tickers.json")
    table = json.loads(raw.decode("utf-8")) if raw else {}
    hit = next((v for v in table.values() if str(v.get("ticker", "")).upper() == ident.upper()), None)
    if not hit:
        sys.exit("Could not find the ticker %s in the SEC's list." % ident)
    return cik10(hit["cik_str"]), hit["ticker"]


def cmd_add_company(name, ident, role=None):
    """Attach another company to a deal, such as the target in a stock-for-stock merger."""
    need_contact()
    deal = os.path.join(KIT, "deals", name)
    if not os.path.isdir(deal):
        sys.exit("There is no deal folder called %s." % name)
    c, ticker = resolve(ident)
    info = company(c)
    ticker = (ticker or (info["tickers"][0] if info["tickers"] else "")).upper()
    path = os.path.join(deal, "deal.json")
    d = load_json(path, {})
    if not d.get("cik"):
        d.update({"cik": c, "ticker": ticker, "company": info["name"], "category": d.get("category") or "merger",
                  "last_checked": datetime.date.today().isoformat()})
    elif c != d["cik"] and c not in d.get("related_ciks", []):
        d.setdefault("related_ciks", []).append(c)
    if ticker:
        roles = d.setdefault("roles", {})
        roles[ticker] = role or roles.get(ticker) or "related company"
    save_json(path, d)
    say("deals/%s now includes %s%s" % (name, info["name"] or c, (" as the " + role) if role else ""))
    import gather as gather_mod
    gather_mod.gather(deal)


def cmd_track(name, ident):
    need_contact()
    deal = os.path.join(KIT, "deals", name)
    if not os.path.isdir(deal):
        sys.exit("There is no deal folder called %s." % name)
    c, ticker = resolve(ident)
    info = company(c)
    path = os.path.join(deal, "deal.json")
    d = load_json(path, {})
    d.update({"cik": c, "ticker": ticker or (info["tickers"][0] if info["tickers"] else None),
              "company": info["name"], "last_checked": datetime.date.today().isoformat()})
    save_json(path, d)
    say("deals/%s now follows %s. New filings will be saved to its filings folder." % (name, info["name"] or c))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "fetch" and args:
        cmd_fetch(args[0], args[1] if len(args) > 1 else None)
    elif cmd == "render" and args:
        cmd_render(args[0])
    elif cmd == "set-quotes" and len(args) == 2:
        cmd_set_quotes(args[0], args[1])
    elif cmd == "fill-quotes" and args:
        cmd_fill_quotes(args[0])
    elif cmd == "batches" and args:
        cmd_batches(args[0])
    elif cmd == "requeue" and args:
        cmd_requeue(args[0])
    elif cmd == "pick" and len(args) == 3:
        cmd_pick(args[0], args[1], args[2])
    elif cmd == "promote" and args:
        cmd_promote(args[0], args[1] if len(args) > 1 else None)
    elif cmd == "track" and len(args) == 2:
        cmd_track(args[0], args[1])
    elif cmd == "add-company" and len(args) in (2, 3):
        cmd_add_company(args[0], args[1], args[2] if len(args) == 3 else None)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
