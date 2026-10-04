# Round 5 build handoff

Implemented the review-4 regressions and the offline workflow for amendments 7 through 12. Phase 1 is not yet accepted. Acceptance depends on Ebrahim's live build and documents absent from this checkout.

Read docs/spec-amendments.md before docs/system-spec.md. Preserved the supplied amendments and nonempty review-4.md. Used standard-library Python and existing kit command wrappers. No libraries were installed. No IBKR, EDGAR or model requests were made. Network use was limited to three bounded openFDA sample requests.

## Verification

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -v` | 96 tests passed |
| `bash -n run.sh` | Passed |
| `git diff --check` | Passed |

Stopped implementation after the full offline suite passed. Existing pre-phase-one numeric and renderer baseline comparisons still pass. Tests that previously accepted prose dates now reject them under amendment 8. Artificial test data remains explicitly distinguished from live acceptance evidence.

## Review-4 new findings

| Finding | Change |
| --- | --- |
| N1, profile substring checks | Exact numeric tokens support scientific notation. Market value evidence requires explicit USD and a matching ISO as-of date. First-product wording must establish an approved or commercial product or the absence of approved/commercial products. The cited source is re-read. Merely saying “our first product candidate” fails. This deliberately conservative parser can reject valid alternative wording. |
| N2, prose date parsing | Removed sentence-level acceptance rules. FDA dates use JSON pointers to original approval action or CRL letter fields. SEC timing uses the company's structured 8-K acceptance timestamp. Prose is reviewed for contradictions, never accepted as date evidence. |
| N3, large bar files | Replaced repeated list membership scans with a set. Added per-operation primary-file caches so validating each bar does not repeatedly read the whole file. The cache is discarded between operations so later publication re-reads sources. |
| N4, collector source paths | The source boundary now permits the repository's data/refclass/raw directory as well as deal filings/work. Resolved paths reject symlink escapes. Live FDA/SEC collection uses source/download-date directories. |
| N5, bounded FDA query samples | Downloaded actual bounded Drugs@FDA and CRL responses. Saved exact request URLs, UTC download dates, bodies and hashes under raw and tests/fixtures/collectors. Removed the test URL-substitution shim. The offline CLI now replays the actual bounded query successfully. |
| N6, partial tender warning | The warning compares returns including target dividends on the same cost basis. whole_holding runs through warn_check, so invalid residual prices warn instead of crashing the calculator. Legacy output calculations remain unchanged. |
| N7, catalyst currency inputs | The catalyst research schema now requests anchor_unit, price_unit and fx explicitly, so the existing conversion warning can receive the necessary fields. It still depends on the supplied research data being correct. |
| N8, partition metadata | Coverage stores partition lists. Assembly and incremental updates retain earlier partitions instead of overwriting the source's previous scope. |
| N9, excluded events | Publication rechecks exclusions, requires independently reconciled review metadata, and re-hashes their primary documents. Changes to reviewed evidence block publication, including evidence for excluded events. Included events also require review metadata. |
| N10, housekeeping | Corrected codex-4.md's obsolete commit statement. Preserved the supplied nonempty review-4.md. Removed build-review summaries from research-standards.md and identified its actual instruction/specification sources. Earlier investor feedback is unavailable. No commit or staging was performed; new files, including review-4.md, remain working-tree additions. |

## Amendments and commands

Amendment 7 approves the existing openFDA Drugs@FDA API collector. Its CBER coverage gap remains visible. Published CRLs also remain an incomplete view of unpublished letters.

Amendment 8 is implemented with structured FDA action evidence and EDGAR acceptance evidence. The collector emits their pointers. The timing convention is now knowledge/refclass-rules.md version 2, so older databases must be rebuilt. Upgrades preserve locally modified knowledge files under the existing seed-only policy; the live installation must adopt the new timing rules before rebuilding.

Amendment 9 moves live collector downloads to data/refclass/raw/<source>/<download-date>/. An offline cache override remains available for replay. Model review artifacts are not primary sources and should remain outside raw. Gates only re-read primary paths.

Amendment 10 adds the following entry point.

```sh
./run.sh refclass fetch-bars --tickers VRNA KALV CRNX LQDA --since YYYY-MM-DD --until YYYY-MM-DD
```

It reuses the kit's Claude IBKR connection and run lock. It captures the streamed tool transcript under data/refclass/raw/ibkr/<download-date>/ and extracts historical tool results in code. Assistant-generated text cannot become bars. XBI is added automatically. The adapter retains the original broker payload and transcript locator. Publication checks normalized values against those saved inputs. Existing raw bar files are not silently replaced.

The currently supported tool payload is an object containing `bars`, with ticker, date, close, adjusted_close and adjustment supplied in the bar or enclosing object. Adjustment must explicitly be split_only. An unsupported schema or missing price convention stops rather than inventing adjustment factors. This mapping has been tested with an explicitly artificial saved transcript, not a real historical broker response. Ebrahim must verify it against the configured IBKR server and may need a mapping adjustment. No real historical broker sample was available, and fetching one was forbidden for this build.

Saved canonical historical JSONL can be replayed without connecting.

```sh
./run.sh refclass fetch-bars --tickers TEST --since YYYY-MM-DD --until YYYY-MM-DD --saved PATH
```

Amendment 11 adds code assembly, independent model review prompts and CSV reconciliation.

```sh
./run.sh refclass prepare-review --collection COLLECTION.json --output REVIEW_DIRECTORY
./run.sh refclass review-models REVIEW_DIRECTORY RESULT_DIRECTORY
```

Repeat --collection for source partitions. prepare-review writes candidates.json and separate Claude/Codex prompts. review-models calls the existing model wrappers sequentially with independent prompts, then reconciles the CSVs. It was not run against live models here.

Saved reviews can also be reconciled offline.

```sh
./run.sh refclass review --prepared REVIEW_DIRECTORY/candidates.json --reviews CLAUDE.csv CODEX.csv --output RESULT_DIRECTORY
```

Each review covers every candidate. CSV fields are candidate_id, decision, event_json and reason. Decisions are include, exclude or unresolved. Reviews cannot change code-derived candidate identifiers, applications or FDA action dates. They supply the company filing link and sourced eligibility evidence. Contradictory press releases must be marked press_release_conflict and remain unresolved. Agreement produces events.csv and reviewed.json. Disagreement produces disagreements.csv for Ebrahim and a nonzero status. Nothing is sent to another person automatically. Human resolutions require corrected independent reviews and reconciliation; no separate interactive resolution command was added.

Production builds require complete event evidence, sessions and bars as before. reviewed.json is an event-review input, not a replacement for those other snapshot inputs. Merge the required snapshot fields before build. Reconcile and build use the same tag normalization, and publication checks the sealed event payload and primary-source hashes.

Amendment 12 adds a live acceptance command and a validated profile writer.

```sh
./run.sh refclass profile savara --input SOURCED_PROFILE.json
./run.sh refclass show savara
./run.sh refclass acceptance --db data/refclass.sqlite --targets PRIMARY_TARGETS.json
```

The profile input needs the existing source, locator, line_start, line_end and as_of fields, plus first_product and market_value with its separately cited USD/date evidence. It writes deals/savara/refclass.json only after the cited deal documents pass validation. No Savara facts were invented and no Savara profile was created here.

Acceptance requires a sourced Savara profile, strict publication, no pending candidates, complete collection partitions and continuous unfiltered FDA date windows from 2015 through the build date. It prints the census and nested classes and compares all three stock closes and their session dates for VRNA, KALV, CRNX and LQDA to the cent. Targets are a primary-path JSON array with ticker, action_date, pre_date, day1_date, day2_date, pre_close, day1_close and day2_close. The existing report-derived comparable fixture remains an offline arithmetic test and is not a production bar source.

The acceptance command does not independently discover omitted sponsors or authenticate manually forged source files. A completed bounded collection is not proof that the entire historical sponsor universe was supplied. Ebrahim must review census scope, known coverage gaps and target provenance during the live build.

## Still open

- Run and validate the actual IBKR historical response mapping, including split adjustments, real XBI and acquired/delisted symbols. Current offline transport tests do not establish compatibility with the configured server's response schema.
- Collect the historical census and review the company universe, partition coverage and missing CBER/unpublished-CRL data. The downloaded samples are small parser fixtures, not the census.
- Run the two independent event reviews on collected primary documents and resolve disagreements. No model reviews were executed in this build.
- Supply the Savara deal documents and sourced profile inputs. The checkout still lacks the documents needed for an honest working show savara acceptance demonstration.
- Reproduce the four comparables from genuine bars using structured SEC timing and a checked session calendar. If those timing conventions differ from the earlier report, investigate and report the mismatch rather than changing prices to force agreement.
- The older review-4 “still open” findings about missing legacy evidence and general prose arithmetic completeness remain phase-3/source-production work. This round does not claim that arbitrary prose has a complete evidence ledger.
- Full live acceptance, calendar provenance and independent census completeness remain unverified. The offline suite passing is not phase-one acceptance.
