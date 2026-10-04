I ran the tests and checked the latest commit (`fdc63f7`, Phase 1 round 3) against both spec documents. I edited nothing.

**Tests:** `python3 -m unittest discover -v` ran 71 tests and all passed in 1.6 s. Bash refused my one extra script, which fed sample sentences to the date-type gate. So the date-gate findings below (items 4 and 5) come from reading the regex in `refclass/quality.py:92-103`, not from running it.

## Review-2 items

| # | Item | Status |
|---|---|---|
| R1-1 | Comparable test is circular | **Open.** The engine is unchanged, and there are still no independent bars or timestamps. |
| R1-2 | No data collection | **Partly fixed.** FDA and EDGAR collectors now exist. There is no IBKR collector, no census, and nothing feeds the collectors' output into `build`. |
| R1-3 | Synthetic XBI | **Open.** The label guard at `engine.py:209-212` is unchanged. |
| R1-4 | All-N/A gate bypass | **Partly fixed.** Arithmetic can no longer be N/A (`quality.py:152`), but one trivially correct computation is enough to pass. |
| R1-11 | Background build | **Partly fixed.** `--foreground` now works anywhere in the arguments. A real detached run is still untested. |
| R1-12 | `show NAME` ignores NAME | **Open.** There is no `deals/savara/refclass.json`, and the profile's source and locator are never re-read. |
| R1-15 | Gate inputs taken on trust | **Open.** The filing inventory and the completeness of the computations are still trusted. |
| N1 | Strict default breaks legacy commands | **Fixed.** `preflight` warns and continues, and the tests no longer patch it out. |
| N2 | Calculator sidecar name | **Fixed** in name (`calc.py:413`). In practice the path is dead, see item 10. |
| N3 | Research labels treated as publication | **Fixed.** Every step is research except `final` and `fund-final` (`run.sh:171-173`). |
| N4 | Bad evidence kills research steps | **Fixed.** Research mode skips validation and writes no evidence file. |
| N5 | Gate re-reads any file | **Fixed.** Reads are limited to the deal's `filings/` and `work/`, and traversal and symlinks are refused. |
| N6 | Parallel prompt appends | **Fixed.** The append was removed from `run_step`. |
| N7 | Error message and date wording | **Message fixed. Date wording partly fixed,** and one check got looser (items 4 and 5). |
| N8 | Housekeeping | **Fixed for review-2.md,** which is now committed. The same problem recurs with `review-3.md` (item 14). |

## Remaining bugs and departures, most serious first

1. **Phase 1 acceptance is still not met.**
   - There is no IBKR price collector and no real XBI series (amendment 5).
   - There is no census of approvals and CRLs since 2015.
   - The four comparables (Verona, KalVista, Crinetics, Liquidia) are not reproduced from independent data.
   - Collector output is only staged. `refclass build` still imports a prepared snapshot, so it does not "build the event table from all sources".

2. **Legacy commands no longer run any real check, which departs from amendment 1.**
   - Amendment 1 says existing commands run the gates and print failures without stopping.
   - The commit took the units and discount checks out of `catalysts.numbers` and the whole-holding headline out of `calc.compute`, and added no warning in their place.
   - `preflight` now only looks for an evidence file, which nothing in `run.sh` produces.
   - So PEY's -5047% discount or HVPE's 37% headline would render with no warning. Amendment 6 needs the outputs unchanged, but it does not rule out a warning on stderr, so both amendments could be met at once.

3. **No refclass output runs the gates in strict mode (amendment 1).**
   - `strict=True` and the `publication` extraction mode are never used by `run.sh` or `refclass`.
   - The only strict path is the standalone `refclass gates FILE` command (`__main__.py:63`).
   - `refclass show` prints numbers without passing any gate.

4. **The date-type gate is looser for goal dates.**
   - The words "expect", "anticipate" and "plan" are no longer rejected for `fda_goal` (`quality.py:101`).
   - So "We plan to submit the NDA and anticipate an action date of November 20, 2026" would pass. That is the company's own estimate, not an FDA goal date, which is the error the gate was added for (Opus and Viridian).

5. **The date-type gate blocks common correct wording (strict paths only).** By reading the regex, these all fail:
   - "(FDA) approved": the `)` breaks `FDA (?:has )?approved`.
   - "the FDA issued a complete response letter": only "received a complete response letter" is matched.
   - Any date written before the clause, as in "On November 20, 2026, the FDA approved…".
   - "Sept. 20": the month pattern is `September|Sep`, so the trailing "t" breaks it.
   - Zero-padded days such as "November 05".

6. **`refclass show savara` still prints only global context.** There is no Savara profile, and the profile's `source` and `locator` are never re-read (`engine.py:310-326`).

7. **The run lock key is the first two arguments** (`jobs.py:17`). So `./run.sh savara` and `./run.sh savara final` (or `savara biotech`) get different locks and can write to the same `out/` folder at the same time.

8. **The amendment 6 tests are thin.** Only the calculator and catalyst numbers are compared against the saved baseline. The biotech, finder, UK-events and valuation tests only check that output files exist (`test_amendments.py:121`).

9. **Collector gaps.**
   - `collect` runs in the foreground with no log under `~/` and no lock, even though a live census run is a long job. Two runs sharing a cache can overwrite each other's `manifest.json`.
   - The FDA `since`/`until` dates are filtered after download, not sent in the query (`fda.py:82-101`). A full Drugs@FDA pull therefore always hits the 25,000-record skip limit unless someone splits the search by hand.
   - One malformed EDGAR `filingDate` aborts the whole collection instead of being recorded as a gap (`edgar.py:114`).

10. **The calculator's evidence file is never written, and every legacy command now warns.**
    - The `terms` step runs in research mode, so `terms.txt.quality.json` is never created, and `calc.py deal` always falls back to `quality.json`.
    - Every calc, catalysts, biotech, find, UK-events and valuation run prints "Quality gates unverified". That is new output compared with before phase 1, and it is noise that carries no information.

11. **The real detached `refclass build` has never been run** (R1-11).

12. **Drugs@FDA comes from the openFDA API, not the "data files" the spec names.** Amendment 4 arguably allows this, but it should be recorded as an amendment. The API also covers only CDER biologics, so CBER BLAs are missing, and this is not reported as a gap.

13. **The evidence file inventory and the arithmetic list are still trusted** (R1-15 and R1-4 remainder).

14. **Housekeeping.**
    - `docs/build/review-3.md` is untracked and empty (0 bytes).
    - `knowledge/research-standards.md` and `knowledge/INDEX.md` are missing, though the spec says to read them first.
    - `edgar.py:9` relies on the private class `lib.prep._HTMLText`, and `lib/` has no `__init__.py`, so the import only works when the command runs from the kit folder.

**Verdict:** The commit fixes the regressions from review-2 and all 71 tests pass, but phase 1 is still not accepted, because there are no prices or XBI, no census and no independent comparables, and the legacy gates no longer check anything.
