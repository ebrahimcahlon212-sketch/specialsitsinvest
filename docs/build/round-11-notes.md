# Round 11

`acceptance_datetime` now interprets `Z` and offset-free values as UTC, honours explicit offsets, and converts the instant to `America/New_York`. All existing helper call sites remain. The other round 10 changes remain in place.

The regression reads the saved Savara submissions response through the offline fixture client, using its manifest checksum validation. The fixture is `tests/fixtures/collectors/2d26b5c3fd1649a4-869ba9fcac4a.response`, under `/filings/recent`.

| Check | Result |
| --- | --- |
| Saved rows | 1,000 |
| Excluded rows | 482 |
| Checked rows | 518 |
| Remaining disagreements | 0 |

The excluded base forms are `3`, `4`, `5`, `CORRESP`, `UPLOAD`, `SC 13D`, `SC 13G`, `SCHEDULE 13D`, `SCHEDULE 13G`, `EFFECT`, `CERTNAS` and `CT ORDER`. Amendments use the same exclusions. `CT ORDER` is an SEC order. Form `25` remains checked, rather than treating every delisting notification as exchange-posted.

The check compares Eastern acceptance dates to filing dates. Before 17:30, it requires the same date. From 17:30 through 17:35 inclusive, it accepts either the same date or the next filing business day. Later acceptances require the next filing business day. Weekends are skipped.

Two federal closures are explicitly included in the fixture check. This is a fixture-specific filing calendar, not a general holiday calendar or an exchange calendar. These rows are checked, not exempted.

| Accession | Form | Eastern acceptance | Closure | Required and actual filing date |
| --- | --- | --- | --- | --- |
| 0001193125-13-236099 | S-1 | 2013-05-24 20:27:18 | 2013-05-27, Memorial Day | 2013-05-28 |
| 0000950123-09-049647 | 8-K | 2009-10-09 19:41:15 | 2009-10-12, Columbus Day | 2009-10-13 |

One checked row falls in the transmission tolerance window.

| Accession | Form | Eastern acceptance | Actual filing date |
| --- | --- | --- | --- |
| 0001193125-16-455520 | 424B5 | 2016-02-09 17:30:07 | 2016-02-09 |

The exact residual disagreement list is `[]`. The regression asserts that empty list, so any new discrepancy fails rather than being silently exempted.

The replacement Savara example reads accession `0001193125-26-344585` from the fixture. Its `2026-08-11T20:05:48.000Z` acceptance converts to `2026-08-11T16:05:48-04:00`, after the market close and before the filing cutoff. Tests also cover winter conversion, explicit offsets, UTC date rollover, offset-free UTC input, and the exact summer close boundary.
