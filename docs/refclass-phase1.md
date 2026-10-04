# Phase 1 event prices

This implementation imports sourced local JSON snapshots and computes event windows, raw returns and XBI abnormal returns in SQLite. It does not yet collect a historical census from FDA, openFDA, EDGAR or IBKR. Nothing calls an order endpoint. All tests run offline with Python's standard library.

```
python3 -m unittest discover -v
./run.sh refclass build --input /path/to/snapshot.json
./run.sh refclass update --input /path/to/increment.json
./run.sh refclass show savara
./run.sh refclass show savara --json
./run.sh refclass gates /path/to/quality.json
```

`--db FILE` overrides `data/refclass.sqlite` for every database command. `REFCLASS_DB` also sets the default. The default input is `data/refclass-input.json`. Missing source files produce a nonzero status and, if no database exists, an empty database with counted source gaps. They never erase an existing database. Builds with source gaps also return nonzero, after recording and printing those gaps. No fixture is loaded into the production database automatically.

`build` replaces the imported dataset in one transaction. `update` merges by event ID and by ticker/date, preserving events with no prices, including acquired and delisted companies. Use a full rebuild to clear previously recorded gaps after resolving them. Rules and feature files carry their own versions and SHA-256 fingerprints. Changed files require a rebuild; a new version number requires updating the implementation and tests first.

Snapshot format

| Field | Required contents |
|---|---|
| `as_of` | ISO build date |
| `fixture` | `true` only for test data; permanently propagated by incremental updates |
| `coverage` | Descriptions of coverage for `drugs_at_fda`, `openfda_crl`, `edgar`, `ibkr`; this records supplied coverage, not independently verified completeness |
| `gaps` | Explicit list of failed downloads, parse failures or incomplete coverage |
| `events` | Event objects described below |
| `prices` | `ticker`, `date`, unadjusted `close`, split-adjusted `adjusted_close`, `source` |
| `sessions` | Every exchange session in each priced window, with ISO `date` and Eastern `open`/`close` times; include early closes, omit actual holidays |

An event has `event_id`, `company`, `ticker`, `drug`, `application` (`NDA` or `BLA`), boolean `original`, boolean `listed_us` at the event, `event_type`, `announced_at`, optional `goal_date`, `source` and `locator`. Use a timezone-aware ISO announcement timestamp, or just the date when its time is unknown. Date-only announcements are flagged and assume after-close timing. Session selection is independent of available company bars. A missing bar stays missing and does not shift the window.

Supply the company's USD-denominated unadjusted pre-news close and contemporaneous common `shares`, `shares_as_of` and `shares_source` for market value. Production imports require the source evidence described below. Supplied coverage still needs independent review. Missing share evidence prevents entry into class C. Returns use split-adjusted prices while market value uses unadjusted prices to match the share count.

Each tag observation contains `feature`, `value`, `tagger`, and `locator`. For nonfixture imports, `first_product` and `same_day_news` require matching `yes`/`no` observations from at least two distinct taggers. The importer recomputes agreement rather than trusting an `agreed` flag. Missing or disputed first-product tags prevent entry into B and C. Only explicitly agreed no-news observations enter the sample without same-day takeover/financing. This is an import boundary for independent extractions; it does not run the two taggers or provide the phase 2 review workflow.

Optional `offering_dates` must be announcement dates, not pricing or completion dates. `offering_coverage_through` establishes the extent of the source search. Five trading days means day one through the fifth session inclusive. No offering is reported only when all five sessions and source coverage exist; otherwise the result is unknown.

Outputs show A, B and C, with each event type separate, priced and unpriced counts, medians and linearly interpolated quartiles, plus results without same-day news. Samples below ten events are marked thin. Counts of missing first-product status and market value explain omissions from narrower classes. Event windows list the input prices and sources. Rates, likelihood ratios, backtests, ledgers and Excel models are not phase 1 outputs. A phase 2 backtest remains a prerequisite for live use.

Quality gates and publication

Publication requires evidence by default. `QUALITY_GATES=legacy` is an explicit compatibility opt-out, emits an unverified warning when evidence is absent, and is not suitable for a verified output. A supplied invalid evidence file always blocks publication.

Research steps such as mapping, drafts, review and terms extraction can run without pre-existing evidence. `run_step` asks the model to return evidence between `<<<BEGIN QUALITY>>>` and `<<<END QUALITY>>>`, outside its OUTPUT block. Python validates this JSON before saving it beside the artifact as `ARTIFACT.quality.json`. Published prose is checked before replacement. The calculator reads the terms artifact's evidence sidecar, with `out/quality.json` retained as a compatibility input. Other renderers still require their directory's `quality.json`; generating evidence automatically for all those legacy data paths remains open.

