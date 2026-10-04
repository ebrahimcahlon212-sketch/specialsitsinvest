#!/usr/bin/env python3
"""Deal arithmetic done by Python, so every number is exact and can be redone
whenever prices move, without asking a model again.

The models extract a deal's terms into out/terms.json. This file then works out
the deal value, the spread after costs, the return per year for each closing
date, the probability the market is implying, the probability-weighted result,
break-even prices, proration scenarios for partial tenders, CVR payoffs and
SPAC trust discounts.

Usage
  calc.py terms DEAL           turn the model's extracted terms (out/terms.txt) into out/terms.json
  calc.py deal DEAL            work out the numbers, writing out/calc.json and out/calc.md
  calc.py card JSON_CARD PRICES_JSON   print one card's numbers as JSON (used by the finder)
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quality_gate import preflight
from refclass.quality import whole_holding

TODAY = datetime.date.today()


def us_dividend_tax():
    """The US tax withheld from dividends for this investor, as a fraction. Zero unless set in settings."""
    try:
        return max(0.0, min(float(os.environ.get("US_DIVIDEND_TAX_PCT") or 0) / 100.0, 1.0))
    except ValueError:
        return 0.0


def num(v):
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(",", "").replace("$", "").replace("£", "").strip())
    except ValueError:
        return None


def day(s):
    if not s:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(s))
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def days_to(d):
    return max((d - TODAY).days, 1) if d else None


def pct(x):
    return "n/a" if x is None else "%.2f%%" % (x * 100)


def fmt(x, cur="USD"):
    if x is None:
        return "n/a"
    sign = "-" if x < 0 else ""
    a = abs(x)
    if cur == "GBX":
        return "%s%.2fp" % (sign, a)
    if cur == "GBP":
        return "%s£%.2f" % (sign, a)
    return "%s$%.2f" % (sign, a) if a >= 0.1 or a == 0 else "%s$%.4f" % (sign, a)


def per_year(ret, days):
    return None if (ret is None or not days) else ret * 365.0 / days


# ---------------------------------------------------------------------------
# Prices

def load_prices(deal):
    """Ticker -> {price, bid, ask, time}, from the latest quotes and market.md."""
    prices = {}
    mpath = os.path.join(deal, "market.md")
    if os.path.exists(mpath):
        for line in open(mpath, encoding="utf-8"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4 and re.match(r"^[A-Za-z][A-Za-z0-9.\-]{0,11}$", cells[0] or "") and num(cells[2]) is not None:
                prices[cells[0].upper()] = {"price": num(cells[2]), "time": cells[3]}
    side = os.path.join(deal, "out", "quotes-latest.json")
    if os.path.exists(side):
        try:
            for t, q in json.load(open(side)).items():
                if q.get("price") is not None:
                    prices.setdefault(t.upper(), {}).update(q)
        except ValueError:
            pass
    return prices


def buy_price(q):
    """What a buyer pays. The ask when the quote is tight enough to trust, otherwise the last price."""
    if not q:
        return None, "no price"
    last, bid, ask = num(q.get("price")), num(q.get("bid")), num(q.get("ask"))
    if ask and bid and last and ask >= bid and (ask - bid) / last <= 0.02:
        return ask, "ask"
    return last, "last"


# ---------------------------------------------------------------------------
# The calculation

def compute(t, prices):
    """t is the terms dictionary. Returns a dictionary of results and a list of warnings."""
    warn = []
    cur = (t.get("currency") or "USD").upper()
    target = (t.get("target_ticker") or "").upper()
    q = prices.get(target)
    px, px_src = buy_price(q)
    if px is None:
        warn.append("No price for %s, so nothing that depends on the price can be worked out." % (target or "the target"))
    costs = (num(t.get("costs_pct")) or 0.0) / 100.0
    cash = num(t.get("cash_per_share")) or 0.0
    ratio = num(t.get("stock_ratio")) or 0.0
    acq = (t.get("acquirer_ticker") or "").upper()
    acq_px = num((prices.get(acq) or {}).get("price")) if acq else None
    if ratio and acq_px is None:
        warn.append("No price for the acquirer %s, so the stock part of the deal can't be valued." % (acq or "(not named)"))
    divs = t.get("dividends_to_close") or []
    wht = us_dividend_tax() if cur == "USD" else 0.0
    target_divs = sum(num(d.get("amount")) or 0 for d in divs if str(d.get("who", "")).lower().startswith("target")) * (1 - wht)
    acq_divs = sum(num(d.get("amount")) or 0 for d in divs if str(d.get("who", "")).lower().startswith("acq"))
    value = cash + (ratio * acq_px if (ratio and acq_px is not None) else 0.0)
    if (ratio and acq_px is None) or (not cash and not ratio):
        value = None
    withheld_case = bool(t.get("proceeds_may_be_withheld")) and us_dividend_tax() > 0 and cur == "USD"
    res = {"currency": cur, "target": target, "price": px, "price_source": px_src, "dividend_tax": wht,
           "withheld_case": withheld_case, "otc": bool(t.get("otc")),
           "price_time": (q or {}).get("time", ""), "acquirer": acq, "acquirer_price": acq_px,
           "deal_value": value, "costs_pct": costs * 100}
    structure = (t.get("structure") or "").lower()

    # Plain spread, unhedged (what an ISA holder gets), with dividends received before closing
    if value is not None and px:
        cost = px * (1 + costs)
        gross = value + target_divs - cost
        res["spread"] = gross
        res["spread_pct"] = gross / cost
        if ratio:
            res["hedged_spread"] = value + target_divs - ratio * acq_divs - cost
            res["hedged_spread_pct"] = res["hedged_spread"] / cost
    # Closing scenarios
    scen = []
    for s in t.get("close_scenarios") or []:
        d = day(s.get("date"))
        if not d:
            continue
        dd = days_to(d)
        r = res.get("spread_pct")
        scen.append({"date": d.isoformat(), "prob": num(s.get("prob")), "days": dd, "return": r,
                     "per_year": per_year(r, dd)})
    if not scen and day(t.get("expected_close")):
        d = day(t.get("expected_close"))
        dd = days_to(d)
        r = res.get("spread_pct")
        scen.append({"date": d.isoformat(), "prob": num(t.get("p_close")), "days": dd, "return": r, "per_year": per_year(r, dd)})
    res["scenarios"] = scen
    # Probabilities
    brk = num(t.get("break_price"))
    if brk is not None and value is not None and px:
        denom = value + target_divs - brk
        res["implied_prob"] = (px - brk) / denom if denom > 0 else None
        p_close = sum(s["prob"] for s in scen if s.get("prob")) if any(s.get("prob") for s in scen) else num(t.get("p_close"))
        if p_close is not None:
            ev = p_close * (value + target_divs) + (1 - p_close) * brk
            res["p_close"] = p_close
            res["expected_value"] = ev
            res["expected_return"] = ev / (px * (1 + costs)) - 1
            wdays = sum(s["prob"] * s["days"] for s in scen if s.get("prob")) / p_close if (scen and p_close) else None
            if wdays:
                res["expected_per_year"] = per_year(res["expected_return"], wdays)
                res["expected_days"] = wdays
        res["break_price"] = brk
        res["break_loss_pct"] = brk / (px * (1 + costs)) - 1
        full = value + target_divs
        if full > brk:
            grid = []
            for cut in (0.0, 0.05, 0.10, 0.15):
                p_in = px * (1 - cut)
                c_in = p_in * (1 + costs)
                grid.append({"price": p_in, "needed": (c_in - brk) / (full - brk), "gain": full / c_in - 1, "loss": brk / c_in - 1})
            res["price_grid"] = grid
    # Break-even prices for hurdle rates
    hurdles = [num(h) for h in (t.get("hurdles_pct") or [10, 15]) if num(h)]
    if value is not None and scen:
        res["max_prices"] = [{"date": s["date"], "hurdle": h,
                              "max_price": (value + target_divs) / ((1 + h / 100.0 * s["days"] / 365.0) * (1 + costs))}
                             for s in scen for h in hurdles]
    # Partial tender offers
    tender = t.get("tender") or {}
    tprice = num(tender.get("price"))
    if tprice and px:
        sought = num(tender.get("shares_sought"))
        out = num(tender.get("shares_outstanding"))
        held = num(tender.get("shares_held_by_bidder")) or 0
        pay_date = day(tender.get("expiry"))
        pdays = days_to(pay_date + datetime.timedelta(days=7)) if pay_date else None
        backs = tender.get("back_end_prices") or {}
        back_list = [(k, num(v)) for k, v in backs.items() if num(v) is not None] or [("current price", px)]
        rows = []
        if sought and out:
            free = max(out - held, 1)
            for part in (1.0, 0.75, 0.5, 0.25):
                frac = min(1.0, sought / (free * part))
                row = {"participation": part, "accepted": frac,
                       "break_even_back_end": (px * (1 + costs) - frac * tprice) / (1 - frac) if frac < 1 else None,
                       "results": []}
                for label, b in back_list:
                    val = frac * tprice + (1 - frac) * b
                    ret = val / (px * (1 + costs)) - 1
                    item = {"back_end": label, "price": b, "return": ret, "per_year": per_year(ret, pdays)}
                    if withheld_case:
                        item["return_withheld"] = (frac * tprice * (1 - us_dividend_tax()) + (1 - frac) * b) / (px * (1 + costs)) - 1
                    row["results"].append(item)
                rows.append(row)
        res["tender"] = {"price": tprice, "rows": rows, "days": pdays,
                         "odd_lot": bool(tender.get("odd_lot_priority")),
                         "odd_lot_return": (tprice / (px * (1 + costs)) - 1) if tender.get("odd_lot_priority") else None,
                         "odd_lot_return_withheld": (tprice * (1 - us_dividend_tax()) / (px * (1 + costs)) - 1)
                         if (tender.get("odd_lot_priority") and withheld_case) else None}
        entitlement = num(tender.get("expected_entitlement"))
        if entitlement is None and rows:
            entitlement = rows[0]["accepted"]
        if entitlement is not None:
            residual = num(tender.get("expected_residual_price"))
            residual = px if residual is None else residual
            res["tender"].update(expected_entitlement=entitlement, expected_residual_price=residual,
                                 headline_return=whole_holding(px * (1 + costs), tprice, entitlement, residual))
    # CVRs
    cvr = t.get("cvr") or {}
    if cvr and px:
        pay = day(cvr.get("earliest_payment"))
        cdays = days_to(pay)
        rows = []
        levels = cvr.get("scenarios") or [{"label": "pays nothing", "payout": 0},
                                          {"label": "minimum payout", "payout": cvr.get("min_payout")},
                                          {"label": "maximum payout", "payout": cvr.get("max_payout")}]
        ev = 0.0
        have_prob = False
        for lv in levels:
            p_out = num(lv.get("payout"))
            if p_out is None:
                continue
            total = (value if value is not None else cash) + p_out
            ret = total / (px * (1 + costs)) - 1
            prob = num(lv.get("prob"))
            if prob is not None:
                have_prob = True
                ev += prob * p_out
            rows.append({"label": lv.get("label") or "", "payout": p_out, "total": total, "return": ret,
                         "per_year": per_year(ret, cdays), "prob": prob})
        res["cvr"] = {"rows": rows, "days": cdays, "expected_payout": ev if have_prob else None,
                      "price_paid_for_cvr": px * (1 + costs) - (value if value is not None else cash)}
    # SPAC trusts
    trust = num(t.get("trust_per_share"))
    if trust and px:
        rd = day(t.get("redemption_date"))
        rdays = days_to(rd)
        ret = trust / (px * (1 + costs)) - 1
        res["spac"] = {"trust": trust, "return": ret, "days": rdays, "per_year": per_year(ret, rdays),
                       "date": rd.isoformat() if rd else "",
                       "return_withheld": (trust * (1 - us_dividend_tax()) / (px * (1 + costs)) - 1) if withheld_case else None}
    return res, warn


# ---------------------------------------------------------------------------
# Output

def to_markdown(res, warn, t):
    cur = res["currency"]
    L = ["## Numbers from the calculator", "",
         "Worked out by Python from the extracted terms and the latest prices, on %s. The price used for %s is %s (%s%s). "
         "Returns are simple, not compounded, and per-year figures use calendar days." % (
             TODAY.isoformat(), res["target"] or "the target", fmt(res["price"], cur), res["price_source"],
             (", " + res["price_time"]) if res.get("price_time") else ""), ""]
    if res.get("dividend_tax"):
        L.append("Dividends from US companies are counted after %.0f%% US tax withheld at source, as set in settings." %
                 (res["dividend_tax"] * 100))
        L.append("")
    if res.get("otc"):
        L.append("These shares trade over the counter, and OTC shares generally can't be held in an ISA.")
        L.append("")
    for w in warn:
        L.append("- %s" % w)
    if warn:
        L.append("")
    rows = []
    tender_headline = (res.get("tender") or {}).get("headline_return")
    if tender_headline is not None:
        rows.append(("Whole-holding return at expected entitlement", pct(tender_headline)))
    if res.get("deal_value") is not None:
        rows.append(("Deal value per share" + (" before any CVR" if res.get("cvr") else ""), fmt(res["deal_value"], cur)))
    if res.get("acquirer"):
        rows.append(("%s price used" % res["acquirer"], fmt(res.get("acquirer_price"), cur)))
    if res.get("costs_pct"):
        rows.append(("Buying costs", "%.2f%% of the price" % res["costs_pct"]))
    if "spread" in res and not res.get("tender"):
        rows.append(("Spread, unhedged" + (", before any CVR" if res.get("cvr") else ""),
                     "%s (%s)" % (fmt(res["spread"], cur), pct(res["spread_pct"]))))
    if "hedged_spread" in res:
        rows.append(("Spread, hedged by shorting the acquirer", "%s (%s)" % (fmt(res["hedged_spread"], cur),
                                                                           pct(res["hedged_spread_pct"]))))
    if res.get("implied_prob") is not None:
        rows.append(("Chance of closing the market implies", pct(res["implied_prob"])))
    if res.get("p_close") is not None:
        rows.append(("Chance of closing, report's estimate", pct(res["p_close"])))
    if res.get("expected_return") is not None:
        rows.append(("Probability-weighted return", "%s, about %s a year" % (
            pct(res["expected_return"]), pct(res.get("expected_per_year")))))
    if res.get("break_price") is not None:
        rows.append(("If the deal breaks", "%s, a change of %s" % (fmt(res["break_price"], cur), pct(res["break_loss_pct"]))))
    if rows:
        L += ["| Item | Value |", "|---|---|"] + ["| %s | %s |" % r for r in rows] + [""]
    if res.get("price_grid"):
        L += ["### What each entry price needs", "",
              "The chance of completion needed to break even, if the shares fall to %s when the deal doesn't happen." % fmt(res["break_price"], cur), "",
              "| Price paid | Chance needed | Gain if completed | Loss if not |", "|---|---|---|---|"]
        L += ["| %s | %s | %s | %s |" % (fmt(gr["price"], cur), pct(gr["needed"]), pct(gr["gain"]), pct(gr["loss"])) for gr in res["price_grid"]]
        L.append("")
    if res.get("scenarios"):
        L += ["### By closing date", "", "| Closing date | Days | Chance | Return | Per year |", "|---|---|---|---|---|"]
        L += ["| %s | %d | %s | %s | %s |" % (s["date"], s["days"], pct(s["prob"]) if s.get("prob") is not None else "n/a",
                                            pct(s["return"]), pct(s["per_year"])) for s in res["scenarios"]]
        L.append("")
    if res.get("max_prices"):
        L += ["### Highest price to pay for a target return", "", "| Closing date | Target return a year | Highest price |",
              "|---|---|---|"]
        L += ["| %s | %.0f%% | %s |" % (m["date"], m["hurdle"], fmt(m["max_price"], cur)) for m in res["max_prices"]]
        L.append("")
    tn = res.get("tender")
    if tn and tn.get("rows"):
        L += ["### Partial tender, by how many holders tender", "",
              "Accepted is the share of your tendered shares the bidder buys. The rest you keep at the back-end price.", ""]
        heads = [r["back_end"] for r in tn["rows"][0]["results"]]
        wcol = res.get("withheld_case")
        cols = []
        for i, h in enumerate(heads):
            cols.append("Return if back end is %s (%s)" % (h, fmt(tn["rows"][0]["results"][i]["price"], cur)))
            if wcol:
                cols.append("Same, with US tax withheld")
        L += ["| Holders tendering | Accepted | Break-even back-end price | %s |" % " | ".join(cols),
              "|---|---|---|" + "---|" * len(cols)]
        for r in tn["rows"]:
            vals = []
            for x in r["results"]:
                vals.append(pct(x["return"]))
                if wcol:
                    vals.append(pct(x.get("return_withheld")))
            L.append("| %s | %s | %s | %s |" % (pct(r["participation"]), pct(r["accepted"]),
                                                fmt(r["break_even_back_end"], cur) if r["break_even_back_end"] else "n/a",
                                                " | ".join(vals)))
        L.append("")
        if tn.get("odd_lot"):
            L += ["Odd-lot priority applies, so 99 shares or fewer are bought in full, a return of %s." % pct(tn["odd_lot_return"]), ""]
            if tn.get("odd_lot_return_withheld") is not None:
                L += ["If the payment is treated as a dividend and %.0f%% US tax is withheld from the whole payment, that becomes %s. "
                      "Getting it back would need a US tax return, which is slow and not certain." % (
                          res["dividend_tax"] * 100 if res.get("dividend_tax") else us_dividend_tax() * 100,
                          pct(tn["odd_lot_return_withheld"])), ""]
        if wcol:
            L += ["The offer document says payments to non-US holders may be treated as dividends, so the withheld columns "
                  "show what happens if US tax is taken from the whole payment.", ""]
    cv = res.get("cvr")
    if cv and cv.get("rows"):
        L += ["### CVR payoffs", "", "You pay about %s for the CVR at today's price." % fmt(cv["price_paid_for_cvr"], cur), "",
              "| Outcome | CVR pays | Total per share | Return | Per year to payment |", "|---|---|---|---|---|"]
        L += ["| %s | %s | %s | %s | %s |" % (r["label"], fmt(r["payout"], cur), fmt(r["total"], cur), pct(r["return"]),
                                            pct(r["per_year"])) for r in cv["rows"]]
        if cv.get("expected_payout") is not None:
            L.append("")
            L.append("Probability-weighted CVR payout %s." % fmt(cv["expected_payout"], cur))
        L.append("")
    sp = res.get("spac")
    if sp:
        L += ["### SPAC trust", "", "Trust value %s per share against %s, a return of %s%s." % (
            fmt(sp["trust"], cur), fmt(res["price"], cur), pct(sp["return"]),
            (", about %s a year to %s" % (pct(sp["per_year"]), sp["date"])) if sp.get("per_year") is not None else ""), ""]
        if sp.get("return_withheld") is not None:
            L += ["If the redemption is treated as a dividend and %.0f%% US tax is withheld from the whole payment, the return "
                  "becomes %s." % (us_dividend_tax() * 100, pct(sp["return_withheld"])), ""]
    return "\n".join(L).rstrip() + "\n"


def cmd_terms(deal):
    """Pull the JSON object out of the model's reply and save it as terms.json."""
    out = os.path.join(deal, "out")
    text = open(os.path.join(out, "terms.txt"), encoding="utf-8", errors="replace").read()
    start, depth, obj = text.find("{"), 0, None
    if start >= 0:
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                    except ValueError:
                        obj = None
                    break
    if not isinstance(obj, dict):
        sys.exit("The extracted terms were not valid JSON. See out/terms.txt.")
    with open(os.path.join(out, "terms.json"), "w") as fh:
        json.dump(obj, fh, indent=1)
    print("  terms       saved %s" % os.path.relpath(os.path.join(out, "terms.json")))


