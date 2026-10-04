#!/usr/bin/env python3
"""Download the official documents that a model found for a company outside EDGAR.

The model only finds the links, in a step where it can browse but can't touch
your account. This script does the downloading, keeps PDFs and web pages only,
and skips anything it already has.

Usage: webdocs.py DEAL LINKS_FILE
LINKS_FILE holds JSON lines with url, title, date and kind.
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finder  # noqa: E402

MAX_DOCS = 30
MAX_BYTES = 40 * 1024 * 1024


def slug(s, n):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:n] or "doc"


def main(deal, links):
    filings = os.path.join(deal, "filings")
    os.makedirs(filings, exist_ok=True)
    mpath = os.path.join(filings, ".gathered.json")
    manifest = finder.load_json(mpath, {"files": {}})
    have = set(v.get("url") for v in manifest["files"].values())
    rows, seen = [], set()
    for line in open(links, encoding="utf-8", errors="replace"):
        m = re.search(r"\{.*\}", line)
        if not m:
            continue
        try:
            r = json.loads(m.group(0))
        except ValueError:
            continue
        url = str(r.get("url") or "").strip()
        if not re.match(r"^https?://", url) or url in seen:
            continue
        seen.add(url)
        rows.append(r)
    added, failed = 0, []
    for r in rows[:MAX_DOCS]:
        url = r["url"].strip()
        if url in have:
            continue
        try:
            body = finder.get(url, limit=MAX_BYTES, sec=False)
        except Exception as e:
            failed.append("%s (%s)" % (r.get("title") or url, e))
            continue
        if not body:
            failed.append("%s (not found)" % (r.get("title") or url))
            continue
        head = body[:2048].lower()
        if body[:5] == b"%PDF-":
            ext = ".pdf"
        elif b"<html" in head or b"<!doctype html" in head or b"<body" in head:
            ext = ".htm"
        else:
            failed.append("%s (not a PDF or web page)" % (r.get("title") or url))
            continue
        date = str(r.get("date") or "")[:10] or "undated"
        name = "%s_%s_%s%s" % (date, slug(r.get("kind"), 20), slug(r.get("title"), 50), ext)
        with open(os.path.join(filings, name), "wb") as fh:
            fh.write(body)
        manifest["files"][name] = {"url": url, "title": r.get("title", ""), "date": date, "kind": r.get("kind", ""),
                                   "saved": datetime.date.today().isoformat()}
        added += 1
    finder.save_json(mpath, manifest)
    finder.say("web docs    %d document%s saved, %d failed" % (added, "" if added == 1 else "s", len(failed)))
    for f in failed[:8]:
        finder.say("            could not save %s" % f)
    if failed:
        finder.say("            anything that failed can be downloaded by hand into %s" % os.path.relpath(filings, finder.KIT))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(os.path.abspath(sys.argv[1]), sys.argv[2])
