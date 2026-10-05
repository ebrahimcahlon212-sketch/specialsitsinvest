Round 9. Make only the four changes below and nothing else.

1. First-product attribution (profile.py). Accept Savara's real filing wording while still rejecting disease-level sentences. A sentence counts only when its subject is the company or its own product. Accept wording such as "have not obtained any regulatory approvals for a product candidate" and "<product> is not approved in any indication". Keep rejecting sentences such as "there are no approved therapies for autoimmune PAP". Add regression tests that use the exact Savara lines cited in docs/build/review-8.md (10-K L.1287 and 10-Q L.1701) as positives, plus a disease-level sentence as a negative.

2. Stale database in refclass review (review.py). When the rules or features changed after the build, price_reviews must not raise. Print one line saying the price review was skipped and refclass build must be rerun, then still print the model disagreements. Add a test that builds under one rules version, changes the version and runs bare refclass review.

3. Share-filing cutoff (profile.py). A filing is available at a valuation close only if it was filed on an earlier date, or on the same date with an EDGAR acceptance time before 16:00 Eastern. If the acceptance time is unknown, treat a same-day filing as unavailable. Add a test with a 10-Q filed after the close on the valuation date.

4. Add amendment 17 to docs/spec-amendments.md. An IBKR close is flagged only when it differs by more than one cent from both Massive closes, and both differences are recorded. This replaces the one-cent wording in amendment 15.

Keep every existing test passing and run python3 -m unittest discover before you finish.
