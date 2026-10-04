#!/usr/bin/env python3
"""Idea log. Capture ideas quickly, and keep the results of checking them.

Usage
  ideas.py add TEXT...          save an idea and print its ID
  ideas.py saved ID FILE        record that the check for ID was written to FILE
  ideas.py list                 print every idea with its verdict, and write journal/ideas.md
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finder  # noqa: E402

JDIR = os.path.join(finder.KIT, "journal")
IDEAS = os.path.join(JDIR, "ideas.jsonl")


def read():
    rows = []
    if os.path.exists(IDEAS):
        for line in open(IDEAS, encoding="utf-8"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def write(rows):
    os.makedirs(JDIR, exist_ok=True)
    with open(IDEAS, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def cmd_add(text, deal=""):
    rows = read()
    iid = "I%03d" % (len(rows) + 1)
    row = {"id": iid, "time": datetime.datetime.now().isoformat(timespec="seconds"), "idea": text, "deal": deal,
           "verdict": "", "check": ""}
    rows.append(row)
    write(rows)
    try:
        import ledger
        ledger.append("idea", {"id": iid, "idea": text, "deal": deal})
        ledger.stamp(quiet=True)
    except Exception:
        pass
    print(iid)


def cmd_saved(iid, path):
    rows = read()
    text = open(path, encoding="utf-8", errors="replace").read()
    verdict = ""
    for v in ("Known and still works", "Known but no longer works", "Looks new and plausible", "Looks new but blocked",
              "Needs legal advice before trying"):
        if re.search(re.escape(v), text, re.I):
            verdict = v
    for r in rows:
        if r["id"] == iid:
            r["check"] = os.path.relpath(path, finder.KIT)
            r["verdict"] = verdict or "see the check"
    write(rows)


def cmd_list():
    rows = read()
    L = ["# Ideas", "", "| ID | Date | Idea | Verdict | Check |", "|---|---|---|---|---|"]
    for r in rows:
        L.append("| %s | %s | %s | %s | %s |" % (r["id"], r["time"][:10], r["idea"].replace("|", "/")[:160],
                                                r.get("verdict") or "not checked", r.get("check") or ""))
    os.makedirs(JDIR, exist_ok=True)
    with open(os.path.join(JDIR, "ideas.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "add":
        deal = ""
        if "--deal" in a:
            i = a.index("--deal")
            deal = a[i + 1] if i + 1 < len(a) else ""
            a = a[:i] + a[i + 2:]
        cmd_add(" ".join(a[1:]).strip(), deal)
    elif len(a) == 3 and a[0] == "saved":
        cmd_saved(a[1], a[2])
    elif a and a[0] == "list":
        cmd_list()
    else:
        sys.exit(__doc__)
