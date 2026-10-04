# Codex round 4

The concrete regressions in review-3 have been addressed where the saved code and evidence permit. Phase 1 is still not accepted. Live collection, independent acceptance evidence and some evidence-completeness work remain open. This note does not claim every review item is closed.

The system specification and amendments were read before changes. The later request to fix the code and write this file takes precedence over the research-only instruction against editing files. No web requests, model calls or broker calls were made. The real detached-worker test used temporary offline inputs and was waited for and reaped before finishing.

## Review disposition

| Review item | Change and remaining work |
| --- | --- |
| 1. Phase 1 acceptance | Build and update now accept repeated `--collection` arguments, reconcile reviewed events by `candidate_id`, persist collected candidates separately and report pending reviews. Collections can create a candidate census without an existing input snapshot. Unreviewed candidates do not become eligible events. Added saved historical IBKR-bar ingestion using the existing quote reader, including mandatory XBI and explicit split-only adjustment. A live MCP historical-price adapter, the full census and independently reproduced comparables remain open. |
| 2. Legacy commands do not check actual results | Catalyst calculations now run currency conversion and discount checks and warn on a mismatch between legacy and converted results. Calculator partial tenders warn when the spread headline differs from the whole-holding return under full participation and the first residual-price scenario. Legacy numeric and rendered results stay unchanged. These checks run without a quality sidecar. Other source-dependent gates still need evidence. |
| 3. Refclass outputs bypass strict gates | Build, update and show call the new strict publication checker before printing results. It rejects fixture publication and missing deal profiles, re-reads price bars and event evidence, reconciles saved SEC inventories, and recomputes event reactions, market values and class distributions, including the news-filtered distributions. Failed publication returns nonzero. An imported database may remain as a research artifact, but no result is printed on a gate failure. Standalone gates still validate supplied evidence only. |
| 4. Estimated goal dates pass | Both action and goal checks reject expectation, anticipation, planning and intention wording in the matched sentence. Added tests for the exact prospective-submission example in the review. Ambiguous wording requires review rather than automatic acceptance. |
| 5. Correct date wording fails | Added action recognition for `(FDA) approved`, FDA-issued complete response letters, dates before the action clause, `Sept.` and zero-padded days. Regression tests exercise every listed example. |
| 6. Savara profile and source checks | Profiles now re-read primary source line ranges before using first-product status or market value. CLI publication refuses to substitute global context for a missing profile. This checkout has no Savara deal documents, so no factual Savara profile was invented. `show savara` acceptance remains open until the deal and evidence are supplied. |
| 7. Conflicting deal locks | All write operations with the same first argument share a lock. Default Savara, final and biotech runs now have the same lock key. Existing read-command exemptions remain. |
| 8. Thin legacy tests | Added a nonempty renderer workload and saved its output from pre-phase-one commit `1429cc8`. Tests compare full biotech JSON, Markdown and HTML, finder Markdown and HTML, UK-event JSON and ticker requests, and valuation results and Markdown. Existing calculator and catalyst baseline comparisons remain. This proves these offline workloads, not every possible external-service command or input. |
| 9. Collection gaps | `run.sh refclass collect` now uses the logged detached launcher by default, with `--foreground` available. Collection locks cover the cache, and manifest updates reload, merge and atomically replace under a lock. FDA requests include the date window in the query. Malformed SEC filing dates become counted gaps while valid filings continue. Large searches still need bounded partitions if the API pagination limit is reached. |
| 10. Missing sidecar warnings | Missing legacy evidence is silent because research deliberately does not produce sidecars. Malformed or failing supplied evidence still warns. Calculator and catalyst checks operate on the actual inputs and results, so meaningful warnings do not depend on sidecars. The terms step remains research and does not produce a sidecar, as required by amendment 2. Source-evidence production remains phase 3 work. |
| 11. Real detached build | Added and ran a real detached worker test. It builds an empty offline database, logs missing-source diagnostics and the expected nonzero completion status, finishes, is reaped and releases its job lock. It is not a live-data build. |
| 12. FDA API instead of bulk files | Collection now explicitly reports missing CBER coverage and incomplete published-CRL coverage. These coverage gaps are included in collection gap counts and passed into builds. The Drugs@FDA API substitution remains an implementation deviation. No approved amendment was invented and neither specification file was changed. A bulk-file collector or an explicit investor-approved amendment is still needed. |
| 13. Trusted inventory and computation lists | Strict refclass publication re-reads saved SEC submissions and the historical files named by that inventory, checks the latest periodic filing against share evidence, and checks Item 1.03 entries. Refclass metrics are checked from the actual structured output rather than a model-supplied arithmetic list. The general prose/evidence gate still cannot prove that every reported number or relevant filing was supplied. Its standalone success must not be presented as completeness certification. |
| 14. Housekeeping | Preserved the existing nonempty review-3 file. Added a knowledge index and research standards consolidated from repository instructions and reviews, explicitly identifying the missing earlier investor feedback. Made both files distributable and seed-only on upgrade. Added `lib/__init__.py` and a public HTML extraction function used by EDGAR. No commit was made; new files, including the supplied review, remain additions in the working tree for the next commit. |

