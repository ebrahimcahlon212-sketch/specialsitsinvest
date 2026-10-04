#!/usr/bin/env python3
"""Keep a deal's market.md prices current from IBKR.

Usage
  quotes.py tickers DEAL           print the deal's tickers, one per line
  quotes.py fill DEAL QUOTES_FILE  write the quotes (JSON lines from the model) into market.md
"""
import json
import os
import re
import sys


def table_rows(lines, start):
    """Return (first_index, last_index_exclusive, rows) for the table after line `start`."""
    i = start + 1
    while i < len(lines) and not lines[i].startswith("|"):
        if lines[i].startswith("## "):
            return i, i, []
        i += 1
    first = i
    rows = []
    while i < len(lines) and lines[i].startswith("|"):
        rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
        i += 1
    return first, i, rows


def find_prices(lines):
    for k, ln in enumerate(lines):
        if re.match(r"^##\s+prices\b", ln, re.I):
            return k
    return None


def deal_tickers(deal):
    found = []
    info = os.path.join(deal, "deal.json")
    if os.path.exists(info):
        d = json.load(open(info))
        t = (d.get("ticker") or "").strip()
        if t:
            found.append(t)
        found += list((d.get("roles") or {}).keys())
    mpath = os.path.join(deal, "market.md")
    if os.path.exists(mpath):
        lines = open(mpath, encoding="utf-8").read().splitlines()
        k = find_prices(lines)
        if k is not None:
            _, _, rows = table_rows(lines, k)
            for r in rows[2:]:
                if r and r[0] and re.match(r"^[A-Za-z0-9.\- ]{1,12}$", r[0]):
                    found.append(r[0])
    for name in ("report.md", "draft.md"):
        p = os.path.join(deal, "out", name)
        if os.path.exists(p):
            m = re.search(r"^#\s+.*?\(([A-Z][A-Z0-9.\-]{0,9})\)", open(p, encoding="utf-8").read(), re.M)
            if m:
                found.append(m.group(1))
            break
    out = []
    for t in found:
        if t.upper() not in [x.upper() for x in out]:
            out.append(t.upper())
    return out


def read_quotes(path):
    quotes = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"\{.*\}", line)
        if not m:
            continue
        try:
            q = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(q, dict) and q.get("ticker"):
            quotes.append(q)
    return quotes


def fill(deal, qpath):
    quotes = read_quotes(qpath)
    mpath = os.path.join(deal, "market.md")
    text = open(mpath, encoding="utf-8").read() if os.path.exists(mpath) else "# Market data for this deal\n"
    lines = text.splitlines()
    k = find_prices(lines)
    header = ["Ticker", "Role in the situation", "Price", "Date and time"]
    if k is None:
        lines += ["", "## Prices", "", "| " + " | ".join(header) + " |", "|---|---|---|---|"]
        k = len(lines) - 4
    first, last, rows = table_rows(lines, k)
    if len(rows) >= 2:
        header, data = rows[0], rows[2:]
    else:
        data = []
    data = [r + [""] * (4 - len(r)) for r in data if any(c for c in r)]
    roles = {}
    info = os.path.join(deal, "deal.json")
    if os.path.exists(info):
        roles = dict((k.upper(), v) for k, v in (json.load(open(info)).get("roles") or {}).items())
    updated, missing = 0, []
    for q in quotes:
        t = str(q["ticker"]).upper().strip()
        price = q.get("price")
        try:
            price = float(price)
        except (TypeError, ValueError):
            missing.append("%s (%s)" % (t, q.get("note") or "no quote"))
            continue
        when = "%s (IBKR%s)" % (q.get("time") or "", ", " + q["note"] if q.get("note") else "")
        row = next((r for r in data if r[0].upper() == t), None)
        if row is None:
            row = [t, "", "", ""]
            data.append(row)
        if not row[1] and t in roles:
            row[1] = roles[t]
        row[2] = "%.2f" % price if price >= 1 else "%.4f" % price
        row[3] = when.replace("|", "/").strip()
        updated += 1
    table = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    table += ["| " + " | ".join(r[:len(header)]) + " |" for r in data]
    table.append("| " + " | ".join([""] * len(header)) + " |")
    if first == last:
        lines[k + 1:k + 1] = [""] + table
    else:
        lines[first:last] = table
    with open(mpath, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")
    side = os.path.join(deal, "out", "quotes-latest.json")
    latest = {}
    if os.path.exists(side):
        try:
            latest = json.load(open(side))
        except ValueError:
            latest = {}
    for q in quotes:
        t = str(q["ticker"]).upper().strip()
        try:
            latest[t] = {"price": float(q.get("price")), "bid": q.get("bid"), "ask": q.get("ask"),
                         "time": q.get("time") or "", "note": q.get("note") or ""}
        except (TypeError, ValueError):
            continue
    os.makedirs(os.path.dirname(side), exist_ok=True)
    with open(side, "w") as fh:
        json.dump(latest, fh, indent=1)
    print("  prices      %d updated from IBKR in %s" % (updated, os.path.relpath(mpath, os.path.dirname(os.path.dirname(os.path.abspath(deal))))))
    for m in missing:
        print("  no quote    %s" % m)


def uk_info(deal):
    info = os.path.join(deal, "deal.json")
    d = json.load(open(info)) if os.path.exists(info) else {}
    return d if d.get("market") == "UK" else None


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "tickers":
        uk = uk_info(sys.argv[2])
        lines = []
        for t in deal_tickers(sys.argv[2]):
            if uk and t == (uk.get("ticker") or "").upper():
                lines.append("%s (London Stock Exchange, ISIN %s, give the price in pence)" % (t, uk.get("isin") or "unknown"))
            else:
                lines.append(t)
        print("\n".join(lines))
    elif len(sys.argv) >= 4 and sys.argv[1] == "fill":
        fill(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
