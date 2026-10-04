#!/usr/bin/env python3
"""Collect the full current set of documents for a deal from EDGAR.

It reads the company's filing history, keeps the forms that matter for the
situation type, and downloads the main document and the key exhibits of each.
For documents that get amended, such as a Form 10 or a merger proxy, only the
latest version of each part is kept, and older copies move to
filings/superseded so the models don't read outdated terms. It also downloads
a few recent filings of the same kind from other companies into the library,
so the document map can tell standard wording from deal-specific wording.

Usage: gather.py DEAL
Needs deals/NAME/deal.json with the company's CIK, which promote and track create.
"""
import datetime
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finder  # noqa: E402
import docmap  # noqa: E402

FAMILY = {"DEFM14A": "proxy", "PREM14A": "proxy", "DEFM14C": "proxy", "PREM14C": "proxy",
          "S-4": "registration", "424B3": "registration", "10-12B": "form10", "10-12G": "form10",
          "SC TO-T": "tender", "SC TO-I": "tender", "SC 14D9": "14d9", "SC 13E3": "13e3",
          "SC 13D": "13d", "8-K": "8k", "10-K": "10k", "10-Q": "10q", "8-A12B": "listing"}
WANT = {
    "merger": {"proxy", "registration", "14d9", "tender", "13e3", "8k", "10k", "10q"},
    "spin-off": {"form10", "8k", "listing", "10k", "10q"},
    "tender offer": {"tender", "14d9", "13e3", "8k", "10k", "10q"},
    "bankruptcy": {"8k", "10k", "10q"},
    "early signal": {"13d", "proxy", "8k", "10k", "10q"},
}
KEEP_EVERY_FILING = {"tender", "14d9", "13d", "8k"}   # amendments and separate events that each add something
EIGHT_K_ITEMS = {"1.01", "1.02", "1.03", "2.01", "2.04", "3.03", "5.01", "5.02", "5.07", "7.01", "8.01"}
PEERS = {
    "merger": [("DEFM14A", '"special meeting"'), ("8-K", '"Agreement and Plan of Merger"')],
    "spin-off": [("10-12B", '"information statement"')],
    "tender offer": [("SC TO-T", '"offer to purchase"'), ("SC TO-I", '"offer to purchase"')],
    "bankruptcy": [("8-K", '"Chapter 11"')],
    "early signal": [("SC 13D", '"purpose of transaction"')],
}
MAX_8K = 12
EIGHT_K_DAYS = 120


def family(form):
    f = finder.norm_form(form)
    base = f[:-2] if f.endswith("/A") else f
    return FAMILY.get(base)


def role(doc, form):
    t = doc["type"].upper().replace(" ", "")
    return t.lower() if t.startswith("EX-") else ""


def main_doc(docs, form):
    """The filing's main document, meaning the one whose type matches the form, or else the first one."""
    f = finder.norm_form(form)
    base = f[:-2] if f.endswith("/A") else f
    for d in docs:
        t = finder.norm_form(d["type"])
        if t == f or t == base or t == base + "/A":
            return d
    return docs[0] if docs and not docs[0]["type"].upper().startswith("EX-") else None


def wanted_exhibit(doc, fam, items):
    t = doc["type"].upper().replace(" ", "")
    if re.match(r"^EX-99(\.|$)", t) or re.match(r"^EX-2(\.|$)", t):
        return True
    if re.match(r"^EX-10(\.|$)", t) and (fam == "form10" or (fam == "8k" and "1.01" in items)):
        return True
    return False


def slug(s, n=40):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:n] or "doc"


