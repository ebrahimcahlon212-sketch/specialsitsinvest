#!/usr/bin/env python3
"""Map what matters in a deal's documents and push generic wording down the list.

Every document in the deal's work folder is split into sections at its headings.
Each section is scored two ways.
  Specific content, meaning dollar amounts, dates, numbers and checklist terms.
  Generic wording, meaning how much of its language also appears in other
  companies' filings. That comparison uses a library that grows with every deal
  you run, every morning's finder excerpts, and a few recent peer filings that
  the gather step downloads for each new deal.

Sections are labelled material, standard with changes, supporting or generic.
Nothing is removed. The labels only decide what the models read in full first.

Usage
  docmap.py build DEAL            write work/sections.json, work/sections.md and out/docmap-auto.md
  docmap.py learn-deal DEAL       add the deal's documents to the library
  docmap.py learn-finder OUTDIR   add a finder run's excerpts to the library
  docmap.py learn-text ID FILE    add one text file to the library
"""
import datetime
import hashlib
import json
import os
import re
import sqlite3
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY = os.path.join(KIT, "library")
DB = os.path.join(LIBRARY, "boilerplate.sqlite")
SHINGLE = 8
SAMPLE = 4          # keep one shingle in four, chosen by hash, so the library stays small
MIN_SOURCES = 2     # wording seen in at least this many other companies' documents counts as generic

TERMS = [
    "termination fee", "reverse termination", "material adverse", "conditions to", "condition to",
    "financing", "regulatory", "antitrust", "hsr", "cfius", "outside date", "end date", "go-shop",
    "no-shop", "no solicitation", "superior proposal", "match", "appraisal", "dividend", "ticking",
    "collar", "exchange ratio", "election", "proration", "record date", "distribution", "tax matters",
    "section 355", "indemnif", "indebtedness", "credit agreement", "backstop", "rights offering",
    "plan of reorganization", "claims", "recovery", "valuation", "projections", "fairness opinion",
    "background of the", "interests of", "golden parachute", "voting agreement", "support agreement",
    "pro forma", "offer price", "minimum condition", "withdrawal rights", "expiration", "odd lot",
    "restructuring support", "forbearance", "strategic alternatives", "rights agreement", "consideration",
    "spread", "break fee", "specific performance", "separation agreement", "transition services",
]
GENERIC_TITLES = re.compile(
    r"forward.looking|cautionary statement|where you can find|incorporation (of certain documents )?by reference|"
    r"^notices?$|governing law|jurisdiction|jury trial|counterparts|severability|entire agreement|"
    r"^assignment$|^headings$|third.party beneficiar|householding|stockholder proposals|^other matters$|"
    r"^legal matters$|^experts$|table of contents|signatures?$|exhibit index|^index$|annex list", re.I)
NUM = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?%|\b\d[\d,]{2,}(?:\.\d+)?\b")
DATE = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                  r"\s+\d{1,2},?\s+\d{4}\b")
HEADING_PATTERNS = [
    re.compile(r"^(ARTICLE|Article|SECTION|Section|ITEM|Item)\s+[\dIVXLC]+[A-Za-z]?(\.\d+)*\b"),
    re.compile(r"^\d{1,2}(\.\d{1,2}){0,2}\.?\s+[A-Z][A-Za-z0-9 ,;'&()\-/]{2,80}$"),
]


def say(msg):
    print("  " + msg, flush=True)


# ---------------------------------------------------------------------------
# Library of wording seen elsewhere

