# Reference class rules, version 1

Fixed on 4 October 2026, before any results were seen. Any change creates version 2, and every output records the version it used.

## Events
An event is an FDA approval, complete response letter, refusal to file, review extension or accepted resubmission for an NDA or original BLA. Supplements and abbreviated applications, such as generics and biosimilars, are excluded. The window runs from 1 January 2015 to the build date. The sponsor, or a partner with disclosed US economics, must be listed on a US exchange at the event date.

## Nested classes, broad to narrow
- A. Every event that meets the event rules.
- B. Class A, limited to the company's first US product, meaning it had no other product on the US market at the event date.
- C. Class B, limited to a market value under $3 billion at the pre-news close. This is the core class.
- D. Class C, limited to products with orphan designation for the indication before the event. Phase 2.
- E. Class D, limited to products that also held breakthrough designation before the event. Phase 2.

Approvals and rejections are always reported separately, with the count at every level.

## Prices and timing
- Times are US Eastern, and the announcement time comes from the earliest press release or filing.
- The pre-news close is the last regular-session close before the announcement.
- A pre-market announcement makes that day's session day one. An announcement during market hours or after the close makes the next session day one. Day two is the session after day one.
- Returns use split-adjusted closes, and the abnormal return is the stock's return from the pre-news close minus XBI's return over the same window.
- Market value is the pre-news close multiplied by common shares outstanding from the latest filing before the event.

## Handling
- Events with no price data stay in the table, marked unpriced, and are counted.
- Events with a takeover or financing announced the same day are flagged, and results are shown with and without them.
- An event whose announcement time is unknown is flagged, and day one assumes an after-close announcement.
- Summaries use medians and interquartile ranges, and a class with fewer than 10 events is marked thin.

## Testing
Offline tests use the closing prices for Verona, KalVista, Crinetics and Liquidia in deals/savara/out/biotech.md as fixtures for raw returns. Abnormal-return tests use synthetic XBI fixtures labelled as synthetic.
