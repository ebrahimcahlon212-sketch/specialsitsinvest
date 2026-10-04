#!/usr/bin/env python3
"""Build one HTML page for reading a deal's reports against the filings.

Usage: build_viewer.py <deal folder>

Writes <deal>/out/viewer.html. Every citation such as [merger_proxy p.47]
becomes a button that opens the cited page image with its text. Figures in
the claim next to each citation are compared with the text of the cited page.
Matches are highlighted, and a citation is marked for checking when none of
the claim's dollar amounts, dates or large numbers appear on that page.

The images of cited pages are embedded, so the file works on its own and can
be opened on a phone.
"""
import base64
import datetime
import html
import json
import os
import re
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_RANGE = 10

# ---------------------------------------------------------------------------
# Numbers in claims and pages

NUM = re.compile(r"(\$\s?)?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\s?%)?"
                 r"(?:\s?(million|billion|thousand|mm|bn|m|b|k)\b)?", re.I)
SCALE = {"thousand": 1e3, "k": 1e3, "million": 1e6, "mm": 1e6, "m": 1e6,
         "billion": 1e9, "bn": 1e9, "b": 1e9}
CALC_WORDS = re.compile(r"\b(spread|annuali[sz]ed|implies|implied|return|expected|"
                        r"probability|odds|weighted|downside|upside|loss|gain|x)\b|[=×÷]", re.I)


WORD = re.compile(r"[a-z0-9][a-z0-9.,%$-]*[a-z0-9%]|[a-z0-9]")


def numbers(text):
    """Return one dict per figure in text.

    key is the value after applying any scale word, alt is the value of the
    digits alone when a scale word was used (tables are often "in millions"),
    anchored marks dollar amounts, years and large numbers, and sig marks the
    figures worth showing and highlighting.
    """
    out = []
    for m in NUM.finditer(text):
        start = m.start()
        if start > 0 and (text[start - 1].isalnum() or text[start - 1] in "._"):
            continue
        dollar, digits, dec, pct, scale = m.groups()
        try:
            base = float(digits.replace(",", "") + (dec or ""))
        except ValueError:
            continue
        v = base * SCALE[scale.lower()] if scale else base
        is_year = not dec and not dollar and not pct and 1900 <= v <= 2100
        anchored = (bool(dollar) or is_year or v >= 1000) and not pct
        sig = anchored or bool(dec) or bool(scale)
        if v < 10 and not sig:
            continue
        out.append({"key": "%.9g" % v, "alt": ("%.9g" % base) if scale else None,
                    "raw": m.group(0).strip(), "anchored": anchored, "sig": sig, "pct": bool(pct)})
    return out


def dedupe(items):
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# ---------------------------------------------------------------------------
# Citations

CITE = re.compile(r"\[([^\[\]\n]{1,300})\](?!\()")
SEG = re.compile(r"^\s*(?:(?P<doc>[A-Za-z0-9][\w.\-]*)\s*,?\s+)?"
                 r"(?P<kind>pp?|pages?|l|lines?)\.?\s*(?P<a>\d+)"
                 r"(?:\s*(?:-|\u2013|to)\s*(?:(?:pp?|l)\.?\s*)?(?P<b>\d+))?\s*$", re.I)
BARE = re.compile(r"^\s*([A-Za-z0-9][\w.\-]*)\s*$")
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])")


