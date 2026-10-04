#!/usr/bin/env python3
"""Where two merging chains overlap, and how many rivals each area has left.

The CMA screens retail mergers by drawing a catchment around each store and
counting the rival brands (fascias) inside it. Areas where the merger leaves
few brands, such as four becoming three, get a closer look and are usually
fixed by selling a store. This does a rough version of that screen using
OpenStreetMap, the free open map, which tags UK shops by brand.

Usage
  overlap.py DEAL BRAND_A BRAND_B [--shop TYPE] [--radius KM] [--country GB]
             [--list-a URL_OR_FILE] [--list-b URL_OR_FILE] [--rival "NAME=URL_OR_FILE"]...

--list-a and --list-b point at each chain's own store list, either the web
address of its "all stores" page or a copy of that page saved from a browser.
Every UK postcode on the page is read and located with postcodes.io, a free
service, so the chains' locations come from their own websites. Rival shops
come from OpenStreetMap, and --rival adds a rival chain from its own store
list in the same way. It can be given more than once.

BRAND_A and BRAND_B are patterns matched against each shop's brand and name,
for example "Ramsdens" and "H&T|H & T". --shop is the OpenStreetMap shop type
used to find rivals, for example pawnbroker. Writes out/overlap.md and
out/overlap.json in the deal folder.

OpenStreetMap is volunteer-made, so the report compares the number of shops
found with the chains' own store counts, and a missing shop means a missing
overlap. Straight-line distance is a stand-in for the drive times the CMA uses.
"""
import json
import math
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finder  # noqa: E402

OVERPASS = ["https://overpass-api.de/api/interpreter?data=", "https://overpass.kumi.systems/api/interpreter?data="]


BOXES = {"GB": "49.8,-8.7,60.9,1.8"}
LAST_ERROR = [""]


def query(shop, pattern_a, pattern_b, country, server=0, rivals_only=False):
    """Every shop of this type in the country. A bounding box answers much faster than a country boundary, so the UK
    uses one. Only when a chain has no store list of its own does it also search brand tags for the two chains."""
    if country in BOXES:
        where = "(%s)" % BOXES[country]
        head = "[out:json][timeout:240];("
    else:
        where = "(area.c)"
        head = '[out:json][timeout:240];area["ISO3166-1"="%s"][admin_level=2]->.c;(' % country
    extra = "" if rivals_only else 'nwr["brand"~"%s|%s",i]%s;' % (pattern_a, pattern_b, where)
    ql = '%snwr["shop"="%s"]%s;%s);out center tags;' % (head, shop, where, extra)
    return OVERPASS[server] + urllib.parse.quote(ql)


def slow_get(url):
    """Overpass can take a few minutes on a country-wide question, far longer than ordinary downloads are allowed."""
    if finder.MOCK:
        return finder.get(url, sec=False)
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "special-sits-kit (store overlap research)"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def fetch_osm(shop, a, b, country, rivals_only):
    for server in range(len(OVERPASS)):
        try:
            raw = slow_get(query(shop, a, b, country, server, rivals_only))
            if raw and raw.lstrip()[:1] == b"{":
                return shops_from(json.loads(raw.decode("utf-8", "replace")))
            LAST_ERROR[0] = "the server sent back something other than map data"
        except Exception as e:
            LAST_ERROR[0] = str(e) or e.__class__.__name__
    return None


POSTCODE = re.compile(r"\b([A-PR-UWYZ][A-HK-Y]?[0-9][A-Z0-9]?)\s*([0-9][ABD-HJLNP-UW-Z]{2})\b")


def page_text(src):
    if os.path.exists(src):
        raw = open(src, "rb").read()
    else:
        raw = finder.get(src, sec=False) or b""
    text = raw.decode("utf-8", "replace")
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"<[^>]+>", "\n", text)
    return re.sub(r"&amp;", "&", text).upper()


def postcodes_in(src):
    seen, out = set(), []
    for m in POSTCODE.finditer(page_text(src)):
        pc = "%s %s" % (m.group(1), m.group(2))
        if pc not in seen:
            seen.add(pc)
            out.append(pc)
    return out


def post_json(url, obj):
    body = json.dumps(obj).encode()
    if finder.MOCK:
        import hashlib
        path = os.path.join(finder.MOCK, hashlib.md5((url + body.decode()).encode()).hexdigest() + ".dat")
        return json.loads(open(path).read()) if os.path.exists(path) else None
    import time
    import urllib.request
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                                  "User-Agent": "special-sits-kit"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(2 + attempt * 2)
    return None