| Section | Inputs |
|---|---|
| `units` | `nav`, `nav_unit`, `price`, `price_unit` |
| `staleness` | `cash_as_of`, `shares_as_of`, `latest_10q_period` |
| `listing` | `ticker`, `as_of`, `checked_through`, `filings` with `date` and `items`, optional `venue` and `suffix_review` |
| `attribution` | `company`, `applicant`, optional `economics_source` object with `source` and `locator` |
| `date_type` | `kind`, ISO `value`, and saved primary-source `evidence` |
| `arithmetic` | List of `kind`, `inputs`, `reported` computations |
| `partial_tender` | `price`, `tender_price`, `entitlement`, `residual_price`, `headline_return` |

Every section must be present. An inapplicable section is `{"not_applicable": "specific reason"}`. Code cannot establish that a model has included every metric or correctly declared a section inapplicable. Source completeness and prose-to-evidence reconciliation remain review responsibilities.

Source evidence contains `source` (a local text path), `line_start` and `line_end` (physical, one-based lines). The gate rereads fewer than fifty lines. These are file line offsets, not necessarily the line tags used in research citations. The date gate checks the sentence containing the specified ISO date or English month-name date for FDA action or goal wording. Ambiguous, inferred or unsupported dates fail. This deliberately conservative text check can reject valid disclosures with different phrasing; it is not a general document interpreter.

The listing suffix check applies to fifth-letter Q tickers on OTC venues, or with unknown venue. It does not flag NDAQ. A `suffix_review` requires source evidence and a reason. An Item 1.03 finding remains blocking even when a suffix review exists.

Arithmetic kinds are `runway`, `return`, `abnormal_return`, `annualized_return`, `expected_value`, `whole_holding` and `discount`. Returns are fractions. Percentage results tolerate half of the last displayed digit for percentages quoted to two decimal places, or 0.00005 in fractional units, plus floating-point slack. Currency values and runway retain 0.005 tolerance. Annualized returns use simple return times 365 divided by a positive calendar-day count. Runway includes cash and both short-term and long-term securities. FX inputs must be explicit.

A partial-tender expected headline requires `expected_entitlement`. Residual value comes from `expected_residual_price` or a single supplied `back_end_prices` scenario. Missing assumptions produce a warning and no expected headline. Participation rows remain scenarios, and are not silently promoted to expectations.

Job execution

Deal job locks use the deal and command identity. A duplicate of that job is refused; a different deal or command can proceed. Help, viewing, questions, knowledge and ledger commands are not blocked by the deal job lock. Database imports also hold a database-specific write lock. Shared legacy stores do not gain transaction safety merely because unrelated jobs can now proceed.

`./run.sh refclass build` and `update` launch detached jobs with logs under `~/special-sits-kit-logs/`. The launcher acquires a database-specific job lock before spawning and passes its file descriptor to the worker. The log records completion status. Launch success means the worker started, not that the import succeeded. For a synchronous import use `./run.sh refclass build --foreground --input FILE`, or `python3 -m refclass build --input FILE`. No live background process was started in the review-fix session; launcher regression tests mock process creation.

Deal profiles

`deals/NAME/refclass.json` supplies `first_product`, USD `market_value`, `source`, `locator` and ISO `as_of`. Reporting selects the deepest applicable fixed class for that profile and keeps the global nested classes visible for context. A missing profile is explicitly reported as a gap and no deal-specific class is selected. This profile remains a sourced analyst input, not an automatically verified ledger row.

Production provenance

Nonfixture events now need `listing_evidence`, `applicant` and `applicant_evidence`. The listing evidence includes its source line range, `venue`, `valid_from` and `valid_through`. The source must contain the ticker and exchange, and the supplied validity interval must cover the event. Applicant evidence must contain the applicant and drug. A different applicant requires `economics_evidence` naming the company, applicant and drug with economics wording. Missing or unreadable evidence excludes the event with a printed reason.

For class C, `share_filings` lists saved filing evidence with `source`, line range, ISO `filed_at`, ISO `as_of` and `shares`. The engine selects the latest supplied filing before the event, reconciles it to the event's share fields, and rereads the count from its outstanding-shares passage. Missing or inconsistent evidence leaves market value unknown. The filing inventory's completeness, listing validity interval and interpretation of partner economics still need human verification. Text matching does not prove a complete SEC search.

Known synthetic or fixture-labelled price sources cannot be imported with `fixture=false`. This prevents accidental reuse of the bundled fake XBI series, but a source label alone is not authentication of a price feed.

Remaining prerequisites

The FDA/openFDA/EDGAR collectors and historical census remain unimplemented. Real split-adjusted IBKR and XBI bar acquisition, primary announcement timestamps and complete exchange-session calendars are still needed. The Savara report fixtures test arithmetic only; they are not the independent, broker-sourced acceptance test required by the system spec. No production data or deal profiles were fabricated to make acceptance pass. Phase 1 remains unaccepted.
