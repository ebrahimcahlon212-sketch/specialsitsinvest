# Review fixes, 4 October 2026

The code fixes below are implemented and the offline tests pass. Phase 1 is still not accepted. The census collectors and independently sourced IBKR/XBI acceptance data remain open. No live FDA, SEC or broker data was fetched, and no background job was started during this session.

The latest request authorizes code and documentation edits despite the research-only no-file-edit rule. I preserved the existing, locally modified `docs/build/review-1.md` and used its current contents as the review checklist.

## Item-by-item disposition

| Review item | Change and remaining work |
|---|---|
| 1. Circular comparable acceptance | Renamed the test to describe arithmetic regression and explicitly documented that it does not pass historical acceptance. The report-derived fixture was not presented as independently obtained data. Still open, acquire broker bars and primary timestamps, then compare their computed windows and closes with the report. |
| 2. No data collection | Still open. FDA/openFDA/EDGAR collectors and IBKR acquisition are not implemented. The repository has no production `data/` snapshot. The session's no-web constraint was respected. No empty import or synthetic fixture is claimed to be a census. This is unfinished implementation as well as missing data. |
| 3. Synthetic XBI | Nonfixture imports now reject explicitly synthetic or fixture-labelled price sources. The arithmetic fixture remains visibly synthetic. Real XBI acquisition and historical abnormal-return acceptance remain open. A provenance string alone cannot authenticate a broker response. |
| 4. Gates off by default | Publication defaults to strict. Missing evidence stops output replacement. Model prompts now request an inline QUALITY JSON block; extraction validates it and writes an artifact-specific evidence sidecar. The tender calculator can consume the terms sidecar. Explicit legacy mode remains an unverified compatibility opt-out. Full automatic evidence generation for other legacy renderers, checking N/A declarations, and proving every prose number appears in the evidence remain open. |
| 5. Gates before research | Removed the gate before model invocation. Drafts, mapping, reviews and structured collection steps can run before evidence exists. Publication remains gated. A regression test covers research without evidence, blocked publication, valid generated evidence and preservation of an existing report on failure. |
| 6. Rounded arithmetic | Percentage calculations accept 0.00005 fractional tolerance plus floating-point slack, matching rounding to two decimal percentage places. This applies to returns, abnormal returns, annualized returns, discounts and tender headlines. Tests accept 21.23% and reject a materially different result. Currency and runway tolerance remains 0.005. |
| 7. Tender headline | Removed the fallback from full-participation proration to expected entitlement. Expected entitlement must be supplied. Residual value must be explicit or come from a single supplied back-end scenario. Ambiguity yields a warning and no expected headline. The command summary no longer falls back to the full-acceptance spread or its annualization for a tender. |
| 8. Kit-wide lock | Locks now identify the deal and command. Default deal run and explicit `run` share an identity. Unrelated jobs can proceed; questions, viewing, knowledge and ledger commands do not acquire the deal lock. Database writes retain a separate database lock. Shared legacy JSON stores still need care when distinct writing jobs access the same store. |
| 9. Upgrade rules | Zip installation seeds missing rules/features files. It preserves existing knowledge files rather than overwriting investor conventions. A real temporary-zip regression checks both installation and preservation. |
| 10. Catalyst crash | Currency and extreme-discount failures become per-record calculation errors. Invalid metrics are withheld, and Markdown/HTML display the error while other records still render. Tests cover both the calculator and the rendered output. |
| 11. Background build | `run.sh refclass build` and `update` now launch logged workers. Logs go under `~/special-sits-kit-logs/` and include exit status. The launcher acquires a database job lock before spawning and passes it to the worker. A foreground option supports synchronous imports. Process creation was mocked in tests to respect the session's no-background-task rule; a real detached lifecycle remains untested here. |
| 12. Ignored deal name | Reporting reads `deals/NAME/refclass.json`, shows its source and date, and selects the deepest applicable fixed class. Different deal profiles select different classes. Missing profiles explicitly leave the output as global context. No production Savara profile was invented, so the live Savara acceptance output remains open. |
| 13. Trusted date label | The date gate now requires the date and a saved primary-source line range. It rereads the sentence containing that date and requires FDA action/goal wording. Submission/readout or ambiguous inferred dates fail, even if labelled as a goal. Tests include a submission mislabelled as an FDA goal. This conservative recognizer can reject valid but unfamiliar wording and does not replace source review. |
| 14. Q false positives | The suffix check applies to a fifth-letter Q on OTC or unknown venues. NDAQ passes. A source-backed suffix review with a reason is supported. An Item 1.03 finding remains blocking regardless of that review. |
| 15. Trusted eligibility/share flags | Production admission now rereads listing and applicant evidence, and partner economics where needed. Missing evidence excludes the event with its reason retained in the report. Class C reconciles shares against the latest supplied pre-event filing and rereads its count. Complete listing histories, complete filing inventories and semantic validation of partner economics remain open. These checks verify supplied evidence, not completeness of collection. |
| 16. Review housekeeping | The supplied review is nonempty and was already modified when this session began. It was preserved. This new report records the current fixes without rewriting that review or creating a commit. |

## Validation

| Check | Result |
|---|---|
| `python3 -m unittest discover -v` | Passed, 54 tests |
| `bash -n run.sh` | Passed |
| `git diff --check` | Passed |

The added tests cover rounded percentages, strict publication and research sequencing, missing tender assumptions, residual scenarios, job identities, zip upgrades, resilient catalyst rendering, background-launch lock handling, deal-profile selection, synthetic-price rejection, Q suffixes and rereading production evidence. All test datasets are offline fixtures.

`docs/refclass-phase1.md` now documents the evidence schemas, publication boundary, foreground/background commands, deal profiles and unresolved acceptance requirements. The fixed rules and feature definitions were not changed.

## Still needed for acceptance

Implement and validate the FDA/openFDA/EDGAR collection adapters and the read-only IBKR adapter against real source responses. Preserve raw responses, acquisition dates and coverage gaps. Obtain independent stock/XBI bars and timestamp evidence for the comparable windows. Build the historical census and report actual coverage and unpriced counts.

Complete evidence generation for every legacy publication path and validate the supplied coverage against source inventories. Current text checks are conservative guards, not proof that a model has identified every relevant filing or calculated every number in a report. Run a real detached build and verify lock retention and exit logging outside this session's background-task restriction.