def db():
    os.makedirs(LIBRARY, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, kind TEXT, added TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS shingles (h INTEGER NOT NULL, src TEXT NOT NULL, "
                "PRIMARY KEY (h, src)) WITHOUT ROWID")
    return con


def words(text):
    return re.findall(r"[a-z]+|#", re.sub(r"\d+(?:[.,]\d+)*", " # ", text.lower()))


def shingles(text):
    w = words(text)
    out = set()
    for i in range(len(w) - SHINGLE + 1):
        h = int.from_bytes(hashlib.blake2b(" ".join(w[i:i + SHINGLE]).encode(), digest_size=8).digest(),
                           "big", signed=True)
        if h % SAMPLE == 0:
            out.add(h)
    return out


def learn(con, src, text, kind):
    if con.execute("SELECT 1 FROM sources WHERE id = ?", (src,)).fetchone():
        return False
    hs = shingles(text)
    con.executemany("INSERT OR IGNORE INTO shingles (h, src) VALUES (?, ?)", [(h, src) for h in hs])
    con.execute("INSERT INTO sources (id, kind, added) VALUES (?, ?, ?)",
                (src, kind, datetime.date.today().isoformat()))
    return True


def library_size(con):
    return con.execute("SELECT COUNT(*) FROM sources").fetchone()[0]


def generic_ratio(con, text, exclude_prefix):
    hs = list(shingles(text))
    if not hs:
        return None
    seen = 0
    for i in range(0, len(hs), 400):
        chunk = hs[i:i + 400]
        q = ("SELECT h FROM shingles WHERE h IN (%s) AND src NOT LIKE ? GROUP BY h HAVING COUNT(DISTINCT src) >= ?"
             % ",".join("?" * len(chunk)))
        seen += len(con.execute(q, chunk + [exclude_prefix + "%", MIN_SOURCES]).fetchall())
    return seen / float(len(hs))


# ---------------------------------------------------------------------------
# Splitting documents into sections

def is_heading(line):
    s = line.strip()
    if not 3 <= len(s) <= 90 or s.endswith((",", ";")):
        return False
    for p in HEADING_PATTERNS:
        if p.match(s):
            return True
    letters = re.sub(r"[^A-Za-z]", "", s)
    return len(letters) >= 5 and letters.isupper() and len(s.split()) <= 12 and not re.search(r"\d{4,}", s)


def doc_lines(work, name, info):
    """Yield (location, text) for every line of a document, location being a page or a line number."""
    folder = os.path.join(work, name)
    tdir = os.path.join(folder, "text")
    if os.path.isdir(tdir):
        for f in sorted(os.listdir(tdir)):
            m = re.match(r"p0*(\d+)\.txt$", f)
            if not m:
                continue
            page = int(m.group(1))
            for line in open(os.path.join(tdir, f), encoding="utf-8", errors="replace"):
                yield ("p", page), line.rstrip()
    else:
        allp = os.path.join(folder, "all.txt")
        if os.path.exists(allp):
            for line in open(allp, encoding="utf-8", errors="replace"):
                m = re.match(r"\[L\.(\d+)\] ?(.*)$", line.rstrip("\n"))
                if m:
                    yield ("L", int(m.group(1))), m.group(2)


def split_sections(lines):
    sections, cur = [], None
    for loc, text in lines:
        if is_heading(text) and (cur is None or len(cur["text"]) > 120):
            if cur:
                sections.append(cur)
            cur = {"title": re.sub(r"\s+", " ", text.strip())[:90], "start": loc, "end": loc, "text": ""}
            continue
        if cur is None:
            cur = {"title": "Opening pages", "start": loc, "end": loc, "text": ""}
        cur["end"] = loc
        if text.strip():
            cur["text"] += text.strip() + "\n"
    if cur:
        sections.append(cur)
    merged = []
    for s in sections:
        if merged and len(s["text"]) < 150:
            merged[-1]["end"] = s["end"]
            merged[-1]["text"] += s["title"] + "\n" + s["text"]
        else:
            merged.append(s)
    return merged


def chunk_by_location(lines, size):
    sections, cur = [], None
    for loc, text in lines:
        key = loc[1] if loc[0] == "p" else (loc[1] - 1) // size
        if cur is None or cur["key"] != key:
            if cur:
                sections.append(cur)
            label = "Page %d" % loc[1] if loc[0] == "p" else "Lines from %d" % loc[1]
            cur = {"title": label, "start": loc, "end": loc, "text": "", "key": key}
        cur["end"] = loc
        if text.strip():
            cur["text"] += text.strip() + "\n"
    if cur:
        sections.append(cur)
    return sections


def cite(doc, loc):
    return "[%s %s.%d]" % (doc, loc[0], loc[1])


def span(doc, s):
    if s["start"] == s["end"]:
        return cite(doc, s["start"])
    if s["start"][0] == "p":
        return "[%s p.%d-%d]" % (doc, s["start"][1], s["end"][1])
    return "[%s L.%d]" % (doc, s["start"][1])


# ---------------------------------------------------------------------------
# build

def classify(con, deal_name, doc, s, use_library):
    text = s["text"]
    low = text.lower()
    size = max(len(text), 1)
    money = len(re.findall(r"\$\s?\d", text))
    dates = len(DATE.findall(text))
    nums = len(NUM.findall(text))
    spec = (money * 3 + dates * 2 + nums) / (size / 1000.0)
    hits = sorted(set(t for t in TERMS if t in low))
    ratio = generic_ratio(con, text, "deal:%s:" % deal_name) if use_library else None
    title_generic = bool(GENERIC_TITLES.search(s["title"]))
    if title_generic and spec < 2 and len(hits) < 2:
        label = "generic"
    elif ratio is not None and ratio >= 0.6 and not hits and spec < 3:
        label = "generic"
    elif ratio is not None and 0.35 <= ratio < 0.85 and hits:
        label = "standard with changes"
    elif len(hits) >= 2 or spec >= 6 or (hits and spec >= 3):
        label = "material"
    else:
        label = "supporting"
    return {"doc": doc, "title": s["title"], "start": list(s["start"]), "end": list(s["end"]),
            "cite": span(doc, s), "label": label, "specific": round(spec, 1),
            "generic_share": None if ratio is None else round(ratio, 2), "terms": hits[:8],
            "chars": len(text), "opening": re.sub(r"\s+", " ", text[:160]).strip()}


def cmd_build(deal):
    deal = os.path.abspath(deal)
    name = os.path.basename(deal)
    work = os.path.join(deal, "work")
    manifest = json.load(open(os.path.join(work, "manifest.json"))) if os.path.exists(os.path.join(work, "manifest.json")) else {}
    con = db()
    use_library = library_size(con) >= MIN_SOURCES
    all_sections = []
    for doc in sorted(manifest):
        lines = list(doc_lines(work, doc, manifest[doc].get("info", {})))
        if not lines:
            continue
        secs = split_sections(lines)
        if len(secs) < 3:
            secs = chunk_by_location(lines, 80)
        for s in secs:
            all_sections.append(classify(con, name, doc, s, use_library))
    with open(os.path.join(work, "sections.json"), "w", encoding="utf-8") as fh:
        json.dump(all_sections, fh, indent=1)

    table = ["# Sections in this deal's documents", "",
             "Automatic labels. The library held %d other documents when this was built%s." % (
                 library_size(con), "" if use_library else ", too few to judge generic wording yet"), "",
             "| Document | Where | Title | Label | Specific | Generic share | Opening words |",
             "|---|---|---|---|---|---|---|"]
    for s in all_sections:
        table.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            s["doc"], s["cite"], s["title"].replace("|", "/"), s["label"], s["specific"],
            "" if s["generic_share"] is None else s["generic_share"], s["opening"][:100].replace("|", "/")))
    with open(os.path.join(work, "sections.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(table) + "\n")

    out = os.path.join(deal, "out")
    os.makedirs(out, exist_ok=True)
    md = ["# Document map (automatic)", "",
          "Built from simple rules and a comparison with %d other documents. The model's map, when it exists, "
          "replaces this one in the report steps." % library_size(con), ""]
    for doc in sorted(set(s["doc"] for s in all_sections)):
        secs = [s for s in all_sections if s["doc"] == doc]
        counts = dict((k, sum(1 for s in secs if s["label"] == k)) for k in
                      ("material", "standard with changes", "supporting", "generic"))
        md += ["## %s" % doc, "",
               "%d sections. %d material, %d standard with changes, %d supporting and %d generic." % (
                   len(secs), counts["material"], counts["standard with changes"], counts["supporting"],
                   counts["generic"]), ""]
        for label in ("material", "standard with changes"):
            items = [s for s in secs if s["label"] == label]
            if items:
                md.append("%s." % label.capitalize())
                md.append("")
                md += ["- %s %s%s" % (s["title"], s["cite"], (" (" + ", ".join(s["terms"][:4]) + ")") if s["terms"] else "")
                       for s in items]
                md.append("")
        gen = [s for s in secs if s["label"] == "generic"]
        if gen:
            md += ["Generic, safe to skim. %s" % "; ".join("%s %s" % (s["title"], s["cite"]) for s in gen[:40]), ""]
    with open(os.path.join(out, "docmap-auto.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    labels = dict((k, sum(1 for s in all_sections if s["label"] == k)) for k in
                  ("material", "standard with changes", "supporting", "generic"))
    say("map         %d sections, %d material, %d standard with changes, %d generic" % (
        len(all_sections), labels["material"], labels["standard with changes"], labels["generic"]))
    if not use_library:
        say("            the library is still small, so generic wording is judged by title rules for now")


def cmd_learn_deal(deal):
    deal = os.path.abspath(deal)
    name = os.path.basename(deal)
    work = os.path.join(deal, "work")
    manifest = json.load(open(os.path.join(work, "manifest.json"))) if os.path.exists(os.path.join(work, "manifest.json")) else {}
    con = db()
    n = 0
    for doc in manifest:
        text = "\n".join(t for _, t in doc_lines(work, doc, {}))
        if text and learn(con, "deal:%s:%s:%s" % (name, doc, manifest[doc].get("fp", {}).get("size", "")), text, "deal"):
            n += 1
    con.commit()
    if n:
        say("library     added %d document%s from this deal, %d in total" % (n, "" if n == 1 else "s", library_size(con)))


def cmd_learn_finder(outdir):
    con = db()
    n = 0
    cands = os.path.join(outdir, "candidates")
    if os.path.isdir(cands):
        for cid in os.listdir(cands):
            meta_p = os.path.join(cands, cid, "meta.json")
            ex_p = os.path.join(cands, cid, "excerpt.txt")
            if not (os.path.exists(meta_p) and os.path.exists(ex_p)):
                continue
            meta = json.load(open(meta_p))
            if learn(con, "finder:%s:%s" % (meta.get("cik"), meta.get("accession")),
                     open(ex_p, encoding="utf-8", errors="replace").read(), "finder"):
                n += 1
    con.commit()
    if n:
        say("library     added %d finder excerpt%s, %d documents in total" % (n, "" if n == 1 else "s", library_size(con)))


def cmd_learn_text(src, path):
    con = db()
    if learn(con, src, open(path, encoding="utf-8", errors="replace").read(), "peer"):
        con.commit()


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "build":
        cmd_build(sys.argv[2])
    elif cmd == "learn-deal":
        cmd_learn_deal(sys.argv[2])
    elif cmd == "learn-finder":
        cmd_learn_finder(sys.argv[2])
    elif cmd == "learn-text" and len(sys.argv) == 4:
        cmd_learn_text(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
