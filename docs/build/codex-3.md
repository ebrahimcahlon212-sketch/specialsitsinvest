# Codex round 3

4 October 2026

The regressions identified in review-2's new-problems section are fixed under the amendments. The FDA and EDGAR collectors are implemented and tested against small saved primary-source responses. All offline tests pass. This does not establish phase 1 acceptance or a complete historical reference class.

Read order was spec-amendments.md, system-spec.md, manual.md, then review-2.md. The amendments control this implementation. This checkout has no knowledge/INDEX.md or knowledge/research-standards.md. The existing refclass rules and feature definitions were read and left unchanged.

## Regression fixes

| Review finding | Change and verification |
| --- | --- |
| Existing renderers stop without quality.json | Legacy preflight always warns on missing, malformed or failing evidence and continues. An old QUALITY_GATES=strict environment setting cannot turn legacy commands into strict publication. Tests execute catalyst, biotech, finder, UK-event and valuation entry points without mocking out their gates. |
| Calculator looks for the wrong sidecar | The deal calculator reads terms.txt.quality.json, matching the extractor, with the shared quality.json fallback. Tests run terms extraction and calculator output with malformed sidecar evidence and confirm Python still produces the spread and Markdown. |
| Research labels misclassified as publication | All existing model steps default to research extraction. Only final and fund-final use warn-only legacy publication extraction. Tests execute the actual run_step shell function with model stand-ins for drafts, reviews, fund steps, gather-web, valuation, checks, questions, angles, explain, sizing, ideas and the other affected labels. |
| Bad model evidence kills research | Research extraction neither validates QUALITY blocks nor writes evidence sidecars. Malformed JSON and invalid source evidence cannot stop a research answer. |
| Gates can read model output | Source reads resolve paths and permit only the trusted deal's filings or work folders. Tests reject out/draft.md, traversal, another deal's source and a work symlink pointing into output. |
| Parallel steps mutate a shared prompt | Removed the instruction append from run_step. It now reads its prompt without changing it. Stand-in tests check both the prompt each model sees and the unchanged original. |
| Misleading extraction error | The shell reports an output-extraction failure and points to the preceding error and raw reply, rather than saying it could not read a model's reply. |
| Normal FDA date wording rejected | Goal dates accept abbreviated months, day-first dates and statements containing expectations or an NDA submission elsewhere. The date must attach to the FDA date clause. A different submission date in the same sentence still fails. |
| Review file housekeeping | docs/build/review-2.md was present and nonempty when this run began. It and spec-amendments.md were already untracked. Their contents were preserved. No commit was made. |

Amendment 6 was applied literally to the calculator and catalyst numeric and display contracts. Their pre-phase-1 behavior was restored from commit 1429cc8, while retaining warn-only preflight. This includes the legacy tender headline and catalyst calculation behavior. The stricter currency, discount and whole-holding functions remain available and tested in refclass. They no longer change legacy results during this compatibility period.

The saved compatibility fixture tests merger and tender calculator results and Markdown, plus catalyst calculations, against that baseline with a fixed date. Older tests asserting strict legacy publication or changed legacy math were replaced by the amendment contracts. This is focused regression evidence, not a claim that every possible live command and external-service interaction was exercised.

Two additional review items were addressed. The foreground switch is accepted anywhere among build/update arguments, with a shell dispatch test. Strict arithmetic validation rejects an all-N/A evidence object and requires computations. Explicit strict publication still stops before replacing a report when evidence fails. Research remains exempt.

## Collectors

The implementation is in refclass/collectors and uses Python's standard library. No packages were installed.

| Collector | Behavior |
| --- | --- |
| Drugs@FDA | Reads the official openFDA representation of Drugs@FDA. Paginates bounded queries, keeps original approved NDA/BLA submissions, excludes ANDAs and supplements, retains review priority and cites the exact submission within the saved response. Filters on each original action's own date, not a date matched elsewhere in the API record. |
| Published FDA CRLs | Reads the transparency/crl endpoint, preserves letter text and letter date, excludes explicit supplements and retains pending application-eligibility questions. A later approved status does not change a historical CRL into an approval. |
| EDGAR | Reads recent and historical company submissions inventories, selects dated 8-K and 8-K/A filings, downloads primary documents and bounded EX-99 exhibits, and retains accession, filing date, acceptance time and provenance. Keyword matches for FDA events and offerings are source-linked research leads. They are not automatically admitted as events. |

