#!/usr/bin/env python3
"""Decision journal.

Every situation you look at gets a decision and a reason. Later, when it
resolves, you record the outcome. The summary then shows how many situations
were screened and researched, how often you invested, how the tool's
probabilities compared with what happened, and how the ones you passed on
turned out, which is the direct test of whether the tool is too cautious.

Decisions are also added to the ledger's hash chain, so the record can't be
quietly rewritten later.

Usage
  journal.py decide ID DECISION REASON...   DECISION is invest, pass or watch. ID is a deal name or a card ID
  journal.py resolve ID OUTCOME NOTE...     OUTCOME is completed, failed or other
  journal.py summary                        print the summary and write journal/summary.md
  journal.py watch [MIN_PER_YEAR_PCT]       table of open deals with today's numbers and alerts
"""
import datetime
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finder  # noqa: E402

KIT = finder.KIT
JDIR = os.path.join(KIT, "journal")
DECISIONS = os.path.join(JDIR, "decisions.jsonl")
OUTCOMES = os.path.join(JDIR, "outcomes.jsonl")


def read_jsonl(path):
    rows = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return rows


def append_jsonl(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    try:
        import ledger
        ledger.append("decision" if path == DECISIONS else "outcome", row)
        ledger.stamp(quiet=True)
    except Exception:
        pass


def deal_context(name):
    deal = os.path.join(KIT, "deals", name)
    if not os.path.isdir(deal):
        return None
    info = finder.load_json(os.path.join(deal, "deal.json"), {})
    ctx = {"kind": "deal", "company": info.get("company") or name, "ticker": info.get("ticker") or "",
           "category": info.get("category") or "", "source": info.get("source") or ""}
    calc = finder.load_json(os.path.join(deal, "out", "calc.json"), {}).get("results") or {}
    if calc:
        s0 = (calc.get("scenarios") or [{}])[0]
        ctx.update({"price": calc.get("price"), "spread_pct": calc.get("spread_pct"), "per_year": s0.get("per_year"),
                    "p_est": calc.get("p_close"), "implied_prob": calc.get("implied_prob"),
                    "expected_return": calc.get("expected_return")})
    return ctx


def card_context(cid):
    for path in sorted(glob.glob(os.path.join(finder.FINDER, "*", "candidates.json")), reverse=True):
        out = os.path.dirname(path)
        for rec in finder.load_json(path, {}).get("new", []):
            if rec.get("id", "").lower() == cid.lower():
                card = finder.read_cards(out).get(rec["id"], {})
                return {"kind": "card", "company": rec.get("company"), "ticker": rec.get("ticker") or "",
                        "category": rec.get("category"), "score": finder.score_of(card) if card else None,
                        "price": (rec.get("quote") or {}).get("price")}
    for name in ("uk.json", "uk_events.json"):
        for path in sorted(glob.glob(os.path.join(finder.FINDER, "*", name)), reverse=True):
            out = os.path.dirname(path)
            for rec in finder.load_json(path, {}).get("new", []):
                if rec.get("id", "").lower() == cid.lower():
                    card = rec.get("card") or finder.read_cards(out).get(rec["id"], {})
                    return {"kind": "card", "company": rec.get("company"), "ticker": rec.get("ticker") or card.get("ticker", ""),
                            "category": rec.get("category"), "score": finder.score_of(card) if card else None,
                            "price": (rec.get("quote") or {}).get("price")}
    return None


def cmd_decide(sid, decision, reason):
    decision = decision.lower()
    if decision not in ("invest", "pass", "watch"):
        sys.exit("The decision must be invest, pass or watch.")
    ctx = deal_context(sid) or card_context(sid)
    if ctx is None:
        sys.exit("No deal folder or card called %s." % sid)
    row = dict(ctx, time=datetime.datetime.now().isoformat(timespec="seconds"), id=sid, decision=decision, reason=reason)
    append_jsonl(DECISIONS, row)
    finder.say("logged    %s, %s. %s" % (sid, decision, reason))


def cmd_resolve(sid, outcome, note):
    outcome = outcome.lower()
    if outcome not in ("completed", "failed", "other"):
        sys.exit("The outcome must be completed, failed or other.")
    if sid not in latest_by_id(read_jsonl(DECISIONS)):
        finder.say("note      no decision was logged for %s, so this outcome won't count towards the trade rate" % sid)
    append_jsonl(OUTCOMES, {"time": datetime.datetime.now().isoformat(timespec="seconds"), "id": sid,
                            "outcome": outcome, "note": note})
    finder.say("resolved  %s, %s" % (sid, outcome))


def latest_by_id(rows):
    out = {}
    for r in rows:
        out[r["id"]] = r
    return out


def screened_count():
    ids = set()
    for out in glob.glob(os.path.join(finder.FINDER, "20*")):
        ids.update(finder.read_cards(out).keys())
        for e in finder.load_json(os.path.join(out, "uk_events.json"), {"new": []})["new"]:
            ids.add(e["id"])
    return len(ids)


def researched_count():
    n = 0
    for d in glob.glob(os.path.join(KIT, "deals", "*")):
        if os.path.exists(os.path.join(d, "out", "report.md")) or os.path.exists(os.path.join(d, "out", "fundamentals.md")):
            n += 1
    return n


def pct(x):
    return "n/a" if x is None else "%.1f%%" % (x * 100)


def cmd_summary():
    decisions = latest_by_id(read_jsonl(DECISIONS))
    outcomes = latest_by_id(read_jsonl(OUTCOMES))
    screened, researched = screened_count(), researched_count()
    by = {"invest": [], "pass": [], "watch": []}
    for d in decisions.values():
        by.setdefault(d["decision"], []).append(d)
    L = ["# Decision journal", "", "Updated %s." % datetime.date.today().isoformat(), "",
         "| Stage | Count |", "|---|---|",
         "| Cards screened by the finder | %d |" % screened,
         "| Situations researched in full | %d |" % researched,
         "| Decisions logged | %d |" % len(decisions),
         "| Invested | %d |" % len(by["invest"]),
         "| Passed | %d |" % len(by["pass"]),
         "| Watching | %d |" % len(by["watch"]), ""]
    if researched:
        L.append("Trade rate is %s of situations researched in full and %s of cards screened." % (
            pct(len(by["invest"]) / float(researched)), pct(len(by["invest"]) / float(screened)) if screened else "n/a"))
        L.append("")
    # How passes turned out is the direct test of caution
    resolved_passes = [(d, outcomes[d["id"]]) for d in by["pass"] if d["id"] in outcomes]
    if resolved_passes:
        missed = [d for d, o in resolved_passes if o["outcome"] == "completed"]
        L += ["Of %d passes that have resolved, %d completed anyway, meaning a buyer at your decision price would "
              "have been paid out, and %d failed. Many completed passes would suggest the tool and you are too cautious." % (
                  len(resolved_passes), len(missed), len(resolved_passes) - len(missed)), ""]
    # Calibration of the tool's own probabilities
    pairs = [(d["p_est"], 1.0 if outcomes[d["id"]]["outcome"] == "completed" else 0.0)
             for d in decisions.values() if d.get("p_est") is not None and d["id"] in outcomes
             and outcomes[d["id"]]["outcome"] in ("completed", "failed")]
    if pairs:
        brier = sum((p - o) ** 2 for p, o in pairs) / len(pairs)
        L += ["## How well the probabilities held up", "",
              "Brier score %.3f over %d resolved situations. Lower is better, and always guessing 50%% scores 0.25." % (brier, len(pairs)), "",
              "| Tool's estimate | Situations | Average estimate | Actually completed |", "|---|---|---|---|"]
        for lo, hi in ((0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 1.01)):
            b = [(p, o) for p, o in pairs if lo <= p < hi]
            if b:
                L.append("| %d%% to %d%% | %d | %s | %s |" % (lo * 100, min(hi, 1) * 100, len(b), pct(sum(p for p, _ in b) / len(b)),
                                                            pct(sum(o for _, o in b) / len(b))))
        L += ["", "If situations keep completing more often than estimated, the tool is too cautious, and the other way round.", ""]
    L += ["## Every decision", "", "| Date | Situation | Decision | Price | Per year then | Chance, tool | Chance, market | Reason | Outcome |",
          "|---|---|---|---|---|---|---|---|---|"]
    for d in sorted(decisions.values(), key=lambda r: r["time"], reverse=True):
        o = outcomes.get(d["id"], {})
        L.append("| %s | %s (%s) | %s | %s | %s | %s | %s | %s | %s |" % (
            d["time"][:10], d.get("company") or d["id"], d["id"], d["decision"], d.get("price") if d.get("price") is not None else "",
            pct(d.get("per_year")), pct(d.get("p_est")), pct(d.get("implied_prob")), (d.get("reason") or "").replace("|", "/"),
            o.get("outcome", "open")))
    os.makedirs(JDIR, exist_ok=True)
    text = "\n".join(L) + "\n"
    with open(os.path.join(JDIR, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


def cmd_watch(min_py):
    decisions = latest_by_id(read_jsonl(DECISIONS))
    outcomes = latest_by_id(read_jsonl(OUTCOMES))
    rows = []
    for d in sorted(glob.glob(os.path.join(KIT, "deals", "*"))):
        name = os.path.basename(d)
        if name in outcomes or (decisions.get(name, {}).get("decision") == "pass"):
            continue
        calc = finder.load_json(os.path.join(d, "out", "calc.json"), {}).get("results") or {}
        if not calc or calc.get("price") is None:
            continue
        s0 = (calc.get("scenarios") or [{}])[0]
        py, ev, imp, est = s0.get("per_year"), calc.get("expected_return"), calc.get("implied_prob"), calc.get("p_close")
        alerts = []
        if py is not None and py >= min_py / 100.0 and (ev is None or ev > 0):
            alerts.append("return above %d%% a year" % min_py)
        if imp is not None and est is not None and imp < est - 0.10:
            alerts.append("market odds %s below the report's %s" % (pct(imp), pct(est)))
        rows.append((name, calc, py, ev, imp, est, alerts))
    if not rows:
        print("No open deals with calculated numbers yet. Deals get them from a full report or ./run.sh NAME terms prices.")
        return
    print("| Deal | Price | Spread | Per year | Expected return | Market odds | Report odds | Alert |")
    print("|---|---|---|---|---|---|---|---|")
    for name, c, py, ev, imp, est, alerts in rows:
        print("| %s | %s | %s | %s | %s | %s | %s | %s |" % (name, c.get("price"), pct(c.get("spread_pct")), pct(py), pct(ev),
                                                          pct(imp), pct(est), "; ".join(alerts) or ""))
    hits = [r for r in rows if r[6]]
    print("")
    print("%d of %d open deals flagged." % (len(hits), len(rows)) if hits else "Nothing flagged today.")


PREDICTIONS = os.path.join(JDIR, "predictions.jsonl")
SETTLED = os.path.join(JDIR, "prediction_outcomes.jsonl")


def as_prob(v):
    try:
        x = float(str(v).strip().rstrip("%"))
    except ValueError:
        sys.exit("Give probabilities as a number like 70 or 0.7.")
    return x / 100.0 if x > 1 else x


def cmd_predict(args):
    opts, words = {}, []
    i = 0
    while i < len(args):
        if args[i] in ("--market", "--tool", "--by", "--deal") and i + 1 < len(args):
            opts[args[i][2:]] = args[i + 1]
            i += 2
        else:
            words.append(args[i])
            i += 1
    if len(words) < 2:
        sys.exit('Use ./run.sh predict "question" YOUR_CHANCE [--market X] [--tool X] [--by YYYY-MM-DD] [--deal NAME]')
    you = as_prob(words[-1])
    question = " ".join(words[:-1]).strip()
    n = len(read_jsonl(PREDICTIONS)) + 1
    row = {"id": "P%03d" % n, "time": datetime.datetime.now().isoformat(timespec="seconds"), "question": question, "you": you,
           "market": as_prob(opts["market"]) if "market" in opts else None, "tool": as_prob(opts["tool"]) if "tool" in opts else None,
           "by": opts.get("by", ""), "deal": opts.get("deal", "")}
    os.makedirs(JDIR, exist_ok=True)
    with open(PREDICTIONS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    try:
        import ledger
        ledger.append("prediction", row)
        ledger.stamp(quiet=True)
    except Exception:
        pass
    finder.say("logged    %s. %s, you %s%s%s" % (row["id"], question, pct(you),
                                                ", market %s" % pct(row["market"]) if row["market"] is not None else "",
                                                ", tool %s" % pct(row["tool"]) if row["tool"] is not None else ""))


def cmd_settle(pid, answer, note):
    answer = answer.lower()
    if answer not in ("yes", "no"):
        sys.exit("Settle a prediction with yes or no.")
    row = {"id": pid.upper(), "time": datetime.datetime.now().isoformat(timespec="seconds"), "answer": answer, "note": note}
    os.makedirs(JDIR, exist_ok=True)
    with open(SETTLED, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    try:
        import ledger
        ledger.append("prediction outcome", row)
        ledger.stamp(quiet=True)
    except Exception:
        pass
    finder.say("settled   %s, %s" % (row["id"], answer))


def cmd_withdraw(pid, note):
    pid = pid.upper()
    if pid not in latest_by_id(read_jsonl(PREDICTIONS)):
        sys.exit("No prediction called %s." % pid)
    row = {"id": pid, "time": datetime.datetime.now().isoformat(timespec="seconds"), "answer": "withdrawn", "note": note}
    os.makedirs(JDIR, exist_ok=True)
    with open(SETTLED, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    try:
        import ledger
        ledger.append("prediction withdrawn", row)
        ledger.stamp(quiet=True)
    except Exception:
        pass
    finder.say("withdrew  %s. It stays in the record but won't be scored" % pid)


def question_key(p):
    return re.sub(r"[^a-z0-9]+", " ", p["question"].lower()).strip()


def cmd_predictions():
    preds = latest_by_id(read_jsonl(PREDICTIONS))
    done = latest_by_id(read_jsonl(SETTLED))
    live = [p for p in preds.values() if done.get(p["id"], {}).get("answer") != "withdrawn"]
    newest = {}
    for p in sorted(live, key=lambda r: (r["time"], r["id"])):
        newest[question_key(p)] = p
    newest_ids = set(p["id"] for p in newest.values())
    L = ["# Predictions", "", "Only your latest prediction on each question is scored. Earlier ones stay in the record, "
         "so you can see how your view changed.", "",
         "| ID | Question | By | You | Market | Tool | Result |", "|---|---|---|---|---|---|---|"]
    for p in sorted(preds.values(), key=lambda r: r["id"]):
        state = done.get(p["id"], {}).get("answer", "open")
        if state != "withdrawn" and p["id"] not in newest_ids:
            state = "updated by %s" % newest[question_key(p)]["id"]
        elif state == "open" and newest.get(question_key(p), {}).get("id") == p["id"]:
            answered = [done[q["id"]]["answer"] for q in live if question_key(q) == question_key(p)
                        and done.get(q["id"], {}).get("answer") in ("yes", "no")]
            state = answered[0] if answered else "open"
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (p["id"], p["question"].replace("|", "/"), p.get("by") or "",
                                                         pct(p["you"]), pct(p.get("market")), pct(p.get("tool")), state))
    outcome = {}
    for p in live:
        a = done.get(p["id"], {}).get("answer")
        if a in ("yes", "no"):
            outcome[question_key(p)] = a
    scored = [(p, 1.0 if outcome[k] == "yes" else 0.0) for k, p in newest.items() if k in outcome]
    L.append("")
    if scored:
        L += ["## Scores", "", "Brier score, lower is better. Always saying 50% scores 0.25.", "",
              "| Who | Predictions scored | Brier score |", "|---|---|---|"]
        for who in ("you", "market", "tool"):
            pairs = [(p[who], o) for p, o in scored if p.get(who) is not None]
            if pairs:
                L.append("| %s | %d | %.3f |" % ({"you": "You", "market": "Market", "tool": "Tool"}[who], len(pairs),
                                                sum((x - o) ** 2 for x, o in pairs) / len(pairs)))
        both = [(p["you"], p["market"], o) for p, o in scored if p.get("market") is not None]
        if both:
            beat = sum(1 for y, m, o in both if (y - o) ** 2 < (m - o) ** 2)
            L += ["", "You were closer than the market on %d of %d predictions where both were recorded." % (beat, len(both))]
        L.append("")
    else:
        L += ["No predictions have been settled yet. Settle one with ./run.sh settle ID yes or no.", ""]
    text = "\n".join(L) + "\n"
    os.makedirs(JDIR, exist_ok=True)
    with open(os.path.join(JDIR, "predictions.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


def main():
    a = sys.argv[1:]
    if a and a[0] == "predict":
        return cmd_predict(a[1:])
    if len(a) >= 3 and a[0] == "settle":
        return cmd_settle(a[1], a[2], " ".join(a[3:]).strip())
    if len(a) >= 2 and a[0] == "withdraw":
        return cmd_withdraw(a[1], " ".join(a[2:]).strip() or "withdrawn")
    if a and a[0] == "predictions":
        return cmd_predictions()
    if len(a) >= 3 and a[0] == "decide":
        cmd_decide(a[1], a[2], " ".join(a[3:]).strip() or "no reason given")
    elif len(a) >= 3 and a[0] == "resolve":
        cmd_resolve(a[1], a[2], " ".join(a[3:]).strip())
    elif a and a[0] == "summary":
        cmd_summary()
    elif a and a[0] == "watch":
        cmd_watch(float(a[1]) if len(a) > 1 else 20.0)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
