# Spec amendments, version 1, 4 October 2026

These override docs/system-spec.md where they differ.

1. Quality gates are strict only for refclass outputs and new commands. Existing commands run the gates in warn-only mode, printing any failure without stopping, until phase 3 adds the steps that produce evidence.
2. Research steps, including drafts, reviews, checks, ask and explain, never receive the evidence instructions and are never stopped by a gate.
3. A gate may only re-read sources inside the deal's filings or work folders, never model output.
4. Collectors for the FDA sources and for EDGAR are built and tested against small saved samples of real responses, stored under tests/fixtures with their download dates. Ebrahim runs the live build himself.
5. The IBKR collector reuses the kit's existing price code and is verified during that live build.
6. Every existing command must behave exactly as it did before phase 1, with tests that show it.

## Version 2, 4 October 2026

7. The openFDA API is approved in place of the Drugs@FDA bulk files, with the missing CBER coverage reported as a gap.
8. Event dates come from structured fields, meaning the FDA action or letter date and the EDGAR acceptance time of the company's 8-K. Prose is used only to flag a press release that contradicts them, never to accept a date.
9. Raw downloads live in data/refclass/raw/, by source and download date, and strict publication may re-read files there as well as in deal folders.
10. A new command, ./run.sh refclass fetch-bars, uses the kit's existing IBKR connection to save daily bars for given tickers and dates into data/refclass/raw/ibkr/. Ebrahim runs it live, and the build agent tests it only with saved samples.
11. Code assembles the event list from the collected candidates, and two models review it into a CSV with disagreements sent to Ebrahim, instead of sentence-level rules.
12. Phase 1 is accepted when the live build reproduces the four comparables from IBKR bars to the cent, reports the census counts, prints the nested classes for a Savara profile built from the Savara deal documents, and traces every published number to a file in data/refclass/raw/ or a deal folder.

## Version 3, 4 October 2026

13. Historical prices for the census come from Massive's daily aggregates, which keep delisted tickers. Each event stores the as-traded close, requested with adjusted=false, and the split-adjusted close, requested with adjusted=true. Returns use split-adjusted closes and the comparables check uses as-traded closes. Amendment 12's acceptance uses Massive bars.
14. The build is developed and tested on Massive's free tier, which holds two years of history. Ebrahim runs the full census after upgrading for one month, and events beyond the plan's history are reported as a gap rather than dropped silently.
15. For events within the last five years, IBKR closes from fetch-bars provide an independent check, and any difference above one cent is flagged for review.
16. The API key is read from settings.env as MASSIVE_API_KEY. It never appears in logs or committed files, and requests stay within the plan's rate limit, which is five calls a minute on the free tier.

## Version 4, 5 October 2026

17. An IBKR close is flagged for review only when it differs by more than one cent from both the Massive as-traded close and the Massive split-adjusted close. Both differences are recorded. This replaces the one-cent wording in amendment 15.
