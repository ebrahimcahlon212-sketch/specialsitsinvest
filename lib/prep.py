#!/usr/bin/env python3
"""Turn a deal's filings into files that every model reads the same way.

For each PDF in <deal>/filings this writes, under <deal>/work/<short name>/,
  text/pNNN.txt   the text of each page (pdftotext -layout)
  pages/pNNN.png  an image of each page (pdftoppm)
  all.txt         the whole text, with a [pNNN] tag at the start of every line
HTML, text and Markdown filings get an all.txt with [L.N] line tags instead.
A PNG or JPG file becomes a one-page document.
It then writes <deal>/work/INDEX.md, which lists every document.

Pages with little text are run through OCR with tesseract when it is
installed (set OCR=off to skip this). Files that have not changed since the
last run are skipped.

Usage: prep.py <deal folder>
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser

DPI = int(os.environ.get("DPI", "110"))
OCR_DPI = int(os.environ.get("OCR_DPI", "300"))
OCR = os.environ.get("OCR", "auto").lower()
LOW_TEXT = 40  # pages with fewer non-space characters than this count as having no text

PDF_EXT = {".pdf"}
HTML_EXT = {".htm", ".html", ".xhtml"}
TEXT_EXT = {".txt", ".md"}
IMAGE_EXT = {".png", ".jpg", ".jpeg"}

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def say(msg):
    print("  " + msg, flush=True)


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, check=True)


def have(tool):
    return shutil.which(tool) is not None


def ocr_enabled():
    return OCR != "off" and have("tesseract")


def make_short_name(filename, used):
    base = os.path.splitext(filename)[0].lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")[:40].rstrip("_") or "doc"
    name, i = base, 2
    while name in used:
        name = "%s_%d" % (base, i)
        i += 1
    used.add(name)
    return name


def fingerprint(path):
    st = os.stat(path)
    return {"file": os.path.basename(path), "size": st.st_size,
            "mtime": int(st.st_mtime), "dpi": DPI}


def ranges(nums):
    nums = sorted(set(nums))
    if not nums:
        return "none"
    spans, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        spans.append((start, prev))
        start = prev = n
    spans.append((start, prev))
    return ", ".join(str(a) if a == b else "%d-%d" % (a, b) for a, b in spans)


def write_all_txt(dest, tagged):
    with open(os.path.join(dest, "all.txt"), "w", encoding="utf-8") as fh:
        for tag, text in tagged:
            for line in text.splitlines():
                if line.strip():
                    fh.write("[%s] %s\n" % (tag, line.rstrip()))


def chars(text):
    return len(re.sub(r"\s", "", text))


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def ocr_pdf_page(src, page):
    tmp = tempfile.mkdtemp()
    try:
        base = os.path.join(tmp, "page")
        run(["pdftoppm", "-r", str(OCR_DPI), "-f", str(page), "-l", str(page),
             "-png", "-singlefile", src, base])
        return run(["tesseract", base + ".png", "stdout"]).stdout
    except Exception:
        return ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def prep_pdf(src, dest):
    info = run(["pdfinfo", src]).stdout
    m = re.search(r"^Pages:\s+(\d+)", info, re.M)
    if not m:
        raise RuntimeError("pdfinfo did not report a page count")
    n = int(m.group(1))
    width = max(3, len(str(n)))
    tdir, idir = os.path.join(dest, "text"), os.path.join(dest, "pages")
    os.makedirs(tdir)
    os.makedirs(idir)

    # One pdftotext call for the whole file. Pages are separated by form feeds.
    full = run(["pdftotext", "-layout", "-enc", "UTF-8", src, "-"]).stdout
    pages = full.split("\f")
    if len(pages) >= n:
        pages = pages[:n]
    else:
        pages = [run(["pdftotext", "-layout", "-enc", "UTF-8", "-f", str(p),
                      "-l", str(p), src, "-"]).stdout for p in range(1, n + 1)]

    run(["pdftoppm", "-r", str(DPI), "-png", src, os.path.join(idir, "tmp")])
    for f in os.listdir(idir):
        mm = re.match(r"tmp-0*(\d+)\.png$", f)
        if mm:
            os.rename(os.path.join(idir, f),
                      os.path.join(idir, "p%0*d.png" % (width, int(mm.group(1)))))

    low, ocred = [], []
    use_ocr = ocr_enabled()
    for i in range(1, n + 1):
        text = pages[i - 1]
        if chars(text) < LOW_TEXT:
            low.append(i)
            if use_ocr:
                t = ocr_pdf_page(src, i)
                if chars(t) > chars(text):
                    text = t
                    ocred.append(i)
            pages[i - 1] = text
        with open(os.path.join(tdir, "p%0*d.txt" % (width, i)), "w", encoding="utf-8") as fh:
            fh.write(text)
    write_all_txt(dest, [("p%0*d" % (width, i), pages[i - 1]) for i in range(1, n + 1)])
    return {"kind": "PDF", "size": plural(n, "page"), "low": low, "ocr": ocred}


class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4",
             "h5", "h6", "section", "article", "header", "footer", "blockquote", "pre",
             "hr", "dt", "dd", "center"}
    CELL = {"td", "th"}
    SKIP = {"script", "style", "head", "title", "ix:header"}

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in ("br", "hr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.CELL:
            self.parts.append(" | ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def text(self):
        raw = "".join(self.parts).replace("\xa0", " ")
        lines, blank = [], False
        for ln in raw.split("\n"):
            ln = re.sub(r"[ \t\r]+", " ", ln).strip()
            ln = re.sub(r"(\|\s*){2,}", "| ", ln)
            ln = re.sub(r"^\|\s*", "", ln)
            ln = re.sub(r"\s*\|$", "", ln).strip()
            if ln:
                lines.append(ln)
                blank = False
            elif not blank:
                lines.append("")
                blank = True
        return "\n".join(lines).strip() + "\n"


def read_text(src):
    raw = open(src, "rb").read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def prep_text(src, dest, is_html):
    s = read_text(src)
    if is_html:
        parser = _HTMLText()
        parser.feed(s)
        parser.close()
        s = parser.text()
    os.makedirs(dest)
    lines = s.splitlines()
    with open(os.path.join(dest, "all.txt"), "w", encoding="utf-8") as fh:
        for i, ln in enumerate(lines, 1):
            if ln.strip():
                fh.write("[L.%d] %s\n" % (i, ln.rstrip()))
    kind = "HTML, text only" if is_html else "Text"
    return {"kind": kind, "size": plural(len(lines), "line"), "low": [], "ocr": []}


def html_renderer():
    """A tool that prints HTML to PDF, so HTML filings get page images in the viewer. None if there isn't one."""
    if os.environ.get("HTML_PAGES", "on").lower() == "off":
        return None
    if have("weasyprint"):
        return lambda src, out: ["weasyprint", "--base-url", os.path.dirname(os.path.abspath(src)), src, out]
    if have("wkhtmltopdf"):
        return lambda src, out: ["wkhtmltopdf", "--quiet", "--enable-local-file-access", src, out]
    for chrome in ("chromium", "chromium-browser", "google-chrome"):
        if have(chrome):
            return lambda src, out, c=chrome: [c, "--headless", "--disable-gpu", "--no-sandbox",
                                                "--print-to-pdf=" + out, "file://" + os.path.abspath(src)]
    return None


