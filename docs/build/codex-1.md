# Phase 1 build status

Partial implementation, blocked on historical source data and the legacy evidence migration. No later phase was built.

Read the manual, system specification, both versioned reference-class files, knowledge index and relevant research notes. Preserved the existing untracked review. Calculation, quality and locking modules already existed untracked at the start. Wrote and ran failing tests before implementing the new engine and integrations or fixing those modules.

Added a SQLite snapshot importer with build, update and show commands. It computes Eastern-time event windows from supplied exchange sessions, adjusted raw and XBI abnormal returns, nested A/B/C counts, quartiles, same-day-news sensitivity and offering flags. It retains unpriced events, marks unknown announcement times, records source gaps, fingerprints rules and requires independent matching first-product tags outside fixtures.

Added publication checks using structured `quality.json`, kernel locks around writing jobs, currency conversion in the catalyst calculator and whole-holding partial-tender headlines. Existing commands retain their dispatch and legacy inputs. Invalid supplied evidence always stops publication; strict mode also stops missing evidence. Default compatibility mode explicitly marks missing evidence unverified. This does **not** meet the specification's requirement for mandatory gates on every output. Source extraction and complete arithmetic coverage of model prose remain unfinished.

Validation passed

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v`, 43 tests.
- Four comparable closing-price sequences and rounded raw returns match the Savara biotech report fixtures. XBI, eligibility metadata and precise pre-market timestamps are explicitly synthetic. This tests arithmetic and import, not a live price feed.
- Offline command tests cover build/show, nested counts, missing sources, publication refusal, duplicate runs, legacy help/version, merger arithmetic and output extraction.
- `bash -n run.sh`, `git diff --check` and parsing all 38 Python files passed. Live model, broker and network commands were not exercised, so their complete behavior is not certified.

The historical FDA/openFDA/EDGAR collection adapters and IBKR daily-bar integration remain unimplemented. No source snapshot or complete historical exchange calendar is available locally. Therefore no production census was populated and phase 1 is not complete. The supplied-snapshot acceptance tests pass; historical coverage does not.

Only installed standard-library modules are used. Optional `exchange_calendars` and `pandas_market_calendars` are absent. Nothing was installed, and no network, broker, model or order calls were made. Deal files were unchanged.

The next build needs saved primary-source samples, historical split-adjusted company/XBI bars and session calendars, followed by source adapters and structured evidence extraction for legacy outputs. Formats and limitations are documented in `docs/refclass-phase1.md`.
