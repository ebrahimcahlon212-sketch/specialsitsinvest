#!/usr/bin/env python3
"""Put a section into a report.

Usage: insert_section.py REPORT SECTION OUT [--heading TEXT] [--top]

Without --heading this handles section 11, Position and sizing. The report's
existing section with that heading is replaced. If there is none, the section
goes before the first numbered section with --top, and otherwise before the
Sources section or at the end.
"""
import re
import sys

SOURCES = re.compile(r"^##\s+(13\.?\s*)?sources\b", re.I)


def main():
    args = sys.argv[1:]
    top = "--top" in args
    args = [a for a in args if a != "--top"]
    heading = "Position and sizing"
    if "--heading" in args:
        i = args.index("--heading")
        heading = args[i + 1]
        del args[i:i + 2]
    if len(args) != 3:
        sys.exit(__doc__)
    report_path, section_path, out_path = args
    pattern = re.compile(r"^##\s+(\d+\.?\s*)?" + re.escape(heading) + r"\b", re.I)
    default = "## 11. Position and sizing" if heading == "Position and sizing" else "## " + heading
    report = open(report_path, encoding="utf-8").read().splitlines()
    section = open(section_path, encoding="utf-8").read().strip().splitlines()
    if not section or not pattern.match(section[0]):
        section = [default, ""] + section

    out, i, placed = [], 0, False
    while i < len(report):
        line = report[i]
        if not placed and pattern.match(line):
            out.extend(section)
            out.append("")
            i += 1
            while i < len(report) and not report[i].startswith("## "):
                i += 1
            placed = True
            continue
        out.append(line)
        i += 1

    if not placed:
        if top:
            idx = next((k for k, ln in enumerate(out) if ln.startswith("## ")), len(out))
        else:
            idx = next((k for k, ln in enumerate(out) if SOURCES.match(ln)), len(out))
        out[idx:idx] = section + [""]

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip() + "\n")


if __name__ == "__main__":
    main()