def render_html_pages(src, dest):
    """Print an HTML filing to pages: hpages/pNNN.png images and htext/pNNN.txt text. Returns the page count, or 0."""
    make = html_renderer()
    if not make or not (have("pdftoppm") and have("pdftotext")):
        return 0
    pdf = os.path.join(dest, "printed.pdf")
    try:
        subprocess.run(make(src, pdf), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
    except Exception:
        return 0
    if not os.path.exists(pdf) or os.path.getsize(pdf) < 1000:
        return 0
    idir, tdir = os.path.join(dest, "hpages"), os.path.join(dest, "htext")
    for d in (idir, tdir):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    try:
        subprocess.run(["pdftoppm", "-r", "96", "-png", pdf, os.path.join(idir, "tmp")], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=900)
        subprocess.run(["pdftotext", "-layout", pdf, os.path.join(tdir, "all.txt")], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=600)
    except Exception:
        return 0
    imgs = sorted(f for f in os.listdir(idir) if f.startswith("tmp"))
    width = max(3, len(str(len(imgs))))
    for f in imgs:
        num = int(re.search(r"(\d+)\.png$", f).group(1))
        os.rename(os.path.join(idir, f), os.path.join(idir, "p%0*d.png" % (width, num)))
    text = open(os.path.join(tdir, "all.txt"), encoding="utf-8", errors="replace").read().split("\f")
    for i, t in enumerate(text[:len(imgs)], 1):
        with open(os.path.join(tdir, "p%0*d.txt" % (width, i)), "w", encoding="utf-8") as fh:
            fh.write(t)
    return len(imgs)


def prep_image(src, dest):
    tdir, idir = os.path.join(dest, "text"), os.path.join(dest, "pages")
    os.makedirs(tdir)
    os.makedirs(idir)
    ext = os.path.splitext(src)[1].lower()
    shutil.copyfile(src, os.path.join(idir, "p001" + ext))
    text, ocred = "", []
    if ocr_enabled():
        try:
            text = run(["tesseract", src, "stdout"]).stdout
        except Exception:
            text = ""
        if text.strip():
            ocred = [1]
    with open(os.path.join(tdir, "p001.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)
    write_all_txt(dest, [("p001", text)])
    return {"kind": "Image (p001%s)" % ext, "size": "1 page", "low": [1], "ocr": ocred}


def write_index(deal, wdir, rows, skipped):
    rel_deal = os.path.relpath(deal, KIT)
    rel_work = os.path.relpath(wdir, KIT)
    out = []
    out.append("# Filings index\n")
    out.append("Deal folder `%s`. Built on %s.\n" % (rel_deal, datetime.date.today().isoformat()))
    out.append("Cite PDF and image documents as [short name p.N], where N is the page number "
               "in the file names. Cite HTML and text documents as [short name L.N], using the "
               "line tags in all.txt.\n")
    out.append("| Short name | Source file | Kind | Size | Read from the image | Text from OCR |")
    out.append("|---|---|---|---|---|---|")
    for name, src, info in rows:
        if info["kind"].startswith("HTML") or info["kind"] == "Text":
            img, ocr = "no page images", "n/a"
        else:
            img = ranges(set(info["low"]) - set(info["ocr"]))
            ocr = ranges(info["ocr"])
        out.append("| %s | %s | %s | %s | %s | %s |" % (name, src.replace("|", "/"), info["kind"],
                                                       info["size"], img, ocr))
    out.append("")
    out.append("## Where the files are\n")
    out.append("For a document with the short name X, the full text is in `%s/X/all.txt`, with a "
               "page or line tag at the start of every line. Search this file first.\n" % rel_work)
    out.append("For PDFs and images, each page also has its own text file and image, for example "
               "`%s/X/text/p001.txt` and `%s/X/pages/p001.png`. They are numbered the same way as "
               "the tags.\n" % (rel_work, rel_work))
    out.append("Pages listed under \"Read from the image\" have little or no extractable text, so "
               "their content is only in the image. Pages listed under \"Text from OCR\" have text "
               "produced by OCR, which can misread numbers, so check figures on those pages against "
               "the image.\n")
    out.append("HTML and text filings have no page images. If a table in one of them looks "
               "garbled, the investor can save that filing as a PDF and run the prep step again.\n")
    if skipped:
        out.append("These files in the filings folder were skipped because they are not a supported "
                   "type or could not be read. %s\n" % ", ".join(skipped))
    with open(os.path.join(wdir, "INDEX.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: prep.py <deal folder>")
    deal = os.path.abspath(sys.argv[1])
    fdir, wdir = os.path.join(deal, "filings"), os.path.join(deal, "work")
    if not os.path.isdir(fdir):
        sys.exit("No filings folder at %s" % fdir)
    os.makedirs(wdir, exist_ok=True)

    manifest_path = os.path.join(wdir, "manifest.json")
    old = {}
    if os.path.exists(manifest_path):
        try:
            old = json.load(open(manifest_path))
        except ValueError:
            old = {}

    junk = re.compile(r"(:zone\.identifier|\.crdownload|\.part|\.tmp)$|^(desktop\.ini|thumbs\.db)$", re.I)
    files = sorted(f for f in os.listdir(fdir)
                   if not f.startswith(".") and not f.startswith("~$") and not junk.search(f)
                   and os.path.isfile(os.path.join(fdir, f)))
    supported = PDF_EXT | HTML_EXT | TEXT_EXT | IMAGE_EXT
    skipped = [f for f in files if os.path.splitext(f)[1].lower() not in supported]
    files = [f for f in files if f not in skipped]

    if any(os.path.splitext(f)[1].lower() in PDF_EXT for f in files):
        missing = [t for t in ("pdfinfo", "pdftotext", "pdftoppm") if not have(t)]
        if missing:
            sys.exit("Missing %s. Install poppler (see docs/manual.md)." % " and ".join(missing))

    # Keep the short name a file had last time, so citations stay stable.
    by_file = dict((v["fp"]["file"], k) for k, v in old.items() if "fp" in v)
    used = set(by_file[f] for f in files if f in by_file)
    names = {}
    for f in files:
        names[f] = by_file[f] if f in by_file else make_short_name(f, used)

    manifest, rows = {}, []
    for f in files:
        src, name = os.path.join(fdir, f), names[f]
        dest = os.path.join(wdir, name)
        fp = fingerprint(src)
        ext = os.path.splitext(f)[1].lower()
        if name in old and old[name].get("fp") == fp and os.path.isdir(dest):
            info = old[name]["info"]
            say("unchanged   %s" % f)
            if info.get("kind", "").startswith("HTML") and not os.path.isdir(os.path.join(dest, "hpages")) and html_renderer():
                n = render_html_pages(src, dest)
                if n:
                    info = dict(info, printed=n)
                    say("printed     %s to %d pages for the viewer" % (f, n))
        else:
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            say("processing  %s" % f)
            try:
                if ext in PDF_EXT:
                    info = prep_pdf(src, dest)
                elif ext in HTML_EXT:
                    info = prep_text(src, dest, True)
                elif ext in TEXT_EXT:
                    head = open(src, "rb").read(20000).lower()
                    info = prep_text(src, dest, b"<html" in head or b"<document>" in head)
                else:
                    info = prep_image(src, dest)
                if info.get("kind", "").startswith("HTML"):
                    n = render_html_pages(src, dest)
                    if n:
                        info = dict(info, printed=n)
                        say("printed     %s to %d pages for the viewer" % (f, n))
            except Exception as e:
                say("could not process %s (%s)" % (f, e))
                shutil.rmtree(dest, ignore_errors=True)
                skipped.append(f)
                continue
        manifest[name] = {"fp": fp, "info": info}
        rows.append((name, f, info))

    for name in old:
        if name not in manifest:
            shutil.rmtree(os.path.join(wdir, name), ignore_errors=True)

    with open(manifest_path, "w") as fh:
        json.dump(manifest, fh, indent=1)
    write_index(deal, wdir, rows, skipped)
    if not rows:
        sys.exit("No usable filings found in %s" % fdir)
    say("index       %s" % os.path.relpath(os.path.join(wdir, "INDEX.md"), KIT))


if __name__ == "__main__":
    main()
