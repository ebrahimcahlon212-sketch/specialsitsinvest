Round 11. Undo change 1 of round 10 and keep every other round 10 change.

1. The acceptanceDateTime field is UTC. A check of 539 saved Savara rows showed the Z is genuine. Read as UTC and converted to New York time, all but 18 filing dates fit EDGAR's 17:30 cut-off, while the Eastern reading contradicts 343. Keep the acceptance_datetime helper and all its call sites, but parse the value as UTC and convert it to America/New_York. If a string carries an explicit offset, honour that offset instead of overwriting it.

2. Tests. Restore the same-day cutoff test to the UTC reading, so in summer 19:59:59Z (15:59:59 Eastern) is available and 20:00:00Z is not. Revert the test_review_four timestamp changes that round 10 made for the Eastern reading. Replace the Apple test with Savara's own 10-Q row (filingDate 2026-08-11, acceptanceDateTime 2026-08-11T20:05:48.000Z), which is 16:05:48 Eastern, after that day's close but before the 17:30 cut-off.

3. Regression test over the saved Savara submissions fixture. Every row must have a filing date consistent with the UTC reading, with these exceptions. Skip Forms 3, 4 and 5 and their amendments, correspondence, Schedules 13D and 13G, and forms posted by the SEC or an exchange rather than the filer, such as EFFECT and CERTNAS, whose filing date is the effective or certification date. Accept either date for acceptances between 17:30 and 17:35 Eastern, because the cut-off applies to when transmission starts. If any other rows still disagree, list them in docs/build/round-11-notes.md and have the test assert exactly that list rather than exempting them silently.

Keep every existing test passing apart from the ones this task changes, and run python3 -m unittest discover before you finish.
