Round 7 closes A, D and F and implements amendments 13 to 16. Problem C is still open: the new market-value check can't be satisfied by any real filing, which blocks the Savara profile that phase 1 acceptance needs.

**Tests:** all 124 pass under `python3 -m unittest discover -v` (2.7 s). I edited nothing. Bash was blocked partway through the review, so I finished with the read and search tools.

## Review-6 problems

| # | Status |
|---|---|
| A | **Fixed.** The `ibkr` allowlist now names the real tools (`get_price_snapshot`, `get_account_positions`, `get_account_balances`, `search_contracts`, `get_account_summary`), and they all exist on the connected server. Legacy prompts ask only for quotes, positions and balances. The test runs the actual hook against these names. Live CLI behaviour is still unverified. |
| C | **Not fixed.** Two new problems, items 1 and 2 below. |
| D | **Fixed.** Bad JSON, missing evidence and unreadable files now become a disagreement for that one candidate (`review.py:131-136`). A review file missing a candidate still stops everything (`review.py:81`). That is a file-level fault, so I think it's acceptable. |
| E | **Partly fixed.** A registry now stops stale folders from being listed, and tests point it at a temporary folder, so the real `data/refclass` stays clean. The output is still thin (item 6). |
| F | **Fixed.** The new test removes the day-one XBI bar for a comparable and confirms acceptance fails with "Comparable is unpriced". |

## Amendments 13 to 16

| # | Status |
|---|---|
| 13 | **Met.** Each window is fetched with `adjusted=false` and `adjusted=true`. Returns use the adjusted close. Market value and the comparables check use the as-traded close (`engine.py:87-88,129`, `acceptance.py:19`). Acceptance requires the four comparables to come from Massive. The saved fixture timestamps decode to midnight Eastern, so the session dates are correct. |
| 14 | **Met.** The default is two years of history. Earlier dates produce a gap and the events stay in the census. `--history-years` covers the run after the upgrade. |
| 15 | **Implemented, but compares the wrong close** (item 3). |
| 16 | **Met.** The key is read from `settings.env`, sent only in the Authorization header, and kept out of URLs, error bodies and messages. Requests are spaced at least 12.1 s apart through a shared file in `.locks/`, which is ignored. |

## API key check

No key appears in any tracked file:
- The only key-shaped string is `synthetic-test-secret` in `tests/test_review_six.py:126`.
- The long tokens in the Massive fixtures are Massive's `request_id` values.
- The saved URLs in the fixture manifest contain no key.
- `settings.env` is not in the git index. I confirmed the index search works by finding paths that are tracked.

I did not scan git history, because Bash was blocked.

## Remaining bugs and departures, most serious first

1. **The profile's market-value check can never pass on a real Savara document** (`profile.py:31-32`).
   - It requires the literal phrase "pre-news close" in a passage of at most 50 lines from the deal's `filings/` or `work/` folders.
   - That phrase is the kit's own term. No 10-K, 10-Q, 8-K or press release uses it.
   - So Savara's market value must be left empty, which keeps Savara out of the under-$3 billion class (`docs/refclass-phase1.md:47`). The only way round it is a hand-written note in `work/`, which defeats the primary-source rule.
   - Events already compute market value in code as close × shares (`engine.py:121-132`). The profile should do the same, as the spec's "code computes" principle says.
   - This blocks amendment 12's requirement for a Savara profile built from the deal documents.

2. **The first-product check accepts sentences about the disease rather than the company** (`profile.py:12`).
   - The pattern `no (FDA-approved|approved|commercial) products` isn't tied to the company.
   - So a 10-K sentence like "there are no approved products for the treatment of [disease]" sets `first_product=True`.
   - This is the same kind of error as the review-6 finding this round was meant to fix, and it applies directly to an orphan-disease company like Savara.

3. **The IBKR check probably compares mismatched prices** (`crosscheck.py:52`).
   - It compares IBKR closes with Massive's as-traded `close`.
   - IBKR's historical bars are normally split-adjusted (this is from memory, not from the repo; the live run should confirm it).
   - If so, every event for a stock that split or reverse-split afterwards is flagged, which is common among small biotechs. Real differences would be hidden among those false flags.
   - Comparing against `adjusted_close` too would fix it.

4. **Flagged differences aren't sent anywhere for review** (`engine.py:405-406`).
   - They are printed as raw JSON lines in build/show, mixed in with every "matched" and "missing" row, which is about six lines per event across the whole census.
   - They don't appear in `refclass review`, so amendment 15's "flagged for review" depends on reading that output.

5. **The full Massive census run will be slow and can't resume** (`massive.py:149,60`).
   - It makes one request per calendar year, even though the 50,000-row limit would cover all the history in one request.
   - The 12.1 s spacing is fixed even on the paid plan.
   - With `--history-years 20`, that is about 24 calls, or about 5 minutes, per ticker. A few hundred tickers take more than a day.
   - A live rerun downloads everything again because successful saved responses are never reused.
   - The run is in the foreground with no log under `~/`, which departs from the spec's rule for long jobs.

6. **Bare `refclass review` is still thin** (`review.py:232-236`).
   - It prints both reviews' full sets of assertions on one line rather than the tags that differ, which is what the spec asks for and the build notes claim.
   - Disagreement files from before round 7 don't appear until that run is reconciled again.

7. **`refclass update` overwrites IBKR checks without checking for conflicts** (`engine.py:218-221`). `assemble` raises an error when values conflict, but the update path silently replaces older observations.

8. **Still open from earlier rounds (not regressions):**
   - Review-6 problem B is deferred to phase 3, so the strict numeric prose check still never runs in a real command.
   - All live checks are still to be done: IBKR response shapes and contract mapping, the full census, the four comparables from Massive, the copying of the report targets, and `show savara`.

**Verdict:** Round 7 closes A, D and F and correctly implements amendments 13 to 16 with no key in the repo, but problem C's new market-value check can't be met by any real filing, so the Savara profile and phase 1 acceptance remain blocked.

Separately, the Gmail, Google Calendar and Google Drive connectors need authorizing in your claude.ai connector settings before they can be used. They weren't needed for this review.