class Filings(object):
    def __init__(self, deal):
        self.work = os.path.join(deal, "work")
        path = os.path.join(self.work, "manifest.json")
        self.docs = json.load(open(path)) if os.path.exists(path) else {}
        self.cache = {}

    def resolve(self, name):
        if name in self.docs:
            return name
        low = name.lower()
        for d in self.docs:
            if d.lower() == low:
                return d
        cands = [d for d in self.docs if d.startswith(low) or low.startswith(d) or low in d]
        return cands[0] if len(cands) == 1 else None

    def _find(self, doc, sub, n, exts):
        for w in (3, 4, 5):
            for ext in exts:
                p = os.path.join(self.work, doc, sub, "p%0*d%s" % (w, n, ext))
                if os.path.exists(p):
                    return p
        return None

    def _printed_pages(self, doc):
        """Word sets and plain text for each printed page of an HTML filing, or None if it wasn't printed."""
        key = "printed|" + doc
        if key in self.cache:
            return self.cache[key]
        tdir = os.path.join(self.work, doc, "htext")
        pages = None
        if os.path.isdir(tdir):
            files = sorted(f for f in os.listdir(tdir) if re.match(r"p\d+\.txt$", f))
            pages = []
            for f in files:
                t = open(os.path.join(tdir, f), encoding="utf-8", errors="replace").read().lower()
                pages.append((int(f[1:-4]), set(WORD.findall(t)), re.sub(r"[^a-z0-9]+", "", t)))
        self.cache[key] = pages
        return pages

    def _printed_page(self, doc, n, rows):
        """The printed page a cited HTML line falls on, matched by its distinctive words, or None."""
        pages = self._printed_pages(doc)
        if not pages:
            return None
        text = dict(rows)
        target = text.get(n, "")
        if len(re.sub(r"[^a-z0-9]+", "", target.lower())) < 25:
            target = " ".join(text.get(k, "") for k in (n - 1, n, n + 1))
        low = target.lower()
        last = rows[-1][0] if rows else n
        expected = max(1, round(n / float(max(last, 1)) * len(pages)))
        squeezed = re.sub(r"[^a-z0-9]+", "", low)[:48]
        if len(squeezed) >= 24:
            hits = [num for num, _, flat in pages if squeezed in flat]
            if hits:
                return min(hits, key=lambda num: abs(num - expected))
        words = sorted(set(w for w in WORD.findall(low) if len(w) >= 4 or any(ch.isdigit() for ch in w)),
                       key=len, reverse=True)[:14]
        if len(words) < 2:
            return None
        scored = [(sum(1 for w in words if w in ws), num) for num, ws, _ in pages]
        best = max(sc for sc, _ in scored)
        if best < max(2, 0.6 * len(words)):
            return None
        return min((num for sc, num in scored if sc == best), key=lambda num: abs(num - expected))

    def page(self, doc, kind, n):
        """Return a dict describing one cited page or line, or None if it does not exist."""
        key = "%s|%s|%d" % (doc, kind, n)
        if key in self.cache:
            return self.cache[key]
        entry = None
        if kind == "p":
            tpath = self._find(doc, "text", n, [".txt"])
            ipath = self._find(doc, "pages", n, [".png", ".jpg", ".jpeg"])
            if tpath or ipath:
                text = open(tpath, encoding="utf-8", errors="replace").read() if tpath else ""
                info = self.docs.get(doc, {}).get("info", {})
                ocr = n in info.get("ocr", [])
                low = n in info.get("low", []) and not ocr
                entry = {"key": key, "doc": doc, "kind": "p", "n": n, "text": text,
                         "image": ipath, "label": "%s, page %d" % (doc, n),
                         "note": ("The text of this page came from OCR, so check figures against the image."
                                  if ocr else "This page has no extractable text. Read it from the image."
                                  if low else "")}
        else:
            allp = os.path.join(self.work, doc, "all.txt")
            if os.path.exists(allp):
                rows = []
                for line in open(allp, encoding="utf-8", errors="replace"):
                    m = re.match(r"\[L\.(\d+)\] ?(.*)$", line.rstrip("\n"))
                    if m:
                        rows.append((int(m.group(1)), m.group(2)))
                near = [(k, t) for k, t in rows if n - 12 <= k <= n + 12]
                if any(k == n for k, _ in near):
                    text = "\n".join("%s%6d  %s" % (">" if k == n else " ", k, t) for k, t in near)
                    entry = {"key": key, "doc": doc, "kind": "L", "n": n, "text": text,
                             "image": None, "label": "%s, line %d" % (doc, n),
                             "note": "HTML filing, shown as text. The cited line is marked."}
                    pno = self._printed_page(doc, n, rows)
                    ipath = self._find(doc, "hpages", pno, [".png"]) if pno else None
                    if ipath:
                        entry.update({"image": ipath, "label": "%s, line %d, printed page %d" % (doc, n, pno),
                                      "note": "HTML filing. The cited line is marked in the text, and the printed page "
                                              "it falls on is shown below it."})
        self.cache[key] = entry
        return entry


