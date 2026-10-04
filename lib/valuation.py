#!/usr/bin/env python3
"""Standalone valuation done by Python, from inputs a model extracts.

It works out enterprise value and multiples at the undisturbed price, today's
price and any offer, historical growth, margins and cash conversion, value per
share at a range of EBITDA multiples, and a discounted cash flow value for each
case the report sets out.

Usage
  valuation.py extract DEAL    turn out/valuation.txt into out/valuation.json
  valuation.py compute DEAL    write out/valuation-results.json and out/valuation.md
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calc  # noqa: E402


def n(v):
    return calc.num(v)


def per_share_price(value_m, shares_m, fx, price_currency):
    """Equity value in millions of the reporting currency to a price per share in the trading currency."""
    if value_m is None or not shares_m:
        return None
    per = value_m / shares_m * (fx or 1.0)
    return per * 100 if price_currency == "GBX" else per


def to_money_m(price, shares_m, fx, price_currency):
    """A share price to a market value in millions of the reporting currency."""
    if price is None or not shares_m:
        return None
    main = price / 100.0 if price_currency == "GBX" else price
    return main * shares_m / (fx or 1.0)


def compute(v, prices):
    cur = (v.get("price_currency") or "GBX").upper()
    fx = n(v.get("fx_to_price_currency")) or 1.0
    shares = n(v.get("shares_diluted_m"))
    debt = (n(v.get("net_debt_m")) or 0.0) + (n(v.get("other_claims_m")) or 0.0)
    hist = sorted([h for h in (v.get("history") or []) if n(h.get("year"))], key=lambda h: n(h["year"]))
    fwd = v.get("forward") or {}
    last = hist[-1] if hist else {}
    res = {"currency": cur, "shares_m": shares, "claims_m": debt, "rows": [], "history": [], "multiples": [], "dcf": []}
    for label, price in (("Undisturbed price", n(v.get("undisturbed_price"))), ("Today's price", prices.get("today")),
                         ("Offer", n(v.get("offer_price")))):
        if price is None:
            continue
        mcap = to_money_m(price, shares, fx, cur)
        ev = mcap + debt if mcap is not None else None
        row = {"label": label, "price": price, "mcap_m": mcap, "ev_m": ev}
        for key, src in (("ev_ebitda_last", last.get("ebitda_m")), ("ev_ebitda_fwd", fwd.get("ebitda_m")),
                         ("ev_ebit_last", last.get("ebit_m"))):
            d = n(src)
            row[key] = ev / d if (ev is not None and d) else None
        f = n(last.get("fcf_m"))
        row["fcf_yield_last"] = f / mcap if (f is not None and mcap) else None
        res["rows"].append(row)
    prev = None
    for h in hist:
        rev, eb, ebit, capex, fcf = (n(h.get(k)) for k in ("revenue_m", "ebitda_m", "ebit_m", "capex_m", "fcf_m"))
        res["history"].append({"year": int(n(h["year"])), "revenue_m": rev,
                               "growth": (rev / prev - 1) if (rev and prev) else None,
                               "ebitda_margin": eb / rev if (eb is not None and rev) else None,
                               "ebit_margin": ebit / rev if (ebit is not None and rev) else None,
                               "capex_to_revenue": capex / rev if (capex is not None and rev) else None,
                               "fcf_conversion": fcf / eb if (fcf is not None and eb) else None})
        prev = rev
    if len(hist) >= 2:
        r0, r1 = n(hist[0].get("revenue_m")), n(hist[-1].get("revenue_m"))
        years = n(hist[-1]["year"]) - n(hist[0]["year"])
        if r0 and r1 and years:
            res["revenue_cagr"] = (r1 / r0) ** (1.0 / years) - 1
    for mult in [n(m) for m in (v.get("multiples") or [6, 8, 10, 12]) if n(m)]:
        out = {"multiple": mult}
        for key, base in (("last", n(last.get("ebitda_m"))), ("fwd", n(fwd.get("ebitda_m")))):
            out[key] = per_share_price(mult * base - debt, shares, fx, cur) if base else None
        res["multiples"].append(out)
    leases_in_debt = v.get("leases_in_net_debt", True) is not False
    for sc in v.get("scenarios") or []:
        flows, build = scenario_flows(sc, leases_in_debt)
        if not flows:
            continue
        tg, r = (n(sc.get("terminal_growth_pct")) or 0) / 100.0, (n(sc.get("discount_pct")) or 10) / 100.0
        if r <= tg:
            continue
        ev, tv_pv = dcf_ev(flows, r, tg)
        res["dcf"].append({"label": sc.get("label") or "", "ev_m": ev, "equity_m": ev - debt,
                           "per_share": per_share_price(ev - debt, shares, fx, cur),
                           "terminal_share": tv_pv / ev if ev else None, "build": build,
                           "inputs": {"fcf_first_m": flows[0], "fcf_last_m": flows[-1], "years": len(flows),
                                      "growth": (n(sc.get("growth_pct")) or 0) / 100.0, "terminal_growth": tg, "discount": r}})
        # the yearly return a buyer earns on this case's cash flows, at each price
        rets = []
        for row in res["rows"]:
            rets.append({"label": row["label"], "price": row["price"],
                         "irr": implied_return(flows, tg, row["ev_m"]) if row.get("ev_m") else None})
        res["dcf"][-1]["implied_returns"] = rets
    base = next((d for d in res["dcf"] if "base" in (d["label"] or "").lower()), res["dcf"][len(res["dcf"]) // 2] if res["dcf"] else None)
    if base:
        sc = next(s for s in (v.get("scenarios") or []) if (s.get("label") or "") == base["label"])
        flows, _ = scenario_flows(sc, leases_in_debt)
        r0, g0 = base["inputs"]["discount"], base["inputs"]["terminal_growth"]
        rates = [round(r0 + d, 4) for d in (-0.02, -0.01, 0, 0.01, 0.02) if r0 + d > 0.02]
        growths = [round(g0 + d, 4) for d in (-0.01, -0.005, 0, 0.005, 0.01)]
        grid = []
        for rr in rates:
            line = []
            for gg in growths:
                if rr <= gg:
                    line.append(None)
                    continue
                ev, _ = dcf_ev(flows, rr, gg)
                line.append(per_share_price(ev - debt, shares, fx, cur))
            grid.append({"discount": rr, "values": line})
        res["grid"] = {"label": base["label"], "growths": growths, "rows": grid}
    return res


def scenario_flows(sc, leases_in_debt=True):
    """Yearly free cash flow before interest, built from revenue, margins, tax and reinvestment when those are given."""
    yrs = int(n(sc.get("years")) or 5)
    g = (n(sc.get("growth_pct")) or 0) / 100.0
    rev0 = n(sc.get("revenue_m"))
    margin = n(sc.get("ebit_margin_pct"))
    if rev0 and margin is not None:
        tax = (n(sc.get("tax_rate_pct")) or 25) / 100.0
        da = (n(sc.get("da_pct_revenue")) or 0) / 100.0
        capex = (n(sc.get("capex_pct_revenue")) or 0) / 100.0
        wc = (n(sc.get("working_capital_pct_revenue")) or 0) / 100.0
        lease = 0.0 if leases_in_debt else (n(sc.get("lease_payments_m")) or 0.0)
        flows, rev_prev, rev = [], rev0, rev0
        for t in range(1, yrs + 1):
            rev = rev_prev * (1 + g)
            ebit = rev * margin / 100.0
            f = ebit * (1 - tax) + rev * da - rev * capex - (rev - rev_prev) * wc - lease
            flows.append(f)
            if t == 1:
                build = {"revenue_m": rev, "ebit_m": ebit, "tax_m": ebit * tax, "da_m": rev * da, "capex_m": rev * capex,
                         "wc_m": (rev - rev_prev) * wc, "lease_m": lease, "fcf_m": f}
            rev_prev = rev
        return flows, build
    f0 = n(sc.get("fcf_base_m"))
    if f0 is None:
        return [], None
    flows, f = [], f0
    for _ in range(yrs):
        f *= 1 + g
        flows.append(f)
    return flows, None


def dcf_ev(flows, r, tg):
    pv = sum(f / (1 + r) ** (t + 1) for t, f in enumerate(flows))
    tv = flows[-1] * (1 + tg) / (r - tg)
    tv_pv = tv / (1 + r) ** len(flows)
    return pv + tv_pv, tv_pv


def implied_return(flows, tg, ev):
    """The discount rate at which these cash flows are worth exactly this enterprise value."""
    lo, hi = tg + 0.001, 0.60
    if dcf_ev(flows, lo, tg)[0] < ev:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if dcf_ev(flows, mid, tg)[0] > ev:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def md(res, v, prices):
    cur = res["currency"]
    f = lambda x: calc.fmt(x, cur)
    m = lambda x: "n/a" if x is None else "%.1f" % x
    x = lambda y: "n/a" if y is None else "%.1fx" % y
    L = ["## Valuation from the calculator", "",
         "Worked out by Python from the extracted inputs on %s. Money figures are in millions of the reporting currency (%s) "
         "and prices are per share in %s. Claims ahead of shareholders, meaning net debt, leases and other claims, "
         "come to %s million." % (calc.TODAY.isoformat(), v.get("reporting_currency") or "as reported", cur, m(res["claims_m"])), ""]
    if res["rows"]:
        L += ["### What the price implies", "",
              "| Price | Per share | Market value | Enterprise value | EV to last EBITDA | EV to next year's EBITDA | EV to last EBIT | Free cash flow yield |",
              "|---|---|---|---|---|---|---|---|"]
        L += ["| %s | %s | %s | %s | %s | %s | %s | %s |" % (r["label"], f(r["price"]), m(r["mcap_m"]), m(r["ev_m"]),
                                                          x(r["ev_ebitda_last"]), x(r["ev_ebitda_fwd"]), x(r["ev_ebit_last"]),
                                                          calc.pct(r["fcf_yield_last"])) for r in res["rows"]]
        L.append("")
    if res["history"]:
        L += ["### History", "", "| Year | Revenue | Growth | EBITDA margin | EBIT margin | Capex to revenue | Cash conversion |",
              "|---|---|---|---|---|---|---|"]
        L += ["| %d | %s | %s | %s | %s | %s | %s |" % (h["year"], m(h["revenue_m"]), calc.pct(h["growth"]),
                                                      calc.pct(h["ebitda_margin"]), calc.pct(h["ebit_margin"]),
                                                      calc.pct(h["capex_to_revenue"]), calc.pct(h["fcf_conversion"]))
              for h in res["history"]]
        L.append("")
        if res.get("revenue_cagr") is not None:
            L += ["Revenue grew %s a year on average over the period. Cash conversion is free cash flow divided by EBITDA." %
                  calc.pct(res["revenue_cagr"]), ""]
    if res["multiples"]:
        L += ["### Value per share at different EBITDA multiples", "", "| EV to EBITDA | On last year's EBITDA | On next year's EBITDA |",
              "|---|---|---|"]
        L += ["| %.1fx | %s | %s |" % (r["multiple"], f(r["last"]), f(r["fwd"])) for r in res["multiples"]]
        L.append("")
    if res["dcf"]:
        L += ["### Discounted cash flow", "",
              "| Case | Free cash flow, year 1 | Growth a year | Years | Growth after | Discount rate | Value per share | Share of value after the forecast |",
              "|---|---|---|---|---|---|---|---|"]
        for d in res["dcf"]:
            i = d["inputs"]
            L.append("| %s | %s | %s | %d | %s | %s | %s | %s |" % (d["label"], m(i["fcf_first_m"]), calc.pct(i["growth"]), i["years"],
                                                                 calc.pct(i["terminal_growth"]), calc.pct(i["discount"]),
                                                                 f(d["per_share"]), calc.pct(d["terminal_share"])))
        L += ["", "A large share of value after the forecast means the answer depends heavily on the long-run assumptions.", ""]
        built = [d for d in res["dcf"] if d.get("build")]
        if built:
            L += ["### How year 1 free cash flow is built", "",
                  "Free cash flow is operating profit after tax, plus depreciation, minus capex and the extra working capital growth "
                  "needs. Interest is left out because debt is subtracted separately, so its tax saving is left out too. Lease "
                  "payments are only subtracted when leases are not already counted in net debt, so nothing is counted twice.", "",
                  "| Case | Revenue | Operating profit | Tax | Depreciation | Capex | Working capital | Leases | Free cash flow |",
                  "|---|---|---|---|---|---|---|---|---|"]
            for d in built:
                b = d["build"]
                L.append("| %s | %s | %s | -%s | +%s | -%s | -%s | -%s | %s |" % (
                    d["label"], m(b["revenue_m"]), m(b["ebit_m"]), m(b["tax_m"]), m(b["da_m"]), m(b["capex_m"]), m(b["wc_m"]),
                    m(b["lease_m"]), m(b["fcf_m"])))
            L.append("")
        irr_rows = [d for d in res["dcf"] if d.get("implied_returns")]
        if irr_rows:
            labels = [r["label"] for r in irr_rows[0]["implied_returns"]]
            L += ["### Yearly return a buyer earns at each price", "",
                  "If the cash flows in a case come true, this is the return per year someone paying each price would earn. "
                  "Compare it with what a buyer like a private equity fund needs.", "",
                  "| Case | %s |" % " | ".join("At %s (%s)" % (lb, f(irr_rows[0]["implied_returns"][i]["price"])) for i, lb in enumerate(labels)),
                  "|---|" + "---|" * len(labels)]
            for d in irr_rows:
                L.append("| %s | %s |" % (d["label"], " | ".join(calc.pct(x["irr"]) for x in d["implied_returns"])))
            L.append("")
    g = res.get("grid")
    if g and g["rows"]:
        L += ["### How the %s value moves with the two biggest assumptions" % g["label"], "",
              "Value per share. Rows are the discount rate and columns are growth after the forecast.", "",
              "| Discount rate | %s |" % " | ".join(calc.pct(x) for x in g["growths"]), "|---|" + "---|" * len(g["growths"])]
        for row in g["rows"]:
            L.append("| %s | %s |" % (calc.pct(row["discount"]), " | ".join(f(x) if x is not None else "n/a" for x in row["values"])))
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def cmd_extract(deal):
    out = os.path.join(deal, "out")
    text = open(os.path.join(out, "valuation.txt"), encoding="utf-8", errors="replace").read()
    start = text.find("{")
    obj, depth = None, 0
    for i in range(max(start, 0), len(text)):
        if start < 0:
            break
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
        sys.exit("The valuation inputs were not valid JSON. See out/valuation.txt.")
    with open(os.path.join(out, "valuation.json"), "w") as fh:
        json.dump(obj, fh, indent=1)
    print("  valuation   inputs saved")


def cmd_compute(deal):
    out = os.path.join(deal, "out")
    v = json.load(open(os.path.join(out, "valuation.json")))
    info = json.load(open(os.path.join(deal, "deal.json"))) if os.path.exists(os.path.join(deal, "deal.json")) else {}
    tick = (info.get("ticker") or "").upper()
    p = calc.load_prices(deal).get(tick) or {}
    prices = {"today": n(p.get("price"))}
    res = compute(v, prices)
    with open(os.path.join(out, "valuation-results.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    with open(os.path.join(out, "valuation.md"), "w", encoding="utf-8") as fh:
        fh.write(md(res, v, prices))
    base = [d for d in res["dcf"] if "base" in (d["label"] or "").lower()]
    print("  valuation   %d cases%s" % (len(res["dcf"]), (", base case %s a share" % calc.fmt(base[0]["per_share"], res["currency"]))
                                         if base and base[0]["per_share"] is not None else ""))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "extract":
        cmd_extract(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "compute":
        cmd_compute(sys.argv[2])
    else:
        sys.exit(__doc__)