def locate(postcodes):
    """Latitude, longitude and district for each postcode, 100 at a time, from postcodes.io."""
    found = {}
    for i in range(0, len(postcodes), 100):
        chunk = postcodes[i:i + 100]
        res = post_json("https://api.postcodes.io/postcodes", {"postcodes": chunk}) or {}
        for item in res.get("result") or []:
            r = item.get("result")
            if r and r.get("latitude") is not None:
                found[item["query"]] = {"lat": r["latitude"], "lon": r["longitude"],
                                        "place": r.get("admin_district") or r.get("parish") or "", "postcode": r.get("postcode")}
    return found


def official(src, fascia_code):
    pcs = postcodes_in(src)
    where = locate(pcs)
    shops = [{"lat": w["lat"], "lon": w["lon"], "label": fascia_code, "name": fascia_code, "place": w["place"],
              "postcode": w["postcode"] or pc, "shop": "", "fascia": fascia_code} for pc, w in ((p, where.get(p)) for p in pcs) if w]
    return shops, len(pcs)


def write_map(path, A, B, rows, name_a, name_b, radius):
    pts = A + B
    if not pts:
        return
    lat0 = sum(p["lat"] for p in pts) / len(pts)
    k = math.cos(math.radians(lat0))
    xs = [p["lon"] * k for p in pts]
    ys = [p["lat"] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    w = 560.0
    h = w * (maxy - miny) / max(maxx - minx, 1e-6)
    h = min(max(h, 300.0), 900.0)
    sx = lambda p: 20 + (p["lon"] * k - minx) / max(maxx - minx, 1e-6) * w
    sy = lambda p: 20 + (maxy - p["lat"]) / max(maxy - miny, 1e-6) * h
    over = set((r["lat"], r["lon"]) for r in rows if r.get("overlap"))
    dots = []
    for p in B:
        dots.append('<circle cx="%.1f" cy="%.1f" r="3" class="b"><title>%s %s</title></circle>' % (sx(p), sy(p), name_b, p["postcode"]))
    for p in A:
        cls = "a hit" if (p["lat"], p["lon"]) in over else "a"
        dots.append('<circle cx="%.1f" cy="%.1f" r="3.4" class="%s"><title>%s %s</title></circle>' % (sx(p), sy(p), cls, name_a, p["postcode"]))
    page = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(a)s and %(b)s stores</title><style>
:root{--bg:#fbfaf7;--ink:#1d1d1b;--muted:#6b6a64;--a:#2b5d8a;--b:#d9822b;--hit:#c0392b}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--ink:#ecebe6;--muted:#a3a29c}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:640px;margin:0 auto;padding:1rem}
svg{width:100%%;height:auto;display:block}
.a{fill:var(--a)}.b{fill:var(--b);opacity:.75}.hit{fill:var(--hit);stroke:var(--hit);stroke-width:5;stroke-opacity:.3}
.key span{display:inline-block;width:.7rem;height:.7rem;border-radius:50%%;margin:0 .35rem 0 .9rem;vertical-align:-1px}
p{color:var(--muted)}</style></head><body><main>
<h1>%(a)s and %(b)s stores</h1>
<p>Each dot is a store located from its postcode. Red dots are %(a)s stores with a %(b)s store within %(r).1f km. Hover or tap a dot for its postcode.</p>
<div class="key"><span style="background:var(--a)"></span>%(a)s<span style="background:var(--b)"></span>%(b)s<span style="background:var(--hit)"></span>Overlap</div>
<svg viewBox="0 0 %(vw).0f %(vh).0f" role="img" aria-label="Map of store locations">%(dots)s</svg>
</main></body></html>""" % {"a": name_a, "b": name_b, "r": radius, "vw": w + 40, "vh": h + 40, "dots": "".join(dots)}
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)


def km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def shops_from(data):
    out = []
    for e in data.get("elements", []):
        t = e.get("tags") or {}
        lat = e.get("lat", (e.get("center") or {}).get("lat"))
        lon = e.get("lon", (e.get("center") or {}).get("lon"))
        if lat is None or lon is None:
            continue
        label = (t.get("brand") or t.get("name") or "unnamed").strip()
        place = t.get("addr:city") or t.get("addr:town") or t.get("addr:suburb") or t.get("addr:postcode") or ""
        out.append({"lat": lat, "lon": lon, "label": label, "name": t.get("name") or label, "place": place,
                    "postcode": t.get("addr:postcode") or "", "shop": t.get("shop") or ""})
    return out


def fascia(s, ra, rb):
    text = "%s %s" % (s["label"], s["name"])
    if ra.search(text):
        return "A"
    if rb.search(text):
        return "B"
    return re.sub(r"[^a-z0-9]+", " ", s["label"].lower()).strip() or "independent"


def main(deal, a, b, shop="pawnbroker", radius=3.0, country="GB", label_a=None, label_b=None, list_a=None, list_b=None,
         rival_lists=None):
    osm_list = fetch_osm(shop, a, b, country, rivals_only=bool(list_a and list_b))
    raw = osm_list is not None
    osm = osm_list or []
    if not raw and not (list_a and list_b):
        sys.exit("OpenStreetMap didn't answer. Try again in a minute, since the free servers are sometimes busy.")
    ra, rb = re.compile(a, re.I), re.compile(b, re.I)
    for s_ in osm:
        s_["fascia"] = fascia(s_, ra, rb)
    source = {"A": "OpenStreetMap", "B": "OpenStreetMap"}
    listed = {}
    A = [s_ for s_ in osm if s_["fascia"] == "A"]
    B = [s_ for s_ in osm if s_["fascia"] == "B"]
    if list_a:
        A, listed["A"] = official(list_a, "A")
        source["A"] = "its own store list"
    if list_b:
        B, listed["B"] = official(list_b, "B")
        source["B"] = "its own store list"
    rivals = [s_ for s_ in osm if s_["fascia"] not in ("A", "B")]
    extra_rivals = {}
    for label, src in (rival_lists or []):
        code = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
        found, n = official(src, code)
        extra_rivals[label] = (len(found), n)
        near_dupes = [r for r in rivals if r["fascia"] != code]
        rivals = near_dupes + found
    shops = A + B + rivals
    name_a = label_a or a.split("|")[0]
    name_b = label_b or b.split("|")[0]
    rows = []
    for s in A:
        near = [(km((s["lat"], s["lon"]), (o["lat"], o["lon"])), o) for o in shops if o is not s]
        inside = [(d, o) for d, o in near if d <= radius]
        nearest_b = min([d for d, o in near if o["fascia"] == "B"] or [None]) if B else None
        fascias = set(["A"]) | set(o["fascia"] for d, o in inside)
        has_b = "B" in fascias
        before = len(fascias)
        after = before - 1 if has_b else before
        rows.append({"lat": s["lat"], "lon": s["lon"], "place": s["place"] or "%.3f, %.3f" % (s["lat"], s["lon"]), "postcode": s["postcode"],
                     "nearest_b_km": nearest_b, "overlap": has_b, "fascias_before": before, "fascias_after": after,
                     "rivals": sorted(f for f in fascias if f not in ("A", "B"))})
    rows.sort(key=lambda r: (not r["overlap"], r["fascias_after"], r["nearest_b_km"] or 999))
    ov = [r for r in rows if r["overlap"]]
    within = lambda d: sum(1 for r in rows if r["nearest_b_km"] is not None and r["nearest_b_km"] <= d)
    flags = {"to2": sum(1 for r in ov if r["fascias_after"] <= 2), "to3": sum(1 for r in ov if r["fascias_after"] <= 3),
             "to4": sum(1 for r in ov if r["fascias_after"] <= 4)}
    have_rivals = bool(rivals)
    result = {"brand_a": name_a, "brand_b": name_b, "radius_km": radius, "found_a": len(A), "found_b": len(B),
              "source": source, "postcodes_listed": listed, "rivals_found": len(rivals), "within_1km": within(1), "within_3km": within(3),
              "within_5km": within(5), "flags": flags, "rows": rows}
    out = os.path.join(deal, "out")
    os.makedirs(out, exist_ok=True)
    finder.save_json(os.path.join(out, "overlap.json"), result)
    L = ["# Store overlap, %s and %s" % (name_a, name_b), "",
         "A rough version of the CMA's local screen, run today. For each %s store it looks within %.1f km, counts the "
         "distinct brands of %s shops there, and shows how many are left once %s and %s become one. Straight-line distance "
         "stands in for the drive times the CMA uses, and a missing shop means a missing overlap, so compare the counts "
         "located with the chains' own figures. A head office address on a store list page adds one to its count." % (
             name_a, radius, shop, name_a, name_b), "",
         "%s locations come from %s and %s locations from %s. Rival shops come from OpenStreetMap%s." % (
             name_a, source["A"], name_b, source["B"], "" if raw else ", which didn't answer this time, so no rivals are counted"), "",
         "| Item | Count |", "|---|---|",
         "| %s stores located%s | %d |" % (name_a, (", from %d postcodes on its list" % listed["A"]) if "A" in listed else "", len(A)),
         "| %s stores located%s | %d |" % (name_b, (", from %d postcodes on its list" % listed["B"]) if "B" in listed else "", len(B)),
         "| Other %s shops found | %d |" % (shop, result["rivals_found"]),
         "| %s stores within 1 km of the nearest %s | %d |" % (name_a, name_b, result["within_1km"]),
         "| Within 3 km | %d |" % result["within_3km"],
         "| Within 5 km | %d |" % result["within_5km"],
         "| Overlap areas left with 2 brands or fewer | %s |" % (flags["to2"] if have_rivals else "not counted, no rival data"),
         "| Left with 3 or fewer, the CMA's usual grocery screen | %s |" % (flags["to3"] if have_rivals else "not counted"),
         "| Left with 4 or fewer, the screen it often uses elsewhere | %s |" % (flags["to4"] if have_rivals else "not counted"), ""]
    for label, (located, listed_n) in extra_rivals.items():
        L += ["%s: %d shops located from %d postcodes on its list, counted as rivals." % (label, located, listed_n), ""]
    L += [
         "In similar deals, the CMA has usually asked for one store to be sold in each area that fails its screen, so the "
         "flagged counts are a rough guide to how many stores a remedy might involve.", "",
         "## Areas where both chains are present", "",
         "| Place | Postcode | Nearest %s | Brands before | Brands after | Other brands nearby |" % name_b,
         "|---|---|---|---|---|---|"]
    for r in ov:
        L.append("| %s | %s | %s | %d | %d | %s |" % (r["place"], r["postcode"], "%.1f km" % r["nearest_b_km"],
                                                    r["fascias_before"], r["fascias_after"], ", ".join(r["rivals"]) or "none"))
    if not ov:
        L.append("| None found within %.1f km | | | | | |" % radius)
    L.append("")
    L += ["A map of every store, with the overlaps in red, is in out/overlap-map.html.", ""]
    with open(os.path.join(out, "overlap.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    write_map(os.path.join(out, "overlap-map.html"), A, B, rows, name_a, name_b, radius)
    if have_rivals:
        finder.say("overlap     %d %s and %d %s stores found, %d rival shops, %d overlap areas within %.1f km, %d left with 3 brands or fewer" % (
            len(A), name_a, len(B), name_b, len(rivals), len(ov), radius, flags["to3"]))
    else:
        finder.say("overlap     %d %s and %d %s stores found, %d overlap areas within %.1f km" % (
            len(A), name_a, len(B), name_b, len(ov), radius))
        finder.say("warning     no rival shops were loaded (%s), so the brand counts are not meaningful. OpenStreetMap may be "
                   "busy, so try again in a few minutes, or add rival chains' own lists with --rival" % (LAST_ERROR[0] or "no reply"))


if __name__ == "__main__":
    args = sys.argv[1:]
    opts = {}
    rival_lists = []
    while "--rival" in args:
        i = args.index("--rival")
        label, _, src = args[i + 1].partition("=")
        if not src:
            sys.exit('Give each rival list as --rival "Name=web address or file", for example --rival "Cash Converters=/mnt/c/Users/you/Downloads/cc.txt"')
        rival_lists.append((label.strip(), src.strip()))
        args = args[:i] + args[i + 2:]
    for key in ("--shop", "--radius", "--country", "--label-a", "--label-b", "--list-a", "--list-b"):
        if key in args:
            i = args.index(key)
            opts[key] = args[i + 1]
            args = args[:i] + args[i + 2:]
    if len(args) != 3:
        sys.exit(__doc__)
    main(os.path.abspath(args[0]), args[1], args[2], shop=opts.get("--shop", "pawnbroker"),
         radius=float(opts.get("--radius", "3")), country=opts.get("--country", "GB"),
         label_a=opts.get("--label-a"), label_b=opts.get("--label-b"), list_a=opts.get("--list-a"), list_b=opts.get("--list-b"),
         rival_lists=rival_lists)