def cmd_deal(deal):
    out = os.path.join(deal, "out")
    preflight(out)
    tpath = os.path.join(out, "terms.json")
    if not os.path.exists(tpath):
        sys.exit("No terms.json yet. Run the terms step first.")
    t = json.load(open(tpath))
    res, warn = compute(t, load_prices(deal))
    with open(os.path.join(out, "calc.json"), "w") as fh:
        json.dump({"results": res, "warnings": warn, "terms": t, "date": TODAY.isoformat()}, fh, indent=1)
    with open(os.path.join(out, "calc.md"), "w", encoding="utf-8") as fh:
        fh.write(to_markdown(res, warn, t))
    head = "spread %s" % pct(res.get("spread_pct")) if res.get("spread_pct") is not None else "no spread"
    if (res.get("tender") or {}).get("headline_return") is not None:
        head = "whole-holding return %s" % pct(res["tender"]["headline_return"])
    if res.get("scenarios"):
        head += ", %s a year to %s" % (pct(res["scenarios"][0]["per_year"]), res["scenarios"][0]["date"])
    print("  calculator  %s%s" % (head, (" (" + "; ".join(warn) + ")") if warn else ""))


def cmd_card(card_path, prices_path):
    card = json.load(open(card_path))
    prices = json.load(open(prices_path))
    res, warn = compute(card, prices)
    print(json.dumps({"results": res, "warnings": warn}))


