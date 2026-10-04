# Phase 1 build status

Blocked before implementation.

Read `docs/manual.md`, `docs/system-spec.md`, `knowledge/INDEX.md`, research standards, data pitfalls, deal arithmetic and FDA manufacturing notes. Searched the repository and backups for the reference-class knowledge files.

Both `knowledge/refclass-rules.md` and `knowledge/refclass-features.md` are absent. The specification requires following the former and using its versioned, prespecified filters for nested classes. It assigns feature definitions to the latter. The broad phase 1 scope does not supply the missing nested-class rules or operational feature definitions. Restore these files before defining the expected class membership in tests. Inventing filters from the observed comparables would violate the specification's rules-before-results requirement.

Located the requested comparable prices in `deals/savara/out/biotech.md`, lines 129–132. There is no `deals/savara/out/report.md`. The biotech report contains Verona, KalVista, Crinetics and Liquidia closing-price sequences suitable for the requested fixtures. It does not contain XBI prices, so those company prices alone cannot validate historical abnormal returns. Synthetic benchmark fixtures must be labelled separately from historical observations.

No implementation or unit tests were written. No phase 1 acceptance tests have passed. Stopped at the missing prerequisite as requested, before writing code ahead of tests. Existing commands and deal files are unchanged. `bash -n run.sh` passed; command behaviour was not regression-tested.

Python's `sqlite3`, `unittest`, `decimal`, `statistics` and `zoneinfo` imports succeeded. No missing library was identified in this prerequisite check, and nothing was installed. No network requests or broker calls were made.

To resume, supply the missing rules and feature files, then write and run failing offline tests before implementation, using the biotech report's company prices as fixtures. Phase 1, including every quality gate, remains outstanding.
