#!/usr/bin/env python3
"""Insider buying in smaller companies, from SEC Form 4 filings.

When directors and officers buy their own company's shares on the open market
with their own money, especially several of them at once in a small company,
it has historically been one of the more useful signals that the shares are
cheap. This reads recent Form 4 filings, keeps open-market purchases only,
and groups them by company.

Usage: insiders.py OUTDIR [DAYS]
Writes OUTDIR/insiders.json and OUTDIR/insiders.md.
"""
import datetime
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finder  # noqa: E402

MIN_VALUE = float(os.environ.get("INSIDER_MIN_VALUE", "50000"))
MAX_CAP = float(os.environ.get("INSIDER_MAX_CAP", "2000000000"))
MAX_FILINGS = int(os.environ.get("INSIDER_MAX_FILINGS", "4000"))


def text_of(node, path):
    el = node.find(path)
    if el is None:
        return ""
    v = el.find("value")
    return ((v.text if v is not None else el.text) or "").strip()


def parse_form4(raw):
    m = re.search(rb"<XML>(.*?)</XML>", raw, re.S | re.I)
    body = (m.group(1) if m else raw).strip()
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    issuer = {"cik": finder.cik10(text_of(root, "issuer/issuerCik") or "0"), "name": text_of(root, "issuer/issuerName"),
              "ticker": text_of(root, "issuer/issuerTradingSymbol").upper()}
    owners = []
    for o in root.findall("reportingOwner"):
        rel = o.find("reportingOwnerRelationship")
        role = []
        if rel is not None:
            if text_of(rel, "isDirector") in ("1", "true"):
                role.append("director")
            if text_of(rel, "isOfficer") in ("1", "true"):
                role.append(text_of(rel, "officerTitle") or "officer")
            if text_of(rel, "isTenPercentOwner") in ("1", "true"):
                role.append("10% owner")
        owners.append({"name": text_of(o, "reportingOwnerId/rptOwnerName"), "role": ", ".join(role)})
    buys = []
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        if text_of(t, "transactionCoding/transactionCode") != "P":
            continue
        if text_of(t, "transactionAmounts/transactionAcquiredDisposedCode") != "A":
            continue
        try:
            shares = float(text_of(t, "transactionAmounts/transactionShares") or 0)
            price = float(text_of(t, "transactionAmounts/transactionPricePerShare") or 0)
        except ValueError:
            continue
        if shares > 0 and price > 0:
            buys.append({"shares": shares, "price": price, "date": text_of(t, "transactionDate")})
    return issuer, owners, buys


def main(out, days):
    finder.need_contact()
    os.makedirs(out, exist_ok=True)
    today = datetime.date.today()
    d = today - datetime.timedelta(days=days)
    accs = {}
    while d < today:
        if d.weekday() < 5:
            try:
                rows = finder.daily_index(d) or []
            except Exception as e:
                finder.say("could not read the index for %s (%s)" % (d, e))
                rows = []
            for r in rows:
                if r["form"] == "4":
                    accs.setdefault(r["accession"], r["cik"])
        d += datetime.timedelta(days=1)
    finder.say("insiders  %d Form 4 filings to read" % len(accs))
    by = {}
    for n, (acc, cik) in enumerate(list(accs.items())[:MAX_FILINGS]):
        url = "https://www.sec.gov/Archives/edgar/data/%d/%s.txt" % (int(cik), acc)
        try:
            raw = finder.get(url)
        except Exception:
            continue
        if not raw:
            continue
        parsed = parse_form4(raw)
        if not parsed:
            continue
        issuer, owners, buys = parsed
        if not buys or not issuer["ticker"] or issuer["ticker"] in ("NONE", "N/A"):
            continue
        g = by.setdefault(issuer["cik"], {"company": issuer["name"], "ticker": issuer["ticker"], "cik": issuer["cik"],
                                           "buyers": {}, "value": 0.0, "last_price": 0.0, "last_date": "", "filings": []})
        for o in owners:
            g["buyers"].setdefault(o["name"], o["role"])
        for b in buys:
            g["value"] += b["shares"] * b["price"]
            if b["date"] >= g["last_date"]:
                g["last_date"], g["last_price"] = b["date"], b["price"]
        g["filings"].append(finder.index_url(cik, acc))
        if (n + 1) % 500 == 0:
            finder.say("insiders  read %d" % (n + 1))
    picks = []
    for g in by.values():
        if g["value"] < MIN_VALUE and len(g["buyers"]) < 2:
            continue
        shares = finder.shares_outstanding(g["cik"])
        g["market_cap"] = shares * g["last_price"] if shares else None
        if g["market_cap"] and g["market_cap"] > MAX_CAP:
            continue
        g["buyers"] = [{"name": k, "role": v} for k, v in g["buyers"].items()]
        picks.append(g)
    picks.sort(key=lambda g: (-len(g["buyers"]), -g["value"]))
    finder.save_json(os.path.join(out, "insiders.json"), {"days": days, "companies": picks})
    L = ["# Insider buying in smaller companies", "",
         "Open-market purchases in Form 4 filings over the last %d days, where several insiders bought or the total was at least $%s, "
         "in companies worth up to $%s. More buyers and bigger amounts come first." % (days, "{:,.0f}".format(MIN_VALUE),
                                                                                      "{:,.0f}".format(MAX_CAP)), "",
         "| Company | Ticker | Insiders buying | Who | Total bought | Last price paid | Market cap |", "|---|---|---|---|---|---|---|"]
    for g in picks[:60]:
        who = "; ".join("%s (%s)" % (b["name"], b["role"]) if b["role"] else b["name"] for b in g["buyers"][:4])
        L.append("| %s | %s | %d | %s | $%s | $%.2f | %s |" % (g["company"].replace("|", "/"), g["ticker"], len(g["buyers"]),
                                                          who.replace("|", "/"), "{:,.0f}".format(g["value"]), g["last_price"],
                                                          finder.money(g["market_cap"])))
    with open(os.path.join(out, "insiders.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    finder.say("insiders  %d companies flagged" % len(picks))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3)
