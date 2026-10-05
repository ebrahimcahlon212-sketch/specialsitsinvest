I edited nothing. All 132 tests pass under `python3 -m unittest discover -v` (2.7 s). Round 8 fixes review-7 items 1 and 3 to 7. But the item 2 fix rejects the wording Savara's own filings actually use, so the Savara profile is still blocked. Bash was blocked partway through, so I finished with the read and search tools.

## Review-7 items

| # | Status |
|---|---|
| 1. Profile market value | **Fixed.** Code now computes market value as the Massive as-traded close × shares, and checks the share count against the saved SEC filing list (`profile.py:25-57`). Savara's 10-Q cover would pass the shares check: "205,460,015 shares of common stock ... outstanding" (`10q_2026_08_11_main_10_q/all.txt` L.109). |
| 2. First-product attribution | **Fixed, but now too narrow.** Disease-level sentences no longer match. The new pattern also rejects Savara's real wording (new problem 1). |
| 3. IBKR price convention | **Fixed.** Each IBKR close is compared with both Massive closes and both differences are recorded. A row is flagged only when it is more than one cent from both (`crosscheck.py:52-61`). Amendment 15 literally flags "any difference above one cent", so this is your call to accept. Rules version 4 now documents it. |
| 4. Where price differences go | **Fixed.** Bare `refclass review` lists flagged differences and counts missing checks. Build and show print counts only. There is a hidden bug (new problem 2). |
| 5. Census speed and resume | **Fixed.** One pair of requests per ticker, `--calls-per-minute` added, and saved successful responses are reused. Reuse only works if the dates are the same. The default end date is today, so a rerun on a later day downloads everything again unless you pass `--until`. The manual says so. |
| 6. Thin review output | **Fixed.** Only the fields and tags that differ are printed. Older disagreement files are found by searching the folder, and newer registry entries take priority. |
| 7. Conflicting IBKR updates | **Fixed.** A conflicting close now raises an error before anything is written, and identical rows are merged (`engine.py:220-226`). |
| 8. Earlier deferred items | **Still open.** Review-6 problem B is deferred to phase 3, and none of the live checks have been run. |

## Still open

- **Review-6 problem B:** the strict numeric prose check still isn't called by any real command. It is deferred to phase 3.
- **Live checks (your runs):**
  - IBKR response shapes, contract mapping and which price convention IBKR uses.
  - The full census after the Massive upgrade.
  - The four comparables priced from Massive.
  - Checking the target figures against the original report.
  - A real Savara profile, then `show savara` and acceptance.

## New problems

1. **The Savara profile can't be set to first-product with Savara's real filings (blocks amendment 12).** `profile.py:11-14` now accepts only phrases like "we have no approved products" or "we do not have any products approved for sale". None of Savara's filings use these phrases. What they actually say is:
   - "We have not obtained any regulatory approvals for a product candidate, commercialized a product candidate, or generated any product revenue" (`10k_2026_03_13_main_10_k/all.txt` L.1287).
   - The company "has no product revenue from inception to date" and "has not yet commenced commercial operations" (10-K and 10-Q notes).
   - MOLBREEVI "is not approved in any indication" (10-Q L.1701).

   Without a match, first-product has to be left empty and Savara lands in class A (`engine.py:371-375`) instead of B or C. That makes the new market value irrelevant. The round-8 test only uses made-up wording. A pattern that names the company and accepts "have not obtained any regulatory approvals" and "not approved in any indication" would fix this. So would a regression test that uses the Savara 10-K line.

2. **Bare `refclass review` will fail on any database built under the old rules** (`review.py:412-417`). `price_reviews` calls `report()`, which raises "Rules or features changed. Rebuild before reporting." The rules moved to version 4 in this round. The error happens before anything is printed, so the model disagreements are hidden too, even though they don't depend on the database. No `data/refclass.sqlite` exists yet, so this hasn't happened. It will if you build before the next rule change and then upgrade.

3. **Minor: the share-filing cutoff for a prospective profile is one day late** (`profile.py:41`). A filing dated the same day as the valuation close counts as available at that close, even if it was filed after the market closed. For Savara this would only matter if the valuation date fell on a 10-Q filing day.

No API key appears in the changed files. The only new key-related code is the existing header-only path.

**Verdict:** Round 8 fixes the market-value blocker and review-7 items 3 to 7, but the narrowed first-product check rejects Savara's actual 10-K wording, so the Savara profile and phase 1 acceptance are still blocked.

The Gmail, Google Calendar and Google Drive connectors need authorizing in your claude.ai connector settings before they can be used. This review didn't need them.