FDA action dates and SEC acceptance timestamps are not substituted for company announcement timestamps. Current SEC tickers and exchanges are labelled current. Historical listing, economics, original BLA versus biosimilar eligibility and first-product status require further evidence.

The HTTP client limits each response, throttles requests and performs bounded retries for rate limits and transient server errors. It uses the saved SEC contact as User-Agent for SEC requests, without copying the contact into fixtures or logs. Live sample requests used the contact from /home/ebrahimcahlon/special-sits-kit/settings.env because this development checkout has no settings.env.

Every saved response has its URL, download time, status, byte count and SHA-256 in tests/fixtures/collectors/manifest.json. The samples were downloaded on 4 October 2026. The manifest records 13 small requests totaling 883,019 response-body bytes, including repeated submissions requests. The 10 unique response bodies occupy 388,994 bytes. No full FDA archive, historical census or price series was downloaded.

The fixture README explains the samples and their limits. Tests verify real approval and CRL parsing, supplemental exclusion, SEC document and exhibit extraction, pagination, duplicate handling, historical submissions, collection bounds, missing sources, malformed schemas, retries, SEC contact headers, throttling and cache checksums. The offline transport never falls back to the network.

## Usage

Collection is an explicit new command. It saves staging JSON containing pending candidates or source filings and a counted gap list. It does not silently certify evidence or overwrite the event database. A bounded or failed collection returns a nonzero status while preserving useful staged results and explaining the gaps.

Replay the saved EDGAR sample without any network request or contact requirement.

```sh
python3 -m refclass collect edgar \
  --offline --cache tests/fixtures/collectors \
  --cik 1160308 --since 2025-10-30 --until 2025-10-30 \
  --max-history 0 --max-filings 1 --max-exhibits 1 \
  --output data/edgar-sample.json
```

For live collection, omit --offline, choose a writable cache and output path, and provide --settings pointing to the existing kit settings if SEC_CONTACT is not already exported. The run.sh refclass collect entry point is also available. FDA source names are drugs_at_fda and openfda_crl. Options include --since, --until, --page-size, --max-pages and --search. EDGAR additionally requires --cik and exposes filing, historical-file and exhibit bounds. A larger FDA search must be partitioned before the API skip limit is reached.

## Verification and remaining work

| Check | Result |
| --- | --- |
| python3 -m unittest discover -v | 71 tests passed |
| bash -n run.sh | Passed |
| git diff --check | Passed before this handoff note |

Stopped after the offline checks, as requested. No model accounts, broker connection, full live build or detached job was launched.

The following remain open from the earlier reviews or the broader spec.

- Ebrahim's live collection, a complete historical census, event reconciliation and independently sourced announcement timing. Collectors stage inputs; build/update still import a prepared snapshot. The Drugs@FDA collector uses the official API dataset, not a bulk-ZIP importer.
- Automatic evidence enrichment and admission of collector candidates to verified classes. EDGAR signals still need research and tagging. Missing or ambiguous attribution and historical listing are not guessed.
- IBKR historical bars and real XBI, reusing the existing kit price integration under amendment 5 and verified during Ebrahim's live build. No alternate price provider or broker/order endpoint was added. The existing current-quote path alone is not proof of historical split-adjusted bars.
- The independent acceptance test for Verona, KalVista, Crinetics and Liquidia. The old report-derived price fixture and synthetic benchmark remain labelled as such and do not satisfy that test.
- A source-rechecked Savara class profile. Existing profile source and locator strings are still not re-extracted by report(), and absent profiles still produce global context.
- Completeness of supplied filing inventories and evidence. Requiring arithmetic computations closes the all-N/A escape, but does not prove every reported computation was supplied. Other N/A assertions still require judgement. Existing production-price guards remain insufficient proof that a source-labelled series is genuine.
- A real detached build run. Launch/lock behavior and foreground dispatch are tested, but no live background build was started in this session.
- Phase 3 evidence-producing workflows and strict publication for legacy commands. Until then, legacy warnings must not be read as evidence certification.
