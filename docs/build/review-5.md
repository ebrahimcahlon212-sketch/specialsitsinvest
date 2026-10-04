I've reviewed commit `4e9fc4f` (Phase 1 round 5) against `docs/system-spec.md` and `docs/spec-amendments.md`, and I edited nothing. Round 5 fixes most of what review 4 found. Phase 1 still can't pass acceptance, mainly because the new bar fetcher doesn't fit the IBKR tool it's meant to call.

**Tests:** `python3 -m unittest discover -v` ran 96 tests and all passed in 1.9 s. I couldn't run any extra scripts because Bash beyond the test run was blocked. The findings below come from reading the code and the saved fixtures.

## Review-4 new problems

| # | Item | Status |
|---|---|---|
| N1 | Profile substring check | **Fixed, but now too strict** (finding 5) |
| N2 | Date gate reading prose | **Fixed.** Dates now come only from JSON fields. I checked that SEC's `acceptanceDateTime` really is UTC: the fixture's index page says 16:26:01 Eastern and the JSON says `20:26:01Z`. |
| N3 | IBKR file reads slow down sharply with size | **Fixed** (set lookup, cached reads, a test that counts reads) |
| N4 | Collected sources outside deal folders | **Fixed in code** (the raw folder is allowed and symlink escapes are rejected). `docs/manual.md` still doesn't mention it (finding 9). |
| N5 | Bounded FDA query never tested on a real response | **Fixed.** Real bounded responses are saved and the URL-swapping test shim is gone. |
| N6 | Partial-tender warning wrong or crashing | **Fixed** |
| N7 | Catalyst currency check can't fire | **Partly fixed** (finding 7) |
| N8 | Coverage overwritten by later partitions | **Fixed** |
| N9 | Excluded events not re-checked | **Fixed.** Exclusions are re-checked and their sources re-hashed. |
| N10 | Housekeeping | **Partly fixed** (finding 9) |

From review 4's "still open" table, item 12 (openFDA API) is now closed by amendment 7. Items 1, 2, 6 and 13 are still open.

## Remaining bugs and departures, most serious first

1. **`fetch-bars` can't work with the IBKR tool that's actually configured** (amendments 10 and 12). The connected server's `get_price_history` takes a contract ID and a period of at most `FIVE_YEARS`, counted back from today. It has no end-date parameter and returns plain OHLCV bars.
   - `transcript_bars` (`refclass/bars.py:172-178`) needs a `bars` list containing `adjusted_close` and `adjustment="split_only"`. The real tool returns neither, so every live run will stop.
   - Even with a fixed mapping, events before about October 2021 can't be priced, so the 2015-onward census can't be priced either.
   - The only test input is an artificial transcript (`tests/fixtures/ibkr-tool-sample.jsonl`).
2. **The bar-fetching session can call order tools** (`run.sh:73`). The `ibkr-bars` mode allows the whole `mcp__ibkr` server under `--permission-mode dontAsk`. That includes `create_order_instruction`, the watchlist and alert tools that change data, and the delete tools. Only the prompt text tells the model not to use them. This breaks the spec rules "never call an order endpoint" and "the broker link is read-only". The older `ibkr` mode already had this problem, and the new command copies it.
3. **Excluded candidates without a ticker or 8-K make the whole build fail.** `engine.py:232` requires `ticker`, `announced_at` and the other key fields on every event before it looks at the exclusion. That includes events both reviews marked `exclude`. A private sponsor or a large pharma company has no 8-K for the event, so the build raises an error. If those candidates are left out of the reviewed events instead, they stay pending, and `acceptance.py:94` fails. The test avoids this by giving its excluded event `ticker='TEST'`.
4. **Event review doesn't work the way the spec describes.**
   - `reconcile` (`review.py:759`) counts every event as a disagreement unless both models return exactly the same `event_json`, including evidence line ranges and drug spellings. In practice nearly every candidate will end up as a disagreement.
   - There is no way for Ebrahim to resolve a disagreement. The only route is to edit the model reviews until they match.
   - The spec says disagreements "wait in `./run.sh refclass review`", but `refclass review` now has required arguments (`__main__.py:57`), so running it bare fails with an error instead of listing disagreements.
5. **The Savara profile check will reject real filing wording** (`refclass/profile.py:459-471`).
   - The first-product pattern misses the usual phrase "we have no products approved for commercial sale".
   - The market value check needs the ISO date (YYYY-MM-DD) and the literal text "USD" or "US$" in the cited lines, plus the market value written out as a raw number. Filings write "$1.2 billion as of June 30, 2026", which fails all three tests.
   - In practice Ebrahim would have to write his own source note, which weakens the source check. A profile can also claim `first_product: false` without any evidence being checked.
6. **The acceptance test compares split-adjusted closes with the report's prices** (`acceptance.py:119`, `engine.py:87`). The engine stores `adjusted_close` as `pre_close`, but the Savara report's prices are most likely the closes as quoted at the time. Any later split would cause a false failure. The check also covers only the closes Ebrahim types into the targets file, not the report's day-one and day-two returns.
7. **The catalyst currency check still can't catch the PEY error.** `prompts/catalysts.md:31` still tells the model to give `anchor_value` in the trading units (pence for London). So the new `anchor_unit` field will just repeat `price_unit`, and a currency mismatch can't be detected.
8. **The FDA collector doesn't stop a search window from conflicting with its own date window** (`fda.py:86`). The first saved Drugs@FDA request ANDs a 2025-2026 window inside the 2015-2026 one. That URL is saved under `data/refclass/raw/`, while its recorded scope says `since=2015-01-01`. The acceptance test does reject any partition with an extra search, so this can't pass acceptance.
9. **Housekeeping.**
   - `codex-5.md` says nothing was committed and that review-4 is uncommitted. That was out of date once this commit was made, which is the same mistake N10 flagged.
   - `docs/build/review-5.md` is untracked and empty again.
   - The `.manifest.lock` files were committed.
   - `refclass-rules.md` is now version 2 but still says "Any change creates version 2".
   - `docs/manual.md` doesn't mention `fetch-bars`, `prepare-review`, `review-models`, `profile`, `acceptance` or `data/refclass/raw/`.
   - `research-standards.md` still contains no investor feedback, which it states openly.
10. **Older items still open.** Amendment 12's live acceptance hasn't been met: there are no real bars, no XBI data, no census, no reproduced comparables, and no Savara documents or `show savara` output. Legacy commands still skip the evidence checks when no evidence file exists (item 2). The general prose gate still trusts the arithmetic list it is given (item 13).

**Verdict:** Round 5 closes most of the review-4 problems and all 96 tests pass, but phase 1 can't be accepted yet. `fetch-bars` doesn't match the configured IBKR tool and can reach its order tools, and finding 3 blocks a real census build.