class Renderer(object):
    def __init__(self, filings):
        self.f = filings
        self.cites = []
        self.used = {}

    # -- citations ----------------------------------------------------------
    def parse(self, inner):
        refs, doc = [], None
        for seg in re.split(r"[;,]", inner):
            if not seg.strip():
                continue
            m = SEG.match(seg)
            if m:
                if m.group("doc"):
                    doc = m.group("doc")
                if not doc:
                    return None
                kind = "L" if m.group("kind").lower().startswith("l") else "p"
                a = int(m.group("a"))
                b = int(m.group("b")) if m.group("b") else a
                refs.append((doc, kind, a, max(a, min(b, a + MAX_RANGE - 1))))
                continue
            bare = BARE.match(seg)
            if bare and self.f.resolve(bare.group(1)):
                doc = bare.group(1)
                continue
            return None
        return refs or None

    def chip(self, inner, refs, claim):
        groups = []
        for doc, kind, a, b in refs:
            real = self.f.resolve(doc)
            pages = [self.f.page(real, kind, n) for n in range(a, b + 1)] if real else []
            groups.append((doc, kind, a, b, real, [p for p in pages if p]))

        # The figure check covers every page cited in the same brackets.
        page_nums = {}
        for g in groups:
            for p in g[5]:
                for f in numbers(p["text"]):
                    page_nums.setdefault(f["key"], set()).add(f["raw"])
        figs = [f for f in numbers(claim) if f["sig"]]
        hits, found, missing = set(), [], []
        anchored_seen = anchored_found = 0
        for f in figs:
            match = f["key"] if f["key"] in page_nums else (f["alt"] if f["alt"] in page_nums else None)
            if f["anchored"]:
                anchored_seen += 1
            if match:
                hits.update(page_nums[match])
                found.append(f["raw"])
                if f["anchored"]:
                    anchored_found += 1
            elif not f["pct"]:
                missing.append(f["raw"])
        flagged = anchored_seen > 0 and anchored_found == 0 and not CALC_WORDS.search(claim)

        chips = []
        for doc, kind, a, b, real, pages in groups:
            idx = len(self.cites)
            label = "%s %s.%s" % (real or doc, kind, a if a == b else "%d-%d" % (a, b))
            if not pages:
                self.cites.append({"label": label, "missing_ref": True})
                chips.append('<span class="cite cite-missing" id="c%d" title="This document or page '
                             'is not in the filings folder">%s</span>' % (idx, html.escape(label)))
                continue
            for p in pages:
                self.used[p["key"]] = p
            self.cites.append({
                "label": label, "keys": [p["key"] for p in pages], "claim": claim.strip(),
                "hits": sorted(hits, key=len, reverse=True), "found": dedupe(found),
                "missing": dedupe(missing), "flagged": flagged})
            cls = "cite cite-check" if flagged else "cite"
            title = "Open %s" % pages[0]["label"]
            if flagged:
                title += ". None of the claim's figures appear in this page's text"
            chips.append('<a class="%s" id="c%d" href="#%s" data-cite="%d" title="%s">%s</a>' % (
                cls, idx, anchor(pages[0]["key"]), idx, html.escape(title, quote=True),
                html.escape(label)))
        return " ".join(chips)

    # -- inline text ----------------------------------------------------------
    def fmt(self, text):
        s = html.escape(text, quote=False)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                   lambda m: '<a href="%s" rel="noopener">%s</a>' % (m.group(2), m.group(1)), s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
        return s

    def inline(self, text, context=None):
        codes = []

        def keep(m):
            codes.append(m.group(1))
            return "\x00%d\x00" % (len(codes) - 1)

        text = re.sub(r"`([^`]+)`", keep, text)
        out, plain, last = [], "", 0
        for m in CITE.finditer(text):
            refs = self.parse(m.group(1))
            if not refs:
                continue
            before = text[last:m.start()]
            out.append(self.fmt(before))
            plain += before
            claim = context if context is not None else last_sentence(plain)
            out.append(self.chip(m.group(1), refs, strip_codes(claim, codes)))
            last = m.end()
        out.append(self.fmt(text[last:]))
        s = "".join(out)
        return re.sub(r"\x00(\d+)\x00", lambda m: "<code>%s</code>" % html.escape(codes[int(m.group(1))]), s)


def strip_codes(text, codes):
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def last_sentence(text):
    parts = [p for p in SENT.split(text) if p.strip()]
    return parts[-1] if parts else text


def strip_cites(text):
    return CITE.sub(" ", text)


def anchor(key):
    return "pg-" + re.sub(r"[^A-Za-z0-9]+", "-", key).strip("-")


# ---------------------------------------------------------------------------
# Markdown blocks

FENCE = re.compile(r"^\s*```")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
ULI = re.compile(r"^(\s*)[-*+]\s+(.*)$")
OLI = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
TSEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
QUOTE = re.compile(r"^\s*>\s?(.*)$")


def indent(s):
    return len(s) - len(s.lstrip(" "))


def is_item(s):
    return bool(ULI.match(s) or OLI.match(s))


def starts_block(lines, i):
    s = lines[i]
    return bool(FENCE.match(s) or HEADING.match(s) or HR.match(s) or QUOTE.match(s) or is_item(s)
                or ("|" in s and i + 1 < len(lines) and TSEP.match(lines[i + 1])))


def split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def render_blocks(lines, r):
    out, i, n = [], 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if FENCE.match(line):
            j, buf = i + 1, []
            while j < n and not FENCE.match(lines[j]):
                buf.append(lines[j])
                j += 1
            out.append('<pre class="code">%s</pre>' % html.escape("\n".join(buf)))
            i = j + 1
            continue
        m = HEADING.match(line)
        if m:
            lvl = min(len(m.group(1)) + 1, 6)
            out.append("<h%d>%s</h%d>" % (lvl, r.inline(m.group(2)), lvl))
            i += 1
            continue
        if HR.match(line):
            out.append("<hr>")
            i += 1
            continue
        if "|" in line and i + 1 < n and TSEP.match(lines[i + 1]):
            head = split_row(line)
            i += 2
            rows = []
            while i < n and lines[i].strip() and "|" in lines[i]:
                rows.append(split_row(lines[i]))
                i += 1
            out.append(render_table(head, rows, r))
            continue
        if QUOTE.match(line):
            buf = []
            while i < n and QUOTE.match(lines[i]):
                buf.append(QUOTE.match(lines[i]).group(1))
                i += 1
            out.append("<blockquote>%s</blockquote>" % render_blocks(buf, r))
            continue
        if is_item(line):
            block, i = render_list(lines, i, r)
            out.append(block)
            continue
        buf = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not starts_block(lines, i):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % r.inline(" ".join(buf)))
    return "\n".join(out)


