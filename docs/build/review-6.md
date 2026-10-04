I edited nothing. All 111 tests pass (`python3 -m unittest discover -v`, 2.4 s). Bash was blocked after a few commands, so I couldn't run the Claude CLI help or any extra scripts. The findings below come from reading the round 6 diff against `docs/system-spec.md` and the 12 amendments.

## Review-5 items

| # | Item | Status |
|---|---|---|
| 1 | `fetch-bars` doesn't fit the configured IBKR tool | **Still open.** The request now matches the real `get_price_history` (contract ID, `FIVE_YEARS`, no end date). Plain OHLCV responses are now saved as gaps instead of stopping the run. But that tool only ever returns plain OHLCV, so every live bar becomes a gap and no event can be priced. History before about October 2021 is also out of reach, so the 2015-onward census can't be priced. Fixing this needs a spec decision, not more code. |
| 2 | Bar session can call order tools | **Fixed for `ibkr-bars`.** There is now an exact allowlist plus a PreToolUse hook that blocks everything else, and `--setting-sources ""`. Whether the CLI and the hook behave this way live is unverified. The same change breaks legacy commands (new problem A). |
| 3 | Excluded candidates without a ticker or 8-K break the build | **Fixed** (`engine.py:236-249`). Reviewed exclusions only need an ID, company, source and locator, and their review seal is checked. |
| 4 | Review workflow | **Mostly fixed.** Reviews are now compared on substance, `--resolve` takes Ebrahim's decisions without editing the model reviews, and bare `refclass review` works. Two smaller gaps remain (new problems D and E). |
| 5 | Savara profile check | **Fixed as asked**: the usual "no products approved" wording, written-out dates, and `$` amounts with thousand/million/billion. It still accepts the wrong kind of market value (new problem C). |
| 6 | Acceptance compared adjusted closes with report prices | **Fixed in code.** Report closes are compared with `*_unadjusted_close`, and day-one and day-two returns are checked to 0.5 bp. Whether the targets file was copied correctly from the report is still a manual step. |
| 7 | Catalyst currency check can't fire | **Fixed.** The prompt now asks for the anchor in its source currency and gives a set format for FX rates. |
| 8 | FDA search can conflict with its own date window | **Fixed** (`fda.py:75-81`). One side effect is that `\bTO\b` with `re.I` rejects any search containing the word "to". |
| 9 | Housekeeping | **Mostly fixed.** The lock files are removed and ignored, the rules wording is fixed, and the manual covers the new commands and `data/refclass/raw/`. `codex-5` is corrected. `docs/build/review-6.md` is untracked and empty again (0 bytes), the same thing review 5 flagged. `research-standards.md` still has no investor feedback. |
| 10 | Older items | **Item 2 fixed** (missing evidence now prints a warning). **Item 13 partly fixed** (new problem B). **Amendment 12 live acceptance is still open**: no real bars, census, XBI data, Savara documents or `show savara` output. |

## New problems, most serious first

**A. The legacy IBKR steps can no longer reach the real tools** (`lib/ibkr_readonly.py:16`). This breaks amendment 6, which requires existing commands to behave exactly as before.
- The `ibkr` allowlist names `get_stock_price`, `get_market_data`, `get_positions` and `search_contract`. None of these exist on the connected `ibkr` server.
- The server's real tools are `get_price_snapshot`, `get_account_positions`, `get_account_balances`, `search_contracts` and `get_account_summary`. Only the last two are on the list.
- The hook now blocks every quote step (catalysts, biotech, refresh, finder, UK quotes) from fetching a price. Sizing loses positions and balances.
- Before this commit these steps had the whole server. No test covers it, because the guard tests use made-up tool names.

**B. The strict numeric prose check never runs in a real command.** `publication` mode only appears in tests. `run.sh:181-183` passes only `research` or `legacy`.
- Its matching rules would reject most filing-based numbers anyway:
  - `str(1200)` doesn't match a source written "1,200".
  - A plain `37` doesn't match a "37%" token.
  - Dates must appear in ISO form in the source.
- So review-4's item 13 is closed only on paper.

**C. The profile check accepts the wrong market value** (`profile.py:41-47`). Any `$` amount near "market value" passes, including the 10-K cover's "aggregate market value… held by non-affiliates". That figure is free float, not market cap. The spec's band is the market value at the pre-news close. The first-product pattern `first … commercial product` also matches "our first commercial product, X, launched…", which means the opposite.

**D. One bad model review stops the whole reconcile** (`review.py:163-165`). A review that decides `exclude` without `review_evidence`, or that cites a file that can't be read, raises `KeyError` or `ValueError` from `seal()`. That aborts every candidate, including ones Ebrahim has already resolved, instead of turning that one candidate into a disagreement.

**E. Bare `refclass review` is thin and can be stale** (`__main__.py:85-95`). It prints only candidate IDs and file paths, not the tag disagreements the spec says it lists. It also gathers every `disagreements.csv` under `data/refclass`, so files from older runs keep listing candidates that were resolved in a different output folder.

**F. A regression test is missing.** Acceptance now waives completeness for every IBKR partition (`acceptance.py:36-38`). That is safe only because each comparable is separately checked as `priced`. No test shows that a missing XBI bar on a comparable's dates still fails.

**Verdict:** Round 6 fixes review-5 items 3 and 5–8 and locks down the bar session, but phase 1 still can't be accepted: the configured IBKR tool can't supply usable bars, and the new read-only allowlist breaks every legacy IBKR quote step.
