# Build 7

Implemented review-6 problems A, C, D, E and F and amendments 13 through 16. Problem B remains deferred to phase 3. Stopped implementation after the complete offline suite passed.

## Review fixes

| Problem | Change |
| --- | --- |
| A | The legacy IBKR allowlist now uses the real `get_price_snapshot`, `get_account_positions`, `get_account_balances`, `search_contracts` and `get_account_summary` tools. The bars session allows `search_contracts` and `get_price_history`. The read-only hook still rejects unknown tools and order endpoints. Tests exercise the actual hook with these names. |
| C | A first-commercial-product statement no longer establishes absence of previously marketed products. Profile market values must be explicitly labelled market capitalization or total equity market value at the pre-news close, with the matching date and USD amount. Non-affiliate float, enterprise value and unrelated dollar amounts are rejected. Unsupported evidence remains a gap. |
| D | Invalid model JSON, missing review evidence and unreadable primary files become disagreements for the affected candidate. Other candidates and valid human resolutions still finish. Human resolutions preserve both model readings, including invalid readings, while the selected evidence is verified and sealed. Invalid human resolutions still stop publication. Models cannot supply their own human-resolution metadata. |
| E | Bare `refclass review` prints current model decisions, reasons and substantive assertions, including differing tag values. A local registry tracks the latest reconciliation per candidate. Resolving into a different output directory supersedes the old listing without deleting the old CSVs. Reconcile older saved runs once to register them. |
| F | A regression removes a comparable's day-one XBI bar and verifies that acceptance fails as unpriced even when the price partition completeness waiver applies. The waiver now concerns Massive partitions. |

## Massive pricing and IBKR comparisons

The new standard-library Massive collector requests daily aggregates twice, with `adjusted=false` and `adjusted=true`. It pairs sessions, saves both original responses and request metadata, and writes bars containing both closes and primary-response locators. Publication rereads the raw responses, their checksums, ticker, session and adjustment convention. Production census prices must come from Massive. Returns use split-adjusted closes; market values and the four-comparable close check use as-traded closes.

The collector requests historical ticker symbols directly, including delisted symbols supplied by the reviewed census. It does not filter against a current-listed ticker universe. XBI is included automatically. Overlapping collections deduplicate identical benchmark prices and reject conflicting values.

Free-tier history defaults to two years. Earlier requested dates produce explicit history gaps without removing candidates. Ebrahim can use `--history-years 20` after upgrading for the full 2015-onward collection. The option does not override provider entitlements. HTTP failures, empty results, unsupported response conventions and incomplete responses remain gaps. Collection windows are bounded by calendar year.

`MASSIVE_API_KEY` is read from `settings.env` without executing its contents. It is sent only in an authorization header, never in request URLs. A shared persisted limiter spaces requests at least 12.1 seconds apart. Error bodies are not saved because they can echo credentials. Tests cover rate-limit persistence, header-only authentication and sanitized failures. A scan found no actual key in tracked or non-ignored new files. `settings.env` remains ignored.

`fetch-bars` retains recognized plain IBKR OHLCV as separate `ibkr_checks`, using the original transcript and contract resolution. It does not invent adjusted prices. Build/show compare native broker closes with Massive as-traded closes for stock and XBI over the pre-news, day-one and day-two sessions of events within five years. Differences strictly above $0.01 are flagged for review; exactly $0.01 passes. Missing observations are reported explicitly. Broker observations cannot overwrite census prices.

Rules are now version 3. Existing databases require a rebuild because their source convention changed. The manual, phase-one guide and example settings describe the new workflow.

## Validation

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -v` | All 124 tests passed in 2.583 seconds. |
| `bash -n run.sh` | Passed. |
| Network use | Four small Massive daily-aggregate samples only, KALV and XBI for 2025-07-01 through 2025-07-10, each with both adjustment settings. |
| Saved real fixtures | `tests/fixtures/massive/2026-10-04/`, with exact download timestamps, keyless URLs and SHA-256 checksums in `manifest.json`. |
| IBKR access | No live requests. Broker tests use saved or explicitly synthetic samples and recording stubs. |
| Dependencies | No installations. New collector uses the Python standard library. |

New regressions cover source tampering, adjustment mismatches, synthetic split returns, free-tier gaps, upgraded-window requests, credential handling, rate limits, broker comparison thresholds, malformed reviews, stale disagreement listings, profile errors, overlapping benchmarks and missing XBI acceptance failure. Existing legacy behavior tests remain in the suite. Refclass fixtures that depended on the superseded IBKR census or permissive profile wording were updated to the amended requirements.

## Still open

- Review-6 problem B belongs to phase 3. Strict numeric prose validation remains a standalone checker, not a mode invoked by a real command. Its formatting limitations were not changed.
- Live phase-one acceptance remains Ebrahim's task. This build did not run the full census, reproduce all four comparables from Massive, validate the report-target transcription, or publish a sourced Savara profile and `show savara` result.
- Ebrahim must upgrade for older Massive history and run the full collection. The small free-tier samples do not establish historical or delisted-symbol coverage for the entire census.
- The actual IBKR response schema, contract mapping, Claude tool permissions and independent comparisons still need live verification. Unsupported broker shapes remain gaps. Differences require review; the code does not automatically reconcile provider conventions.
- Savara profile evidence must establish full-company market capitalization at the pre-news close and first-product status. The conservative profile parser rejects unsupported wording rather than substituting a 10-K free-float amount.
- Complete exchange sessions, source inventories, FDA/EDGAR census coverage, missing CBER coverage and unpublished CRLs remain the existing acceptance and coverage work. Passing the offline suite does not certify those inputs.

The existing user changes in `docs/spec-amendments.md` and `docs/build/review-6.md` were preserved.