def render_list(lines, i, r):
    n, base = len(lines), indent(lines[i])
    ordered = bool(OLI.match(lines[i]))
    items = []
    while i < n:
        line = lines[i]
        if not line.strip():
            j = i
            while j < n and not lines[j].strip():
                j += 1
            if j < n and items and indent(lines[j]) > base:
                items[-1][1].append("")
                i += 1
                continue
            if j < n and is_item(lines[j]) and indent(lines[j]) == base:
                i = j
                continue
            break
        if indent(line) == base and is_item(line):
            m = OLI.match(line) or ULI.match(line)
            items.append([m.group(m.lastindex), []])
            i += 1
            continue
        if indent(line) > base and items:
            items[-1][1].append(line)
            i += 1
            continue
        if items and not starts_block(lines, i):
            items[-1][0] += " " + line.strip()
            i += 1
            continue
        break
    parts = []
    for text, sub in items:
        inner = r.inline(text)
        if any(s.strip() for s in sub):
            k = min(indent(s) for s in sub if s.strip())
            inner += render_blocks([s[k:] if s.strip() else "" for s in sub], r)
        parts.append("<li>%s</li>" % inner)
    tag = "ol" if ordered else "ul"
    return "<%s>%s</%s>" % (tag, "".join(parts), tag), i


def render_table(head, rows, r):
    width = len(head)
    th = "".join("<th>%s</th>" % r.inline(c) for c in head)
    body = []
    for row in rows:
        row = (row + [""] * width)[:max(width, len(row))]
        context = " | ".join(x for x in (strip_cites(c).strip() for c in row) if x)
        body.append("<tr>%s</tr>" % "".join("<td>%s</td>" % r.inline(c, context) for c in row))
    return ('<div class="tablewrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
            % (th, "".join(body)))


# ---------------------------------------------------------------------------
# Page assembly

def data_uri(path):
    ext = os.path.splitext(path)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    return "data:%s;base64,%s" % (mime, base64.b64encode(open(path, "rb").read()).decode("ascii"))


