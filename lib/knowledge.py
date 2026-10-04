#!/usr/bin/env python3
"""The kit's knowledge notebook, a memory that carries across deals.

Lessons worth keeping, such as regulator habits, precedents, base rates, methods
and data pitfalls, live as plain Markdown notes in knowledge/, one per topic,
with an index that every step can read. New lessons are appended with their
source and date, so nothing earlier is overwritten and every claim can be traced.

Usage
  knowledge.py seed              create knowledge/ from the starting notes, if it doesn't exist yet
  knowledge.py ensure            add any starting notes that are missing, keeping existing ones
  knowledge.py index             rebuild knowledge/INDEX.md
  knowledge.py merge FILE DEAL   add the lessons in a model's reply, attributed to DEAL
"""
import datetime
import glob
import json
import os
import re
import shutil
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KDIR = os.path.join(KIT, "knowledge")
SEEDS = os.path.join(KIT, "templates", "knowledge")
TODAY = datetime.date.today().isoformat()


def notes():
    return sorted(p for p in glob.glob(os.path.join(KDIR, "*.md")) if os.path.basename(p) != "INDEX.md")


def meta(path):
    text = open(path, encoding="utf-8").read()
    title = re.search(r"^#\s+(.+)$", text, re.M)
    topics = re.search(r"^Topics:\s*(.+)$", text, re.M)
    updated = re.search(r"^Updated:\s*(.+)$", text, re.M)
    lessons = len(re.findall(r"^\s*-\s", text, re.M))
    return {"name": os.path.splitext(os.path.basename(path))[0], "title": title.group(1).strip() if title else "",
            "topics": topics.group(1).strip() if topics else "", "updated": updated.group(1).strip() if updated else "",
            "lessons": lessons}


def cmd_index(quiet=False):
    os.makedirs(KDIR, exist_ok=True)
    L = ["# Knowledge notebook", "",
         "Lessons carried across deals, one note per topic. Each lesson names its source, so treat these as starting points "
         "to check against the documents for the deal in hand, not as facts about it.", "",
         "| Note | Topics | Lessons | Updated |", "|---|---|---|---|"]
    for p in notes():
        m = meta(p)
        L.append("| [%s](%s.md) | %s | %d | %s |" % (m["title"] or m["name"], m["name"], m["topics"], m["lessons"], m["updated"]))
    with open(os.path.join(KDIR, "INDEX.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    if not quiet:
        print("  knowledge   %d notes in knowledge/" % len(notes()))


def cmd_ensure():
    """Add any starting notes that are missing, without touching notes that already exist."""
    os.makedirs(KDIR, exist_ok=True)
    added = 0
    for p in glob.glob(os.path.join(SEEDS, "*.md")):
        dest = os.path.join(KDIR, os.path.basename(p))
        if not os.path.exists(dest):
            shutil.copy2(p, dest)
            added += 1
    if added:
        cmd_index(quiet=True)


def cmd_seed():
    if os.path.isdir(KDIR) and notes():
        return
    os.makedirs(KDIR, exist_ok=True)
    for p in glob.glob(os.path.join(SEEDS, "*.md")):
        dest = os.path.join(KDIR, os.path.basename(p))
        if not os.path.exists(dest):
            shutil.copy2(p, dest)
    cmd_index(quiet=True)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60] or "general"


def cmd_merge(path, deal):
    os.makedirs(KDIR, exist_ok=True)
    added, created = 0, []
    grouped = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"\{.*\}", line)
        if not m:
            continue
        try:
            e = json.loads(m.group(0))
        except ValueError:
            continue
        lesson = (e.get("lesson") or "").strip()
        if not lesson:
            continue
        grouped.setdefault(slug(e.get("note")), []).append(e)
    for name, items in grouped.items():
        fpath = os.path.join(KDIR, name + ".md")
        if not os.path.exists(fpath):
            first = items[0]
            with open(fpath, "w", encoding="utf-8") as fh:
                fh.write("# %s\n\nTopics: %s\nUpdated: %s\n" % (first.get("title") or name.replace("-", " ").capitalize(),
                                                             first.get("topics") or "", TODAY))
            created.append(name)
        text = open(fpath, encoding="utf-8").read()
        block = ["", "### From %s, %s" % (deal, TODAY), ""]
        for e in items:
            kind = (e.get("action") or "add").lower()
            prefix = "Correction to an earlier lesson. " if kind == "correct" else ""
            src = (" Source: %s." % e["source"].rstrip(".")) if e.get("source") else ""
            conf = (" Confidence %s." % e["confidence"]) if e.get("confidence") else ""
            block.append("- %s%s%s%s" % (prefix, e["lesson"].rstrip(), src, conf))
            added += 1
        text = re.sub(r"^Updated:.*$", "Updated: %s" % TODAY, text, count=1, flags=re.M)
        with open(fpath, "w", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n" + "\n".join(block) + "\n")
    cmd_index(quiet=True)
    print("  knowledge   %d lessons added%s" % (added, (", new notes " + ", ".join(created)) if created else ""))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "seed":
        cmd_seed()
    elif a and a[0] == "ensure":
        cmd_ensure()
    elif a and a[0] == "index":
        cmd_index()
    elif len(a) == 3 and a[0] == "merge":
        cmd_merge(a[1], a[2])
    else:
        sys.exit(__doc__)
