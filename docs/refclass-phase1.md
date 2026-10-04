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

Supply the company's USD-denominated unadjusted pre-news close and contemporaneous common `shares`, `shares_as_of` and `shares_source` for market value. The normalizer must establish that these shares come from the latest filing before the event, that the applicant belongs to the sponsor or a partner with disclosed economics, and that the listing was eligible. The engine cannot establish those facts from unsourced flags. Missing share evidence prevents entry into class C. Returns use split-adjusted prices while market value uses unadjusted prices to match the share count.

Each tag observation contains `feature`, `value`, `tagger`, and `locator`. For nonfixture imports, `first_product` and `same_day_news` require matching `yes`/`no` observations from at least two distinct taggers. The importer recomputes agreement rather than trusting an `agreed` flag. Missing or disputed first-product tags prevent entry into B and C. Only explicitly agreed no-news observations enter the sample without same-day takeover/financing. This is an import boundary for independent extractions; it does not run the two taggers or provide the phase 2 review workflow.

Optional `offering_dates` must be announcement dates, not pricing or completion dates. `offering_coverage_through` establishes the extent of the source search. Five trading days means day one through the fifth session inclusive. No offering is reported only when all five sessions and source coverage exist; otherwise the result is unknown.

Outputs show A, B and C, with each event type separate, priced and unpriced counts, medians and linearly interpolated quartiles, plus results without same-day news. Samples below ten events are marked thin. Counts of missing first-product status and market value explain omissions from narrower classes. Event windows list the input prices and sources. Rates, likelihood ratios, backtests, ledgers and Excel models are not phase 1 outputs. A phase 2 backtest remains a prerequisite for live use.

Quality gates and compatibility

`out/quality.json` (or the corresponding finder output directory) supplies the seven evidence sections below. Run locks are enforced separately by the operating system. A present file is always enforced before the model call or publication. Invalid evidence stops the step and leaves an existing output untouched. `QUALITY_GATES=strict` also refuses missing evidence. Default `legacy` mode keeps existing command inputs working and prints that absent evidence is unverified. This compatibility path is not a completed mandatory quality-gate rollout.

| Section | Inputs |
|---|---|
| `units` | `nav`, `nav_unit`, `price`, `price_unit` |
| `staleness` | `cash_as_of`, `shares_as_of`, `latest_10q_period` |
| `listing` | `ticker`, `as_of`, `checked_through`, `filings` with `date` and `items` |
| `attribution` | `company`, `applicant`, optional `economics_source` object with `source` and `locator` |
| `date_type` | `kind`, either `fda_action` or `fda_goal` |
| `arithmetic` | List of `kind`, `inputs`, `reported` computations |
| `partial_tender` | `price`, `tender_price`, `entitlement`, `residual_price`, `headline_return` |

Every section must be present. An inapplicable section is `{"not_applicable": "specific reason"}`. Arithmetic kinds are `runway`, `return`, `abnormal_return`, `annualized_return`, `expected_value`, `whole_holding` and `discount`. Return numbers are fractions. Annualized returns use simple return times 365 divided by the positive calendar-day count. Runway requires cash plus both short-term and long-term securities and positive monthly burn. The Python currency API takes explicit currency-pair FX rates; no rates are guessed. JSON evidence can supply FX as a list of `from`, `to`, `rate` records.

The kit holds one inherited kernel lock across a writing job and its child steps, serializing independent writing jobs because finder state and knowledge are shared. Read-only help, version, doctor and refclass reports can still run. A stale lock file does not block a new process. Lock files are never unlinked, avoiding races between waiters. Existing model logs retain their locations; snapshot imports do not launch a long job or a background process.

Remaining prerequisites are saved primary source datasets, historical split-adjusted IBKR/XBI bars, a complete exchange-session calendar and structured source evidence from the legacy extractors. Neither `exchange_calendars` nor `pandas_market_calendars` is installed. No library was installed; the importer requires supplied sessions instead of guessing holidays. The four Savara raw-price fixtures and synthetic XBI benchmark verify the calculation and import path, not the accuracy or completeness of a live data feed.
