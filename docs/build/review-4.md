I checked commit `94c0a08` (Phase 1 round 4) against `docs/system-spec.md`, `docs/spec-amendments.md` and each item in `review-3.md`. I edited nothing.

**Tests:** `python3 -m unittest discover -v` ran 86 tests and all passed in 1.7 s. My extra scripts were blocked, as in review 3: one fed sample sentences to the date gate, the other listed the CRL response's date fields. So the date-gate items below come from reading the regex in `refclass/quality.py:92-105`, not from running it.

**Closed since review 3:** items 3, 4, 7, 8, 9, 10, 11 and 14, and R1-11. Item 5 is closed for the five listed examples but has a new gap (N2 below). For item 8, I couldn't regenerate the baseline from `1429cc8`. But `git diff 1429cc8 HEAD` shows the biotech, finder, UK-events and valuation code changed only by the added `preflight` calls, which now return silently.

## Still open

| # | Item | Status |
|---|---|---|
| 1 | Phase 1 acceptance | **Open.** `--collection` now joins collected candidates to reviewed events (`pipeline.py`), and saved IBKR bars can be loaded (`collectors/ibkr.py`). Still missing: a live IBKR historical adapter, real XBI bars, the 2015+ census and reproduction of the four comparables. |
| 2 | Legacy commands check nothing (amendment 1) | **Partly fixed.** The discount and partial-tender checks now warn based on the actual results. The checks that need an evidence file (staleness, listing, attribution, date type, arithmetic) are silently skipped, because `preflight` returns `None` when there is no evidence file (`quality_gate.py:17`). See also N6 and N7. |
| 6 / R1-12 | `refclass show savara` | **Open.** There is no Savara profile or Savara documents. The CLI test now expects `show savara` to exit 1 with no output (`test_engine.py:245`). The new profile source check is weak (N1). |
| 12 | openFDA API instead of the Drugs@FDA data files | **Open.** The missing CBER coverage is now reported, but no amendment records the switch to the API. |
| 13 / R1-4 / R1-15 | Trusted inventory and arithmetic list | **Partly fixed.** The refclass path now re-reads the SEC inventory and recomputes its numbers. The prose evidence gate still trusts the arithmetic list it is given. |
| R1-1 / R1-3 | Circular comparables and synthetic XBI | **Open on data.** Production prices must now match a saved IBKR JSON line, which closes the relabelling bypass. No real bars exist yet. |

## New problems

1. **The deal-profile source check is a substring test** (`engine.py:340`, `engine.py:345`).
   - A market value of `300000000` passes against text that says `1300000000`.
   - A float such as `1.2e9` can never pass.
   - Nothing checks currency or the as-of date, although the error message says "in USD".
   - The first-product check matches "our first product candidate", which is common filing wording.
2. **The date gate rejects the most common press-release form.** "On November 20, 2026, the U.S. Food and Drug Administration (FDA) approved X" fails, because the sentence splitter breaks after "U.S." and the full agency name doesn't fit the pattern. The reverse error also exists. "FDA approved X on March 3, 2026, ahead of its PDUFA date of November 20, 2026" passes as a November 20 action, because of the 100-character span in `quality.py:101`. I found these by reading the regex, not by running it.
3. **IBKR ingestion slows down sharply with large files** (`ibkr.py:31`). `raw not in parsed` scans the whole list for every line, so the time grows with the square of the file size. A single file of bars since 2015 could effectively hang. Reusing the quote reader here only serves as a filter.
4. **Collected sources can't pass strict publication where they are stored.** Strict publication only reads `deals/*/filings` and `deals/*/work` (amendment 3). The SEC inventories and IBKR bars therefore have to sit inside a deal folder. The collector cache and comparables such as Verona aren't deals, and the manual doesn't describe this workflow.
5. **The bounded FDA query is no longer tested against a real response (amendment 4).** The test shim swaps in the old saved URL, and the offline CLI test now expects 0 candidates. Whether `letter_date:[YYYYMMDD TO YYYYMMDD]` works on the CRL endpoint is unverified.
6. **The partial-tender warning can be wrong or crash** (`calc.py:231-235`).
   - `spread_pct` includes target dividends but `whole_holding` doesn't, so a tender deal that also pays a dividend gets a false warning.
   - `whole_holding` isn't wrapped in `warn_check`, so a `GateError` would crash a legacy calc run, which breaks amendment 6. For example, a negative back-end price would trigger it.
7. **The catalyst currency-mismatch check can't fire on real inputs.** It needs `anchor_currency`, `price_unit` or similar fields, and `prompts/catalysts.md` never asks for them. Only the -50% to 90% range check is live, though that one does catch PEY.
8. **Coverage metadata is overwritten** (`pipeline.py:22`). Coverage is keyed by source, so several partitions of one source keep only the last partition's scope. The openFDA skip limit makes such partitions necessary.
9. **Excluded events aren't re-checked at publication.** `publication.check` re-verifies only the eligible events, so a wrongly excluded event shrinks a class without any warning.
10. **Housekeeping.**
    - `codex-4.md` says "No commit was made", which is out of date.
    - `docs/build/review-4.md` is untracked and empty again.
    - `research-standards.md` summarises the build reviews rather than the investor's feedback, which the file itself says.

**Verdict:** Round 4 fixes most of the review-3 regressions and all 86 tests pass, but phase 1 is still not accepted: there is no live price or XBI data, no census, no reproduced comparables and no working `show savara`, and the new profile and date checks have real false-pass and false-fail cases.
