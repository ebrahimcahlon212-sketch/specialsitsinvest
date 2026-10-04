# Offline fixtures

The company closing prices and dates in `savara-comparables.csv` are copied from the final Savara biotech report, `deals/savara/out/biotech.md`, lines 129–132. The percent columns are independently calculated expected results, rounded only for display. No network access is needed and the deal folder is not needed to run tests.

The report does not establish precise announcement times, adjusted closes, share counts, listing histories or XBI prices. The tests use synthetic 08:00 Eastern timestamps for KalVista and Liquidia to exercise the pre-market convention. Verona and Crinetics use unknown times and the required after-close assumption. Tests treat these closes as split-adjusted only for the synthetic calculation exercise. Synthetic sessions, shares, eligibility tags and XBI prices must never be loaded as verified historical research. XBI is 100, 102 and 101 on the three corresponding dates. Sessions include the July and May holiday gaps in the report.

The report's blended Savara estimate is not a reference-class statistic. Its unrounded result is $5.579..., which rounds to $5.58 to the cent, rather than the report's discretionary $5.60. The engine does not adopt that blend or estimate.

These are arithmetic regression fixtures only. Passing them is not the system-spec acceptance test. That acceptance test remains open until independently acquired IBKR stock and XBI bars and primary announcement timestamps are available. Production imports reject price sources explicitly labelled synthetic or fixture unless the entire snapshot is labelled as a fixture.

`ibkr-tool-sample.jsonl` is an explicitly artificial saved transport sample for the historical adapter. It is not a downloaded broker response or phase-one acceptance evidence. No live IBKR data was fetched in this build.
