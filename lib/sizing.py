#!/usr/bin/env python3
"""How much to put into one situation, worked out by Python.

It takes the payoff if the deal completes and if it fails from the calculator,
and the chance of completion, preferring your own logged prediction for the
deal, then the report's estimate. The Kelly formula gives the share of the
account that grows it fastest over many bets, and the kit uses half of that,
because full Kelly swings too hard and the probabilities are estimates.
The ISA rules from settings are then applied, meaning the largest share one
situation may take, the cash kept back for opportunities, and a warning when
trading costs eat too much of a small position.

Usage: sizing.py DEAL [CHANCE]
Settings used: ISA_VALUE, MAX_POSITION_PCT (25), CASH_RESERVE_PCT (20),
TRADE_COST_GBP (3), GBPUSD for US shares.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calc  # noqa: E402
import finder  # noqa: E402


def setting(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return float(default)


def my_prediction(name):
    path = os.path.join(finder.KIT, "journal", "predictions.jsonl")
    best = None
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                p = json.loads(line)
            except ValueError:
                continue
            if (p.get("deal") or "").lower() == name.lower():
                best = p
    return best


def main(deal, chance_arg=None):
    name = os.path.basename(os.path.abspath(deal))
    c = finder.load_json(os.path.join(deal, "out", "calc.json"), {}).get("results") or {}
    if not c or c.get("price") is None:
        sys.exit("This deal has no calculator results yet. Run its full report, or ./run.sh %s terms prices." % name)
    grid = (c.get("price_grid") or [None])[0]
    if grid:
        gain, loss = grid["gain"], -grid["loss"]
    elif c.get("spread_pct") is not None and c.get("break_loss_pct") is not None:
        gain, loss = c["spread_pct"], -c["break_loss_pct"]
    else:
        sys.exit("The calculator needs a deal value and a price if the deal fails before sizing can work.")
    pred = my_prediction(name)
    if chance_arg is not None:
        p, source = float(chance_arg) / (100.0 if float(chance_arg) > 1 else 1.0), "the chance you gave"
    elif pred:
        p, source = pred["you"], "your prediction %s" % pred["id"]
    elif c.get("p_close") is not None:
        p, source = c["p_close"], "the report's estimate"
    else:
        p, source = c.get("implied_prob") or 0.5, "the market's implied odds, which by definition give no edge"
    isa = setting("ISA_VALUE", 0)
    cap = setting("MAX_POSITION_PCT", 25) / 100.0
    reserve = setting("CASH_RESERVE_PCT", 20) / 100.0
    fee = setting("TRADE_COST_GBP", 3)
    q = 1 - p
    ev = p * gain - q * loss
    kelly = (p * gain - q * loss) / (gain * loss) if gain > 0 and loss > 0 else 0.0
    half = max(0.0, kelly / 2.0)
    frac = min(half, cap)
    binary = (finder.load_json(os.path.join(deal, "out", "calc.json"), {}).get("terms") or {}).get("kind") == "binary decision"
    win, lose, event = ("is approved", "is rejected", "approval") if binary else ("completes", "fails", "completion")
    L = ["## Sizing from the calculator", "",
         "If it %s you make %s, and if it %s you lose %s, at today's price including buying costs. "
         "Using %s, a %s chance of %s, the expected return is %s." % (
             win, calc.pct(gain), lose, calc.pct(loss), source, calc.pct(p), event, calc.pct(ev)), ""]
    if ev <= 0:
        L += ["With these odds the expected return is not positive, so the calculator suggests no position. "
              "It becomes positive above a %s chance of %s." % (calc.pct(loss / (gain + loss)), event), ""]
        frac = 0.0
    else:
        L += ["The Kelly share is %s of the account, and the kit uses half of that, %s, capped at the %s limit for one "
              "situation, which gives %s." % (calc.pct(kelly), calc.pct(half), calc.pct(cap), calc.pct(frac)), ""]
    if isa > 0 and frac > 0:
        amount = min(frac * isa, isa * (1 - reserve))
        cur = (c.get("currency") or "USD").upper()
        price = c["price"]
        per_share = price / 100.0 if cur == "GBX" else price
        if cur == "USD":
            fx = setting("GBPUSD", 0)
            if not fx:
                L += ["Set GBPUSD in settings to turn this into a number of US shares.", ""]
                per_share = None
            else:
                per_share = per_share / fx
        if per_share:
            shares = max(0, int((amount - fee) / (per_share * (1 + (c.get("costs_pct") or 0) / 100.0))))
            spend = shares * per_share * (1 + (c.get("costs_pct") or 0) / 100.0) + fee
            cost_share = (fee + shares * per_share * (c.get("costs_pct") or 0) / 100.0) / spend if spend else None
            L += ["| Item | Value |", "|---|---|",
                  "| ISA value in settings | £%.2f |" % isa,
                  "| Suggested stake | £%.2f |" % amount,
                  "| Shares at today's price | %d |" % shares,
                  "| Total cost including fees and stamp duty | £%.2f |" % spend,
                  "| Costs as a share of the stake | %s |" % calc.pct(cost_share), ""]
            if cost_share is not None and cost_share > 0.02:
                L += ["Costs are over 2% of this stake, which eats a large part of a small spread. "
                      "A bigger pot or a wider spread would make it worthwhile.", ""]
    elif isa <= 0:
        L += ["Set ISA_VALUE in settings to turn this into pounds and shares.", ""]
    out = os.path.join(deal, "out", "sizing-calc.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L).rstrip() + "\n")
    print("\n".join(L).rstrip())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
