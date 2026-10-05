I reviewed the round-9 changes against the task file and the three new problems in review-8. I couldn't run the test suite, and I changed no files.

**What I reviewed.** The latest commit, `702287d`, is still round 8. The round-9 work is staged but not committed, so I reviewed the staged diff. There is also an untracked `docs/build/review-9.md`, which I didn't read.

**Tests not run.** Bash was denied in this session's don't-ask mode after my first two commands, so `python3 -m unittest discover` did not run. I have no pass or fail result, and the four new tests in `tests/test_review_eight.py` are unverified.

## The four required changes

| # | Change | Status |
|---|---|---|
| 1 | First-product wording (`profile.py:30-43`) | **Done.** It accepts "we have / the company / <company> has not obtained any regulatory approvals for a product candidate". It also accepts "<product> is not approved in any indication" when the product is the profile's `drug` or is named as "a trademark of <company>" in the same text. Disease-level sentences, unrelated products and competitors are rejected, and the test has negative cases for each. |
| 2 | Out-of-date database in `refclass review` (`review.py:263-272`) | **Done.** The three version errors from `report()` are caught, one "skipped … refclass build must be rerun" line is printed, and the disagreements are still printed. The test covers a changed version number and changed text, for both the rules file and the features file. One weak point is that it catches errors by matching their exact message text, so rewording a message in `engine.py` would bring the crash back. |
| 3 | Same-day filing cutoff (`profile.py:9-20`, `inventory.py:9-40`) | **Done as written, but probably wrong for real EDGAR data** (see the main problem below). An unknown acceptance time is treated as unavailable, as the task asks. A filing made after the close does not replace the earlier filing as the one used for share counts. |
| 4 | Amendment 17 | **Done.** The wording matches the task and replaces amendment 15's one-cent rule. |

## The new tests use Savara's real filing wording

I checked both strings against the filings.

- **10-K L.1287:** the test text matches `deals/savara/work/10k_2026_03_13_main_10_k/all.txt` (tag L.1287, file line 724) word for word, including "We have not obtained any regulatory approvals for a product candidate, commercialized a product candidate, or generated any product revenue."
- **10-Q L.1701:** the test text matches `10q_2026_08_11_main_10_q/all.txt` (tag L.1701, file line 870) word for word: "[1] MOLBREEVI is the proposed trade name for molgramostim inhalation solution. It is not approved in any indication. MOLBREEVI is a trademark of Savara Inc."

The disease-level negative is "There are no approved therapies for autoimmune PAP." The extra test sentence "MOLBREEVI is not approved in any indication." is made up, which is fine because it only tests the profile `drug` path.

## Problems

1. **EDGAR's acceptance times are probably Eastern time, not UTC, which would undo change 3.** `available_at_close` reads the trailing `Z` as UTC (`profile.py:16`). As far as I know (from memory, not from these files), the SEC submissions JSON writes Eastern local time with a `Z` added. For example, Apple's 10-Q for the quarter to June 2023 shows `2023-08-03T18:04:43.000Z` with filingDate 2023-08-04. That only makes sense as 18:04 Eastern, because EDGAR gives filings accepted after 17:30 Eastern the next day's date.
   - **Effect:** a 10-Q accepted at 16:05 Eastern on the valuation date, written as `16:05:00.000Z`, would be converted to 12:05 Eastern and counted as available. That is the case this round was meant to block.
   - **Test:** `test_same_day_share_filing_requires_acceptance_before_close` builds in the UTC reading, with `19:59:59Z` counted as available.
   - **Check before accepting:** compare one saved Savara submissions row with the "Accepted" time on its EDGAR filing index page. The same field also feeds 8-K `announced_at` (`edgar.py:129`).
2. **The new tests can't tell the two inventory errors apart.** `inventory.py:30` now ends with "…cannot establish the latest SEC periodic filing". The task didn't ask for this wording. Because of it, the regex `'latest SEC'` in `test_after_close_filing_does_not_displace_prior_filing` matches both the "no prior filing" error and the "share evidence omits latest filing" error. The final subtest would therefore pass for the wrong reason.
3. **Minor:** the trade-name pattern `[^.]+` (`profile.py:42`) fails if the product description contains a period, such as "Inc." or "e.g.". This doesn't affect Savara's wording.

**Verdict:** All four changes are made and the tests quote Savara's 10-K and 10-Q exactly, but the suite wasn't run here and the same-day cutoff probably misreads EDGAR's acceptance times, so I would hold acceptance until both are checked.

The Gmail, Google Calendar and Google Drive connectors need authorizing in your claude.ai connector settings before they can be used. This review didn't need them.