The repeated review-2 items map to the rows above. Independent comparables, real XBI and the historical census remain open. The renamed-synthetic-price bypass is closed for simple source-label changes because production bars must match saved primary JSON lines. This does not authenticate a manually forged broker response. That requires the live connection and independently checked data.

## Data and publication contracts

A collected candidate is stored even when no reviewed event exists. Reviewed snapshot events supplied alongside collections need a matching candidate identifier and consistent event type and application number. Pending candidates and source gaps appear in the report. Update retains earlier census records. It remains a reviewed assembly pipeline, not automatic factual extraction or independent dual-model tagging.

Saved IBKR bars must be JSON lines in a deal's filings or work folder. Each line needs `provider`, `ticker`, `date`, `close`, `adjusted_close` and `adjustment`. Provider must be `IBKR` and adjustment must be `split_only`. The source stored in the price table is the primary file path plus `#L` and its line number. Current quote records are rejected. Missing symbols, including XBI, are gaps. The file must come from a real saved broker response or a verified conversion during the investor's live build. No production bars were fabricated in this run.

The saved-bar adapter is available through `refclass collect ibkr --bars PATH --tickers TICKER ...`, together with the normal cache, output and date arguments. It consumes saved data and does not connect to IBKR. Full session coverage comes from event-window checks against the supplied calendar, not from the mere presence of one bar per ticker. Independent calendar validation remains necessary during the live build.

Strict event publication currently handles approval and CRL action dates. Other event types fail closed until their source-aware date checks are implemented. It also requires saved announcement evidence containing the exact timestamp representation, source line ranges on tags, and contemporaneous share and inventory evidence. These deliberately narrow contracts need validation against real source formatting. An unpriced event remains stored, but missing required evidence can block publication of the whole result.

The arbitrary-prose publication gate still accepts an explicitly supplied arithmetic list. Closing that remaining completeness problem needs a structured report-to-evidence binding, including sourced facts and labelled estimates, before strict prose publication can be claimed. Adding another self-declared list would not solve it.

## Fixture provenance and verification

The existing downloaded FDA fixtures predate automatic query date bounds. Parser tests replay those exact saved response bodies through an explicitly test-only adapter and preserve their original URLs and download dates. The real offline CLI correctly records a cache miss for a newly bounded query. No download metadata was relabelled to imply a request that never occurred. The live bounded queries still need verification under amendment 4.

The new renderer baseline was generated from the pre-phase-one code, not from the changed implementation. Strict-publication unit tests use explicitly fabricated primary-like files to exercise checks. They are not historical acceptance evidence.

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -v` | 86 tests passed |
| `bash -n run.sh` | Passed |
| `git diff --check` | Passed |
| Network, model and broker requests | None |

The live-build owner still needs to supply the Savara documents, independent comparable timestamps and bars, historical XBI and session data, and complete reviewed FDA/SEC coverage. The open software work includes the live historical MCP adapter, bulk Drugs@FDA ingestion or an approved API amendment, broader event-date source checks, and report-wide evidence completeness. Until those are resolved, phase 1 acceptance must remain open.
