# Phase 1 event prices

Read [the amendments](spec-amendments.md) with [the system specification](system-spec.md). The [manual](manual.md) describes collection, `fetch-bars`, independent review, human resolution, profiles and acceptance. The implementation has offline tests, but phase 1 still needs Ebrahim's live acceptance run.

FDA approval and CRL collectors use openFDA. EDGAR collection saves submissions inventories, 8-Ks and bounded exhibits. Real saved response fixtures test these collectors. No full historical census is supplied. Missing CBER and unpublished-CRL coverage remain explicit gaps.

Massive daily aggregates supply paired as-traded and split-adjusted closes, with genuine small saved responses for offline tests. Free-tier history is limited to two years by default. Earlier requested windows remain counted gaps. Ebrahim can run the full census after upgrading, using `collect massive --history-years 20`, with an explicit `--calls-per-minute` matching the purchased plan. Exact successful requests resume across saved download dates; `--refresh` bypasses reuse. Historical symbols are requested directly without filtering against a current-listed ticker universe.

IBKR `fetch-bars` saves original transcripts and retains plain OHLCV for independent comparison only. Events in the last five years compare broker closes against both Massive conventions. Differences above one cent from both appear in `refclass review`; missing comparisons remain counted. JSON keeps each difference and the matching convention. The production census requires Massive bars; broker observations cannot replace them. No live broker data was fetched during this build.

```sh
python3 -m unittest discover -v
./run.sh refclass build --input /path/to/snapshot.json
./run.sh refclass update --input /path/to/increment.json
./run.sh refclass show savara
./run.sh refclass show savara --json
./run.sh refclass review
./run.sh refclass gates /path/to/quality.json
```

`--db FILE` overrides `data/refclass.sqlite` for database commands. `REFCLASS_DB` also sets the default. The default snapshot is `data/refclass-input.json`. Missing sources return a nonzero status and never erase an existing database. Builds with source gaps record and print them. No fixture is loaded into production automatically.

`build` replaces the dataset in one transaction. `update` merges by event ID and ticker/date, preserving acquired, delisted and unpriced events. Rebuild to clear resolved historical gaps. Rules and feature versions and SHA-256 fingerprints are recorded. Changed convention files require a rebuild.

## Snapshot format

| Field | Contents |
|---|---|
| `as_of` | ISO build date |
| `fixture` | True only for test data, propagated by updates |
| `coverage` | Partition lists with `path`, `complete`, `scope`, for FDA, CRL, EDGAR and Massive, plus optional IBKR check partitions |
| `gaps` | Failed downloads, parse failures and coverage limitations |
| `candidates` | Code-assembled candidates, retained even when not reviewed |
| `events` | Independently reviewed inclusions and exclusions |
| `prices` | Ticker, session date, unadjusted `close`, split-only `adjusted_close`, primary `source#Lnumber` |
| `ibkr_checks` | Separate native broker closes with primary line provenance |
| `sessions` | Every exchange session in priced windows, with date and Eastern open/close, including early closes |

Included events need company, ticker, drug, application, original-application status, historical listing, structured action and announcement evidence, source locators and review metadata. Source line evidence uses `source`, `line_start` and `line_end` for physical one-based text lines. A range must contain fewer than fifty lines. JSON pointers identify structured FDA dates and SEC 8-K acceptance timestamps. Prose can flag a contradiction, not establish those dates.

Reviewed exclusions require identity, company, primary evidence and a sealed review. They do not require a ticker or an announcement timestamp. Both inclusions and exclusions are rechecked against primary-file hashes before publication.

Independent tag values are compared by feature, without requiring equal line ranges or tag order. Drug-name case, spacing and punctuation do not create disagreements. Different substantive assertions remain pending. Ebrahim's explicit resolution keeps both model readings, its reason and the selected tags. It cannot change structured candidate identities or FDA dates. The manual gives the resolution CSV command.

Session selection is independent of bar availability. Date-only announcement inputs are flagged and assume after-close timing in the calculation engine, but strict publication still requires the structured SEC evidence required by amendment 8. A missing bar cannot move the event window.

Market value uses an unadjusted pre-news close and contemporaneous common shares. `share_filings` must identify saved filing evidence, filing date, as-of date and share count. Saved SEC inventories support the check for the latest filing before the event. Applicant, listing and any partner-economics evidence must be supplied. A missing market value prevents entry into class C.

Returns use split-adjusted stock and XBI closes on the same sessions. Reactions retain unadjusted closes separately. Acceptance compares these as-traded prices to the report's prices, then checks the report's day-one and day-two split-adjusted returns. No assumption is made that a later split leaves as-traded prices equal to adjusted prices.

Optional offering dates are announcement dates. The five-session window starts at day one. No offering is reported only when all five sessions and source coverage are supplied, otherwise the result is unknown.

Outputs show nested classes A, B and C with priced, unpriced and unknown-feature counts, medians and interpolated quartiles. Approvals and CRLs remain separate. Results also exclude same-day takeover/financing in a sensitivity view. Rates, likelihood ratios, backtests and workbooks belong to later phases.

## Publication checks

Research steps never receive evidence instructions and never run gates. Existing publication commands warn without blocking, including when evidence is absent. The old `QUALITY_GATES` environment variable cannot make legacy commands strict. New publication paths fail closed.

Strict reference-class publication recomputes the actual reactions and class summaries, rereads primary bars and event evidence, and checks review seals. It accepts primary files only from deal `filings/` or `work/`, or `data/refclass/raw/`, with symlink escape checks. Keep model outputs outside raw.

General structured quality evidence requires units, staleness, listing, attribution, date type, arithmetic and partial-tender sections. Explicit N/A reasons are allowed except for arithmetic. The supported computations are runway, return, abnormal return, annualized return, expected value, whole-holding return and discount. Runway includes both short- and long-term securities. Annualization uses simple return times 365 divided by the calendar-day count.

The standalone strict prose checker, still unwired to real commands pending phase 3 (review-6 problem B), scans the actual output for every numeric token. `numeric_claims` binds each token by zero-based character offsets to primary line evidence or a checked arithmetic entry. Calculation inputs need primary evidence keyed by their input paths. Extra claims, missing bindings, mismatches and unsupported inputs stop publication before replacing an existing report. This establishes numeric coverage, not the semantic correctness of a source interpretation or the completeness of a search. Legacy extraction only warns; research extraction remains exempt.

FX rates and source units must be explicit. Catalyst research keeps the anchor in its original source unit. Legacy rendered numbers retain their compatibility contract and warn when the converted comparison differs.

## Execution and remaining acceptance

Build, update and collect normally launch jobs with logs under `~/special-sits-kit-logs/`. Add `--foreground` for synchronous execution. A lock prevents a second copy of the same job. Shared legacy stores do not gain transaction safety from separate job locks.

Acceptance requires reviewed census candidates, continuous unfiltered FDA collection windows, EDGAR coverage, genuine prices for the four comparables, a sourced Savara profile and the required published-number traces. Massive history and price gaps elsewhere remain counted unpriced, as the specification requires. The test does not independently discover omitted sponsors or authenticate forged local files.

This checkout lacks the live bars, complete census, Savara source documents and verified report targets needed for acceptance. The paid Massive history, genuine IBKR schema and original comparable target transcription still require live verification. No phase 2 work is authorized by passing the offline suite.
