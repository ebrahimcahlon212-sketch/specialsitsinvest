#!/usr/bin/env python3
"""A fair sample of overlap areas, and an estimate scaled up from it.

The closest overlaps are the worst cases, so their results can't be applied to
every area. This picks a random sample from the rest, spread evenly across the
distance range, and after the web checks it works out the share of areas that
would fail each screen, with a 90% margin of error, and scales that up to all
the areas. The closest areas already checked are added as exact counts.

Usage
  sample_areas.py select OUTDIR N SKIP [SEED]   choose N areas after skipping the SKIP closest
  sample_areas.py estimate OUTDIR               combine the closest check and the sample into one estimate
"""
import json
import math
import os
import random
import re
import sys

POSTCODE = re.compile(r"\b([A-Z]{1,2}[0-9][A-Z0-9]?)\s*([0-9][A-Z]{2})\b")
Z90 = 1.645


def load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def overlap_rows(out):
    data = load(os.path.join(out, "overlap.json"), {})
    rows = [r for r in data.get("rows", []) if r.get("overlap")]
    rows.sort(key=lambda r: (r.get("nearest_b_km") if r.get("nearest_b_km") is not None else 999, r.get("postcode", "")))
    return rows, data


def cmd_select(out, n, skip, seed):
    rows, data = overlap_rows(out)
    if not rows:
        sys.exit("No overlap areas found. Run the overlap check first.")
    pool = rows[skip:]
    n = min(n, len(pool))
    rng = random.Random(seed)
    # Stratified: split the pool into n equal bands by distance and pick one area at random from each
    picked = []
    for i in range(n):
        lo, hi = int(i * len(pool) / n), int((i + 1) * len(pool) / n)
        band = pool[lo:hi] or pool[lo:lo + 1]
        picked.append(rng.choice(band))
    info = {"population": len(rows), "skipped_closest": skip, "pool": len(pool), "sample": len(picked), "seed": seed,
            "radius_km": data.get("radius_km"), "areas": picked}
    with open(os.path.join(out, "competition-sample-areas.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=1)
    L = ["# Areas to check, a random sample", "",
         "There are %d overlap areas. The %d closest were checked before, so this sample is drawn from the other %d. "
         "They were split into %d equal bands by distance and one area was picked at random from each, with seed %s, "
         "so the results can be scaled up to all of them." % (len(rows), skip, len(pool), len(picked), seed), "",
         "Check exactly these areas and do not swap any out. If one can't be checked, say so and mark it unchecked.", "",
         "| Place | Ramsdens postcode | Nearest H&T |", "|---|---|---|"]
    for r in picked:
        d = r.get("nearest_b_km")
        L.append("| %s | %s | %s |" % (r.get("place", ""), r.get("postcode", ""), "%.2f km" % d if d is not None else ""))
    with open(os.path.join(out, "competition-sample-areas.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("  sample      %d areas picked at random from the %d beyond the %d closest" % (len(picked), len(pool), skip))


def first_int(cell):
    m = re.search(r"\d+", cell or "")
    return int(m.group(0)) if m else None


def parse_areas_block(text):
    m = re.search(r"<<<BEGIN AREAS>>>(.*?)<<<END AREAS>>>", text, re.S)
    rows = []
    if not m:
        return rows
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("checked", True) is False:
            continue
        rows.append({"postcode": str(d.get("postcode", "")).upper(),
                     "d1": first_int(str(d.get("d1_before"))), "d2": first_int(str(d.get("d2_before"))),
                     "d3": first_int(str(d.get("d3_before")))})
    return rows


def parse_table(text):
    """The brand-count table in a competition report, for reports written before the areas block existed."""
    rows, cols = [], None
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            cols = None if rows else cols
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cols is None:
            names = [c.upper() for c in cells]
            if "D1" in names and "D2" in names and "D3" in names:
                cols = {k: names.index(k) for k in ("D1", "D2", "D3")}
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        m = POSTCODE.search(cells[0].upper())
        if not m:
            continue
        rows.append({"postcode": "%s %s" % (m.group(1), m.group(2)),
                     "d1": first_int(cells[cols["D1"]]), "d2": first_int(cells[cols["D2"]]), "d3": first_int(cells[cols["D3"]])})
    return rows


def results_from(path):
    if not os.path.exists(path):
        return []
    text = open(path, encoding="utf-8", errors="replace").read()
    return parse_areas_block(text) or parse_table(text)


def wilson(x, n, pop=None):
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = x / float(n)
    denom = 1 + Z90 ** 2 / n
    centre = (p + Z90 ** 2 / (2 * n)) / denom
    half = Z90 * math.sqrt(p * (1 - p) / n + Z90 ** 2 / (4 * n * n)) / denom
    if pop and pop > n:
        half *= math.sqrt((pop - n) / float(pop - 1))
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def cmd_estimate(out):
    rows, _ = overlap_rows(out)
    info = load(os.path.join(out, "competition-sample-areas.json"), {})
    closest = results_from(os.path.join(out, "competition.md"))
    sample = results_from(os.path.join(out, "competition-sample.md"))
    if not sample:
        sys.exit("No sample results found. Run the sampled competition step first.")
    population = len(rows) or info.get("population", 0)
    unsampled = max(0, population - len(closest) - len(sample))
    L = ["# How many areas would fail, scaled up from a random sample", "",
         "Worked out by Python. The %d closest areas count exactly as checked. The %d sampled areas give the share "
         "that fails, which is applied to the %d areas not checked, with a 90%% margin of error. Each row of the overlap "
         "list is a Ramsdens store, so a town with two stores counts twice." % (len(closest), len(sample), unsampled), "",
         "| Who counts as a rival | Screen | Closest, exact | Sample | Share of sample | Estimated total of %d areas | 90%% range |" % population,
         "|---|---|---|---|---|---|---|"]
    names = {"d1": "Confirmed pawn lenders only", "d2": "Adding Cash Converters", "d3": "Adding sale-and-buy-back shops"}
    for key in ("d1", "d2", "d3"):
        for limit, label in ((3, "Left with 1 or 2 brands"), (4, "Left with 3 or fewer")):
            c_rows = [r for r in closest if r[key] is not None]
            s_rows = [r for r in sample if r[key] is not None]
            if not s_rows:
                continue
            c_fail = sum(1 for r in c_rows if r[key] <= limit)
            s_fail = sum(1 for r in s_rows if r[key] <= limit)
            p, lo, hi = wilson(s_fail, len(s_rows), len(s_rows) + unsampled)
            est = c_fail + s_fail + p * unsampled
            L.append("| %s | %s | %d of %d | %d of %d | %.0f%% | %.0f | %.0f to %.0f |" % (
                names[key], label, c_fail, len(c_rows), s_fail, len(s_rows), p * 100, est,
                c_fail + s_fail + lo * unsampled, c_fail + s_fail + hi * unsampled))
    L += ["", "Brand counts include both merging chains, so an area fails the first screen when three or fewer brands are "
          "present before the merger, and the second when four or fewer are.", ""]
    with open(os.path.join(out, "competition-estimate.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L[6:6 + 6]))


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 4 and a[0] == "select":
        cmd_select(a[1], int(a[2]), int(a[3]), int(a[4]) if len(a) > 4 else 2026)
    elif len(a) == 2 and a[0] == "estimate":
        cmd_estimate(a[1])
    else:
        sys.exit(__doc__)