def gather(deal_dir, quiet=False):
    info_path = os.path.join(deal_dir, "deal.json")
    d = finder.load_json(info_path, {})
    if not d.get("cik"):
        sys.exit("This deal has no company attached. Run ./run.sh track NAME TICKER first.")
    category = d.get("category") or "merger"
    want = WANT.get(category, WANT["merger"])
    today = datetime.date.today()
    since = d.get("since") or (today - datetime.timedelta(days=365)).isoformat()
    eight_k_since = max(since, (today - datetime.timedelta(days=EIGHT_K_DAYS)).isoformat())
    filings_dir = os.path.join(deal_dir, "filings")
    old_dir = os.path.join(filings_dir, "superseded")
    os.makedirs(filings_dir, exist_ok=True)
    mpath = os.path.join(filings_dir, ".gathered.json")
    manifest = finder.load_json(mpath, {"files": {}})

    ciks = [d["cik"]] + [o for o in d.get("related_ciks", []) if o != d["cik"]]
    tickers = {}
    for c in ciks:
        t = finder.company(c)["tickers"]
        tickers[c] = t[0] if t else c[-6:]
    rows, seen_acc = [], set()
    for c in ciks:
        for r in finder.company(c)["recent"]:
            fam = family(r["form"])
            if not fam or fam not in want or r["date"] < since or r["accession"] in seen_acc:
                continue
            items = set(x.strip() for x in (r.get("items") or "").split(",") if x.strip())
            if fam == "8k" and (not items & EIGHT_K_ITEMS or r["date"] < eight_k_since):
                continue
            seen_acc.add(r["accession"])
            rows.append(dict(r, cik=c, family=fam, items=items))
    rows.sort(key=lambda r: r["date"])
    eight_ks = [r for r in rows if r["family"] == "8k"][-MAX_8K:]
    rows = [r for r in rows if r["family"] != "8k"] + eight_ks
    for fam in ("10k", "10q"):
        latest = []
        for c in ciks:
            latest += [r for r in rows if r["family"] == fam and r["cik"] == c][-1:]
        rows = [r for r in rows if r["family"] != fam] + latest

    # Choose documents. For families that get amended, the latest version of each part wins.
    chosen = {}
    for r in sorted(rows, key=lambda r: r["date"]):
        try:
            docs = finder.filing_docs(r["cik"], r["accession"])
        except Exception:
            docs = []
        if not docs and r.get("doc"):
            folder = "https://www.sec.gov/Archives/edgar/data/%d/%s/" % (int(r["cik"]), r["accession"].replace("-", ""))
            docs = [{"url": folder + r["doc"], "name": r["doc"], "type": r["form"], "desc": r.get("desc") or r["form"]}]
        primary = main_doc(docs, r["form"])
        for doc in docs:
            if doc is primary:
                rl = "main"
            else:
                rl = role(doc, r["form"])
                if not rl or not wanted_exhibit(doc, r["family"], r["items"]):
                    continue
            if r["family"] in KEEP_EVERY_FILING:
                key = "%s|%s|%s" % (r["family"], r["accession"], rl)
            else:
                key = "%s|%s" % (r["family"], rl)
            if r["family"] not in KEEP_EVERY_FILING and r["cik"] != d["cik"]:
                key = "%s|%s" % (key, r["cik"])
            chosen[key] = {"url": doc["url"], "name": doc["name"], "type": doc["type"], "desc": doc["desc"],
                           "form": r["form"], "date": r["date"], "accession": r["accession"],
                           "family": r["family"], "role": rl, "cik": r["cik"]}

    by_url = dict((v["url"], k) for k, v in manifest["files"].items())
    added, superseded = 0, 0
    for key, doc in sorted(chosen.items(), key=lambda kv: kv[1]["date"]):
        if doc["url"] in by_url and os.path.exists(os.path.join(filings_dir, by_url[doc["url"]])):
            continue
        try:
            raw = finder.get(doc["url"])
        except Exception as e:
            finder.say("could not download %s (%s)" % (doc["name"], e))
            continue
        if not raw:
            continue
        ext = os.path.splitext(doc["name"])[1].lower() or ".htm"
        who = "" if doc["cik"] == d["cik"] else "%s_" % slug(tickers.get(doc["cik"], doc["cik"][-6:]), 8)
        fname = "%s%s_%s_%s_%s%s" % (who, doc["family"], doc["date"], slug(doc["role"], 14),
                                     slug(doc["desc"] or doc["name"], 36), ext)
        with open(os.path.join(filings_dir, fname), "wb") as fh:
            fh.write(raw)
        # An older copy of the same part of an amended document is now out of date
        for old_name, meta in list(manifest["files"].items()):
            if meta.get("slot") == key and old_name != fname and os.path.exists(os.path.join(filings_dir, old_name)):
                os.makedirs(old_dir, exist_ok=True)
                shutil.move(os.path.join(filings_dir, old_name), os.path.join(old_dir, old_name))
                meta["superseded"] = doc["date"]
                superseded += 1
        manifest["files"][fname] = dict(doc, slot=key)
        added += 1
    manifest["last_gather"] = today.isoformat()
    finder.save_json(mpath, manifest)
    d["have"] = sorted(set(d.get("have", [])) | seen_acc)[-400:]
    d["last_checked"] = today.isoformat()
    finder.save_json(info_path, d)
    if not quiet or added:
        finder.say("gather      %d document%s added, %d older version%s moved to filings/superseded" % (
            added, "" if added == 1 else "s", superseded, "" if superseded == 1 else "s"))
    learn_peers(category, d["cik"], quiet)
    return added


def learn_peers(category, own_cik, quiet=False):
    """Add a few recent filings of the same kind from other companies to the library."""
    peers_dir = os.path.join(docmap.LIBRARY, "peers")
    os.makedirs(peers_dir, exist_ok=True)
    con = docmap.db()
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=365)).isoformat()
    n = 0
    for form, phrase in PEERS.get(category, []):
        try:
            hits = finder.efts(phrase, start, today.isoformat(), forms=form, limit=100)
        except Exception:
            continue
        taken = set()
        for h in hits:
            src = h.get("_source", {})
            ciks = [finder.cik10(c) for c in src.get("ciks") or []]
            if not ciks or own_cik in ciks or ciks[0] in taken or ":" not in h.get("_id", ""):
                continue
            adsh, fname = h["_id"].split(":", 1)
            sid = "peer:%s:%s" % (ciks[0], adsh)
            if con.execute("SELECT 1 FROM sources WHERE id = ?", (sid,)).fetchone():
                taken.add(ciks[0])
                continue
            url = "https://www.sec.gov/Archives/edgar/data/%d/%s/%s" % (int(ciks[0]), adsh.replace("-", ""), fname)
            try:
                raw = finder.get(url, limit=2500000)
            except Exception:
                continue
            if not raw:
                continue
            text = finder.html_to_text(raw)[:600000]
            with open(os.path.join(peers_dir, "%s_%s.txt" % (ciks[0], adsh)), "w", encoding="utf-8") as fh:
                fh.write(text)
            docmap.learn(con, sid, text, "peer")
            taken.add(ciks[0])
            n += 1
            if len(taken) >= 4:
                break
    con.commit()
    if n:
        finder.say("library     added %d recent filing%s from other companies for comparison" % (n, "" if n == 1 else "s"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    finder.need_contact()
    gather(os.path.abspath(sys.argv[1]))