def cmd_new_docs(deal):
    """Print the short names of documents that the last report did not see."""
    work = os.path.join(deal, "work", "manifest.json")
    if not os.path.exists(work):
        return
    manifest = json.load(open(work))
    seen_path = os.path.join(deal, "out", "report-docs.json")
    report = os.path.join(deal, "out", "report.md")
    if os.path.exists(seen_path):
        seen = set(json.load(open(seen_path)))
        new = [d for d in manifest if d not in seen]
    elif os.path.exists(report):
        cutoff = os.path.getmtime(report)
        new = [d for d, v in manifest.items() if (v.get("fp") or {}).get("mtime", 0) > cutoff]
    else:
        new = []
    print(" ".join(sorted(new)))


def cmd_save_docs(deal):
    work = os.path.join(deal, "work", "manifest.json")
    if os.path.exists(work):
        with open(os.path.join(deal, "out", "report-docs.json"), "w") as fh:
            json.dump(sorted(json.load(open(work))), fh)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "new-docs":
        return cmd_new_docs(sys.argv[2])
    if cmd == "save-docs":
        return cmd_save_docs(sys.argv[2])
    if cmd == "terms":
        cmd_terms(sys.argv[2])
    elif cmd == "deal":
        cmd_deal(sys.argv[2])
    elif cmd == "card" and len(sys.argv) == 4:
        cmd_card(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
