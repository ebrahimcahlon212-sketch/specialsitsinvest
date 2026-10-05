Round 10. Make only the three changes below and nothing else.

1. EDGAR acceptance times. The acceptanceDateTime field in SEC submissions data is Eastern local time even though it ends in Z. Parse it as America/New_York local time everywhere it is used, including the share-filing cutoff in profile.py and the 8-K announced_at in edgar.py. Fix test_same_day_share_filing_requires_acceptance_before_close so that 15:59:59 is available and 16:00:00 or later is not. Add a test using Apple's 10-Q row (acceptanceDateTime 2023-08-03T18:04:43.000Z, filingDate 2023-08-04), which only fits the Eastern reading. Then check the saved Savara submissions rows. Leaving out Forms 3, 4 and 5 and correspondence, every row whose Eastern acceptance time is after 17:30 should have the next business day as its filing date. Print how many rows were checked and list any that disagree.

2. Exception classes. Replace error-message matching with dedicated exception classes. The three version errors raised by engine.report() share one class, and review.py catches that class. The two inventory errors in inventory.py get separate classes, and test_after_close_filing_does_not_displace_prior_filing asserts the specific class.

3. Trade-name pattern (profile.py). Allow periods inside common abbreviations such as Inc. and Ltd. so a description containing them still matches, and add a test.

Keep every existing test passing and run python3 -m unittest discover before you finish.
