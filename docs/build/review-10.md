I reviewed commit `80e3b93` ("Phase 1 round 10") and the test suite passes. One part of the task is still unconfirmed: the check of the saved Savara submissions rows. I changed no files.

**Tests:** `python3 -m unittest discover` ran 140 tests, all OK. The two "Warning." lines in the output come from tests that trigger gates on purpose.

## The three required changes

| # | Change | Status |
|---|---|---|
| 1 | EDGAR acceptance times read as Eastern time | **Code and tests done. The Savara check is not shown.** A new function, `acceptance_datetime` (`edgar.py:25`), reads the time as New York local time. Every place that reads `acceptanceDateTime` now uses it: the share-filing cutoff (`profile.py:17`), the 8-K `announced_at` (`edgar.py:136`), `review.draft` and `quality.acceptance_time`. In the same-day test, `15:59:59.000Z` now counts as available, while `16:00:00.000Z` and `19:59:59Z` do not. The Apple test uses the 10-Q row from the task and checks the 18:04 Eastern reading, the next-day filing date and the switch to −05:00 in winter. |
| 2 | Exception classes | **Done.** `ConventionVersionError` (a subclass of `ValueError`) covers the "unsupported rules version", "unsupported features version" and "rules or features changed" errors from `report()`. `review.py:264` now catches the class instead of matching message text, and a new test shows that a plain `ValueError` with the old message is no longer caught. `inventory.py` has two separate classes, and `test_after_close_filing_does_not_displace_prior_filing` asserts `MissingLatestShareFilingError`. This fixes problem 2 from review-9. |
| 3 | Trade-name pattern | **Done.** The pattern now lets `Inc.`, `Ltd.`, `Corp.` and `Co.` appear inside the description, and a test covers all four. Another test confirms that a full stop between sentences still breaks the match. |

## Problems

1. **The Savara check isn't in the commit, and I couldn't run it.** The task asks for every non-Form 3, 4 or 5, non-correspondence row accepted after 17:30 Eastern to be checked for a next-business-day filing date, with a printed count and a list of rows that disagree. Nothing in the commit does this. The saved submissions are in `tests/fixtures/collectors/2d26b5c3fd1649a4-869ba9fcac4a.response` (CIK 0001160308, Savara Inc). After my first few commands, Bash was blocked in this session's don't-ask mode, so I couldn't run the check myself. It still needs running, along with a request for the count and any rows that disagree.
2. **`acceptance_datetime` overwrites any timezone already in the string** (`edgar.py:27`). A value ending in `+00:00` would be read as Eastern time without any warning. Real SEC data always ends in `Z`, so this is low risk. The test row `-04:00` only passes because it is already Eastern.
3. **Minor inconsistency.** The matching "Rules or features changed. Rebuild before updating." error in `build()` (`engine.py:198`) is still a plain `ValueError`. The task only covered `report()`, so this is not a breach.

Nothing outside the three changes was modified, apart from the call sites that change 1 requires and the `test_review_four` timestamps that the Eastern reading forced.

**Verdict:** All three changes are made correctly and all 140 tests pass, but I would hold acceptance until the Savara submissions check from change 1 is run and its count and disagreeing rows (if any) are shown.