def page_sort_key(key):
    doc, kind, n = key.split("|")
    return (doc, kind, int(n))


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: build_viewer.py <deal folder>")
    deal = os.path.abspath(sys.argv[1])
    out_dir = os.path.join(deal, "out")
    deal_name = os.path.basename(deal)

    sources = []
    final = os.path.join(out_dir, "report-with-sizing.md")
    if not os.path.exists(final):
        final = os.path.join(out_dir, "report.md")
    if os.path.exists(final):
        sources.append(("report", "Final report", final))
    if os.path.exists(os.path.join(out_dir, "fundamentals.md")):
        sources.append(("fundamentals", "Fundamentals", os.path.join(out_dir, "fundamentals.md")))
    if os.path.exists(os.path.join(out_dir, "biotech.md")):
        sources.append(("biotech", "FDA decision", os.path.join(out_dir, "biotech.md")))
    if os.path.exists(os.path.join(out_dir, "competition-estimate.md")):
        sources.append(("competition-estimate", "Estimate", os.path.join(out_dir, "competition-estimate.md")))
    if os.path.exists(os.path.join(out_dir, "competition.md")):
        sources.append(("competition", "Competition", os.path.join(out_dir, "competition.md")))
    if os.path.exists(os.path.join(out_dir, "competition-sample.md")):
        sources.append(("competition-sample", "Sample", os.path.join(out_dir, "competition-sample.md")))
    if os.path.exists(os.path.join(out_dir, "overlap.md")):
        sources.append(("overlap", "Overlap", os.path.join(out_dir, "overlap.md")))
    if os.path.exists(os.path.join(out_dir, "angles.md")):
        sources.append(("angles", "Angles", os.path.join(out_dir, "angles.md")))
    if os.path.exists(os.path.join(out_dir, "qa.md")):
        sources.append(("qa", "Questions", os.path.join(out_dir, "qa.md")))
    for fname in ("docmap.md", "docmap-auto.md"):
        if os.path.exists(os.path.join(out_dir, fname)):
            sources.append(("map", "Document map", os.path.join(out_dir, fname)))
            break
    if os.path.exists(os.path.join(out_dir, "draft.md")):
        sources.append(("draft", "Draft", os.path.join(out_dir, "draft.md")))
    if os.path.isdir(out_dir):
        for f in sorted(os.listdir(out_dir)):
            if f.startswith("review-") and f.endswith(".md"):
                model = f[len("review-"):-3]
                label = ("Check by " + model[len("check-"):].capitalize()) if model.startswith("check-") else ("Review by " + model.capitalize())
                sources.append(("review-" + model, label,
                                os.path.join(out_dir, f)))
    if not sources:
        sys.exit("Nothing to show yet. Run the draft step first.")

    filings = Filings(deal)
    r = Renderer(filings)
    sections, title = [], None
    for sid, name, path in sources:
        text = open(path, encoding="utf-8", errors="replace").read()
        if title is None:
            m = re.search(r"^#\s+(.+)$", text, re.M)
            title = m.group(1).strip() if m else None
        start = len(r.cites)
        body = render_blocks(text.splitlines(), r)
        flagged = sum(1 for c in r.cites[start:] if c.get("flagged") or c.get("missing_ref"))
        sections.append({"id": sid, "name": name, "body": body,
                         "count": len(r.cites) - start, "flagged": flagged})

    figures = []
    keys = sorted(r.used, key=page_sort_key)
    by_doc = {}
    for k in keys:
        by_doc.setdefault(k.split("|")[0], []).append(k)
    nav = {}
    for doc, ks in by_doc.items():
        for i, k in enumerate(ks):
            nav[k] = {"prev": ks[i - 1] if i > 0 else None, "next": ks[i + 1] if i + 1 < len(ks) else None}
    total_bytes = 0
    for k in keys:
        p = r.used[k]
        img = ""
        if p["image"]:
            total_bytes += os.path.getsize(p["image"])
            img = '<img src="%s" alt="%s" loading="lazy">' % (data_uri(p["image"]), html.escape(p["label"]))
        figures.append(
            '<figure class="page" id="%s" data-key="%s" data-label="%s" data-note="%s">'
            '<figcaption>%s</figcaption>%s'
            '<details><summary>Page text</summary><pre class="pagetext">%s</pre></details>'
            '</figure>' % (anchor(k), html.escape(k), html.escape(p["label"]), html.escape(p.get("note", "")),
                           html.escape(p["label"]), img,
                           html.escape(p["text"] or "No extractable text on this page.")))

    total = sum(s["count"] for s in sections)
    flagged = sum(s["flagged"] for s in sections)
    meta = "%d citation%s" % (total, "" if total == 1 else "s")
    if flagged:
        meta += ", %d to check" % flagged
    data = {"cites": r.cites, "nav": nav, "sections": [s["id"] for s in sections]}

    tabs = "".join('<button type="button" class="tab" data-sec="%s" aria-pressed="%s">%s%s</button>' % (
        s["id"], "true" if i == 0 else "false", html.escape(s["name"]),
        ' <span class="tabflag" title="%d marked for checking">%d</span>' % (s["flagged"], s["flagged"])
        if s["flagged"] else "") for i, s in enumerate(sections))
    secs = "".join('<section class="doc" id="sec-%s" data-sec="%s"><div class="sectag">%s</div>%s</section>' % (
        s["id"], s["id"], html.escape(s["name"]), s["body"]) for s in sections)

    page = TEMPLATE
    for token, value in (
            ("%%TITLE%%", html.escape(title or deal_name)),
            ("%%DEAL%%", html.escape(deal_name)),
            ("%%META%%", html.escape(meta)),
            ("%%BUILT%%", datetime.date.today().isoformat()),
            ("%%TABS%%", tabs),
            ("%%SECTIONS%%", secs),
            ("%%FIGURES%%", "".join(figures) or "<p>No pages were cited.</p>"),
            ("%%CHECKBTN%%", "" if not flagged else
             '<button type="button" id="nextcheck" class="ghost warnbtn">Next to check</button>'),
            ("%%DATA%%", json.dumps(data).replace("</", "<\\/"))):
        page = page.replace(token, value)
    dest = os.path.join(out_dir, "viewer.html")
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("  viewer      %s (%d cited pages, %.1f MB of images)" % (
        os.path.relpath(dest, KIT), len(keys), total_bytes / 1e6))


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>%%TITLE%%</title>
<script>document.documentElement.classList.add("js")</script>
<style>
:root{--paper:#EEF1F4;--sheet:#FFFFFF;--ink:#18202B;--ink2:#55606E;--rule:#D6DCE3;--flag:#0E6D76;--flagbg:#D9EEEF;--flagink:#08474D;--checkbg:#FBE5BF;--checkink:#6E3900;--missbg:#E7EAEE;--missink:#5B6572;--mark:rgba(255,214,0,.5);--shade:rgba(15,22,30,.45);
--serif:Charter,"Bitstream Charter","Sitka Text",Cambria,Georgia,serif;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;--mono:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#0E1217;--sheet:#161C23;--ink:#E3E8EE;--ink2:#9AA5B2;--rule:#29313B;--flag:#4CC0C9;--flagbg:#113A3F;--flagink:#A7E6EA;--checkbg:#48300D;--checkink:#FFD796;--missbg:#222932;--missink:#A2ACB8;--mark:rgba(255,204,0,.32);--shade:rgba(0,0,0,.6);color-scheme:dark}}
:root[data-theme="dark"]{--paper:#0E1217;--sheet:#161C23;--ink:#E3E8EE;--ink2:#9AA5B2;--rule:#29313B;--flag:#4CC0C9;--flagbg:#113A3F;--flagink:#A7E6EA;--checkbg:#48300D;--checkink:#FFD796;--missbg:#222932;--missink:#A2ACB8;--mark:rgba(255,204,0,.32);--shade:rgba(0,0,0,.6);color-scheme:dark}
*,*::before,*::after{box-sizing:inherit}
html{scroll-padding-top:calc(env(safe-area-inset-top,0px) + 7rem)}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--serif);font-size:17px;line-height:1.62;-webkit-text-size-adjust:100%}
header.top{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--paper);border-bottom:1px solid var(--rule);padding:.8rem 1.1rem .55rem;font-family:var(--sans)}
.top h1{font-size:.98rem;line-height:1.3;margin:0;font-weight:650;letter-spacing:-.005em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.top .meta{display:flex;flex-wrap:wrap;align-items:center;gap:.35rem .8rem;margin:.2rem 0 .55rem;font-size:.8rem;color:var(--ink2)}
.tabs{display:flex;gap:.35rem;overflow-x:auto;scrollbar-width:none;margin:0 -1.1rem;padding:0 1.1rem}
.tabs::-webkit-scrollbar{display:none}
.tab{flex:none;font:600 .82rem/1 var(--sans);color:var(--ink2);background:transparent;border:1px solid var(--rule);border-radius:999px;padding:.5rem .8rem;cursor:pointer}
.tab[aria-pressed="true"]{color:var(--sheet);background:var(--ink);border-color:var(--ink)}
.tabflag{display:inline-block;margin-left:.3rem;min-width:1.2em;padding:.1rem .3rem;border-radius:999px;background:var(--checkbg);color:var(--checkink);font-size:.72rem}
button.ghost{font:600 .76rem/1 var(--sans);color:var(--ink2);background:transparent;border:1px solid var(--rule);border-radius:6px;padding:.32rem .55rem;cursor:pointer}
button.warnbtn{color:var(--checkink);background:var(--checkbg);border-color:transparent}
main{max-width:44rem;margin:0 auto;padding:1.2rem 1.1rem 4rem;transition:margin .25s ease}
.doc{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:1.3rem 1.2rem 1.6rem;margin-bottom:1.4rem}
.sectag{font:600 .75rem/1 var(--sans);color:var(--ink2);margin-bottom:.9rem}
.js .doc{display:none}.js .doc.on{display:block}.js .sectag{display:none}
h2,h3,h4,h5,h6{font-family:var(--sans);line-height:1.25;letter-spacing:-.01em;margin:1.7rem 0 .6rem}
h2{font-size:1.45rem;margin-top:.2rem}h3{font-size:1.1rem;padding-top:.9rem;border-top:1px solid var(--rule)}h4{font-size:1rem}
p,ul,ol{margin:0 0 .95rem}li{margin:.25rem 0}
a{color:var(--flag)}
code,pre.code{font-family:var(--mono);font-size:.82em}
pre.code{background:var(--paper);padding:.8rem;border-radius:6px;white-space:pre-wrap;overflow-wrap:anywhere}
blockquote{margin:0 0 1rem;padding:.1rem 0 .1rem 1rem;border-left:3px solid var(--rule);color:var(--ink2)}
hr{border:0;border-top:1px solid var(--rule);margin:1.5rem 0}
.tablewrap{overflow-x:auto;margin:0 0 1.1rem;border:1px solid var(--rule);border-radius:8px}
table{border-collapse:collapse;width:100%;font:.85rem/1.45 var(--sans);font-variant-numeric:tabular-nums}
th,td{text-align:left;vertical-align:top;padding:.5rem .65rem;border-bottom:1px solid var(--rule);min-width:6.5rem}
@media (max-width:600px){th,td{min-width:5.4rem;padding:.45rem .5rem}.doc{padding:1.1rem .95rem 1.4rem}main{padding:1rem .7rem 3rem}}
th{background:var(--paper);font-weight:650;color:var(--ink2)}
tr:last-child td{border-bottom:0}
.cite{display:inline-block;font:650 .72rem/1.2 var(--sans);text-decoration:none;white-space:nowrap;vertical-align:.12em;padding:.2rem .75rem .2rem .45rem;margin:0 .1rem;background:var(--flagbg);color:var(--flagink);clip-path:polygon(0 0,100% 0,calc(100% - 6px) 50%,100% 100%,0 100%);cursor:pointer}
.cite:hover,.cite:focus-visible{background:var(--flag);color:var(--sheet)}
.cite-check{background:var(--checkbg);color:var(--checkink)}
.cite-check::after{content:" check";font-weight:500}
.cite-missing{background:var(--missbg);color:var(--missink);text-decoration:line-through;cursor:help}
.cite.flash{outline:3px solid var(--flag);outline-offset:2px}
:focus-visible{outline:2px solid var(--flag);outline-offset:2px}
#pages{margin-top:2.2rem}
#pages h2{font-size:1.15rem}
.js #pages{display:none}.js #pages.on{display:block}
figure.page{margin:0 0 1.6rem;background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:.8rem}
figure.page figcaption{font:650 .82rem/1.3 var(--sans);color:var(--ink2);margin-bottom:.6rem}
figure.page img{display:block;width:100%;height:auto;border:1px solid var(--rule);background:#fff}
details summary{font:600 .8rem/1.2 var(--sans);color:var(--ink2);cursor:pointer;margin-top:.6rem}
pre.pagetext{font:.8rem/1.6 var(--sans);white-space:pre-wrap;overflow-wrap:anywhere;overflow-x:hidden;background:var(--paper);padding:.8rem;border-radius:6px;margin:.5rem 0 0;tab-size:2}
mark{background:var(--mark);color:inherit;padding:0 .08em;border-radius:2px}
.focusline{background:var(--mark);display:inline-block;width:100%;white-space:pre-wrap;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.showpages{display:none}.js .showpages{display:inline-block}
.note{font:.8rem/1.5 var(--sans);color:var(--ink2);max-width:44rem;margin:0 auto;padding:0 1.1rem 2rem}
#shade{position:fixed;inset:0;background:var(--shade);opacity:0;pointer-events:none;transition:opacity .2s ease;z-index:8}
#shade.on{opacity:1;pointer-events:auto}
#panel{position:fixed;left:0;right:0;bottom:0;height:86vh;z-index:9;background:var(--sheet);border-top:1px solid var(--rule);border-radius:14px 14px 0 0;transform:translateY(102%);transition:transform .25s ease;display:flex;flex-direction:column;padding-bottom:env(safe-area-inset-bottom,0px);font-family:var(--sans)}
#panel.on{transform:none}
.phead{display:flex;align-items:center;gap:.4rem;padding:.7rem .8rem .6rem 1rem;border-bottom:1px solid var(--rule)}
.phead .ptitle{flex:1;min-width:0;font-weight:650;font-size:.9rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pbtn{font:600 .85rem/1 var(--sans);color:var(--ink);background:var(--paper);border:1px solid var(--rule);border-radius:8px;min-width:2.5rem;height:2.3rem;padding:0 .6rem;cursor:pointer}
.pbtn:disabled{opacity:.4;cursor:default}
.pbody{flex:1;overflow-y:auto;padding:.9rem 1rem 1.5rem;-webkit-overflow-scrolling:touch}
.claim{font:1rem/1.5 var(--serif);border-left:3px solid var(--flag);padding:.1rem 0 .1rem .8rem;margin:0 0 .8rem}
.figs{font-size:.8rem;line-height:1.5;color:var(--ink2);margin:0 0 .8rem}
.figs b{color:var(--ink);font-weight:650}
.figs .pnote{display:block;margin-top:.35rem}
.figs .warn{color:var(--checkink);background:var(--checkbg);border-radius:6px;padding:.45rem .6rem;display:block;margin-top:.4rem}
.imgwrap{overflow:auto;border:1px solid var(--rule);background:#fff;border-radius:4px;margin-top:.9rem}
.imgwrap img{display:block;width:100%;height:auto;cursor:zoom-in}
.imgwrap.zoom img{width:210%;max-width:none;cursor:zoom-out}
.hint{font-size:.75rem;color:var(--ink2);margin:.35rem 0 0}
@media (min-width:1100px){
#panel{left:auto;top:0;height:auto;width:min(48vw,760px);border-radius:0;border-top:0;border-left:1px solid var(--rule);transform:translateX(102%);padding-top:env(safe-area-inset-top,0px)}
#panel.on{transform:none}
#shade{display:none}
body.panelopen main,body.panelopen .note{margin-left:max(1.1rem,calc((52vw - 44rem)/2));margin-right:auto}
}
@media (prefers-reduced-motion:reduce){#panel,#shade,main{transition:none}}
</style>
</head>
<body>
<header class="top">
<h1>%%TITLE%%</h1>
<div class="meta"><span>%%META%%</span>%%CHECKBTN%%<button type="button" class="ghost showpages" id="showpages">Cited pages</button></div>
<nav class="tabs" aria-label="Documents">%%TABS%%</nav>
</header>
<main>
%%SECTIONS%%
<section id="pages" aria-label="Cited pages">
<h2>Cited pages</h2>
%%FIGURES%%
</section>
</main>
<p class="note">Built on %%BUILT%% from the deal folder %%DEAL%%. Tap a citation to open the page it points to. The figure check compares the numbers in each claim with the text of the cited page. A number can be missing because it sits in a table image or is written another way, so treat a mark as a prompt to look, not as a finding.</p>
<div id="shade"></div>
<aside id="panel" role="dialog" aria-modal="false" aria-labelledby="ptitle" aria-hidden="true">
<div class="phead">
<div class="ptitle" id="ptitle"></div>
<button type="button" class="pbtn" id="pprev" aria-label="Previous cited page">&#8249;</button>
<button type="button" class="pbtn" id="pnext" aria-label="Next cited page">&#8250;</button>
<button type="button" class="pbtn" id="pclose" aria-label="Close">&#215;</button>
</div>
<div class="pbody" id="pbody">
<p class="claim" id="pclaim"></p>
<div class="figs" id="pfigs"></div>
<details open><summary>Page text</summary><pre class="pagetext" id="ptext"></pre></details>
<div class="imgwrap" id="pimgwrap"><img id="pimg" alt=""></div>
<p class="hint" id="phint">Tap the page to zoom.</p>
</div>
</aside>
<script>
(function(){
var D=%%DATA%%;
document.documentElement.classList.add("js");
var tabs=[].slice.call(document.querySelectorAll(".tab")),secs=[].slice.call(document.querySelectorAll(".doc"));
var panel=document.getElementById("panel"),shade=document.getElementById("shade");
var current=null,currentCite=null,lastChip=null;
function show(id){tabs.forEach(function(t){t.setAttribute("aria-pressed",t.dataset.sec===id?"true":"false")});secs.forEach(function(s){s.classList.toggle("on",s.dataset.sec===id)});try{localStorage.setItem("viewer-tab-"+document.title,id)}catch(e){}}
tabs.forEach(function(t){t.addEventListener("click",function(){show(t.dataset.sec);window.scrollTo(0,0)})});
var saved=null;try{saved=localStorage.getItem("viewer-tab-"+document.title)}catch(e){}
show(saved&&D.sections.indexOf(saved)>=0?saved:D.sections[0]);
function esc(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function rx(s){return s.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}
function fig(key){return document.querySelector('figure.page[data-key="'+key.replace(/"/g,'\\"')+'"]')}
function render(key,c){
var f=fig(key);if(!f)return;current=key;
document.getElementById("ptitle").textContent=f.dataset.label;
var img=f.querySelector("img"),pimg=document.getElementById("pimg"),wrap=document.getElementById("pimgwrap");
wrap.classList.remove("zoom");
if(img){pimg.src=img.src;pimg.alt=f.dataset.label;wrap.style.display="";document.getElementById("phint").style.display=""}else{wrap.style.display="none";document.getElementById("phint").style.display="none"}
var raw=f.querySelector("pre").textContent,h=esc(raw);
if(c&&c.hits&&c.hits.length){h=h.replace(new RegExp(c.hits.map(function(x){return rx(esc(x))}).join("|"),"g"),function(m){return"<mark>"+m+"</mark>"})}
h=h.replace(/^&gt;(.*)$/m,function(m,rest){return'<span class="focusline">&gt;'+rest+"</span>"});
document.getElementById("ptext").innerHTML=h;
var cl=document.getElementById("pclaim"),fg=document.getElementById("pfigs");
if(c&&c.claim){cl.textContent=c.claim;cl.style.display=""}else{cl.style.display="none"}
var out="";
if(c&&c.keys&&c.keys.indexOf(key)>=0){
if(c.found.length)out+="Figures from the claim found on this page <b>"+esc(c.found.join(", "))+"</b>. ";
if(c.missing.length)out+="Not found in the page text <b>"+esc(c.missing.join(", "))+"</b>.";
if(c.flagged)out+='<span class="warn">None of the dollar amounts, dates or large numbers in this claim appear in the text of the cited page. Check the image, or the citation may point to the wrong page.</span>';
}
if(f.dataset.note)out+='<span class="pnote">'+esc(f.dataset.note)+'</span>';
fg.innerHTML=out;fg.style.display=out?"":"none";
var nv=D.nav[key]||{};
document.getElementById("pprev").disabled=!nv.prev;document.getElementById("pnext").disabled=!nv.next;
document.getElementById("pbody").scrollTop=0;
}
function open(key,c){currentCite=c;render(key,c);panel.classList.add("on");panel.setAttribute("aria-hidden","false");shade.classList.add("on");document.body.classList.add("panelopen");document.getElementById("pclose").focus({preventScroll:true})}
function close(){panel.classList.remove("on");panel.setAttribute("aria-hidden","true");shade.classList.remove("on");document.body.classList.remove("panelopen");if(lastChip)lastChip.focus({preventScroll:true})}
document.addEventListener("click",function(e){var a=e.target.closest("a.cite");if(!a)return;e.preventDefault();var c=D.cites[+a.dataset.cite];lastChip=a;open(c.keys[0],c)});
document.getElementById("pclose").addEventListener("click",close);
shade.addEventListener("click",close);
document.addEventListener("keydown",function(e){if(e.key==="Escape"&&panel.classList.contains("on"))close()});
document.getElementById("pprev").addEventListener("click",function(){var n=D.nav[current];if(n&&n.prev)render(n.prev,currentCite)});
document.getElementById("pnext").addEventListener("click",function(){var n=D.nav[current];if(n&&n.next)render(n.next,currentCite)});
document.getElementById("pimg").addEventListener("click",function(){document.getElementById("pimgwrap").classList.toggle("zoom")});
var sp=document.getElementById("showpages"),pages=document.getElementById("pages");
sp.addEventListener("click",function(){var on=pages.classList.toggle("on");sp.textContent=on?"Hide cited pages":"Cited pages";if(on)pages.scrollIntoView()});
var nc=document.getElementById("nextcheck");
if(nc){var i=-1;nc.addEventListener("click",function(){var sec=document.querySelector(".doc.on");var list=[].slice.call(sec.querySelectorAll(".cite-check,.cite-missing"));if(!list.length){var other=secs.filter(function(s){return s.querySelector(".cite-check,.cite-missing")})[0];if(!other)return;show(other.dataset.sec);sec=other;list=[].slice.call(sec.querySelectorAll(".cite-check,.cite-missing"));i=-1}i=(i+1)%list.length;var el=list[i];el.scrollIntoView({block:"center"});el.classList.add("flash");setTimeout(function(){el.classList.remove("flash")},1200)})}
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
