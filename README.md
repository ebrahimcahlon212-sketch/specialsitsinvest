# filing-date-rag

Point-in-time cocoa and sugar research prototype with source-linked retrieval and offline evaluation.

I built this after noticing how easily research Q&A tools answer with information that was not public at the date being asked about. This prototype refuses to do that: ask a cocoa or sugar question at a chosen UTC cutoff and it retrieves only eligible evidence, showing where each passage came from. It builds on the public cocoa positioning and sugar USDA-vintage studies without changing either research protocol.

The local evidence browser works without an API key. An optional OpenAI agent adds three tools: evidence search, a DuckDB evidence lookup, and a calculator grounded in retrieved numbers.

## What is here

- 28 logical vintage/snapshot extracts and 92 citable passages from 34 preserved input files.
- ICCO balances, regional cocoa grindings, U.S./Mexico USDA sugar vintages, and compact cocoa and Sugar No. 11 positioning snapshots. Complete imported CSV histories remain on disk.
- BM25 retrieval, with an opt-in OpenAI embedding adapter and reciprocal-rank fusion.
- A local FastAPI backend, Streamlit interface and downloadable JSON research records.
- Deterministic corpus checks, 74 passing offline tests, Ruff and strict Mypy checks.
- 37 authored offline evaluation cases. Expected evidence appeared in the top six for all 18 answerable cases, but ranked first in only 14. All 12 metadata-boundary cases passed.

The corpus is a set of research extracts, sized for audit rather than volume. Citations name exact CSV records or sections, and none invents a PDF page. Source URLs, extract hashes, upstream hashes where available, capture times and publication uncertainty remain attached.

## Run locally

Tested on Windows x64 with Python 3.12.14. Other platforms are not yet verified.

```
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
powershell -NoProfile -File scripts/start.ps1
```

On a prepared installation, double-click `Start Research.cmd`. It starts local services and opens http://127.0.0.1:8511. `Stop Research.cmd` stops the process trees rooted at the launcher's verified process IDs and creation times. Logs stay in the ignored `logs/` folder.

For manual startup, use separate terminals:

```
.\.venv\Scripts\python.exe scripts/run_api.py
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The API defaults to port 8011 and accepts `PORT`; the UI reads the same environment variable. Keep both bound to loopback. There is no authentication layer, so please do not expose it publicly.

## Try the date distinction

Ask: **What was the latest ICCO cocoa surplus estimate for 2024/25, and how had it changed?**

At `2026-06-01T00:00:00Z`, public-as-of retrieval can surface the retained May estimate of 48 kt and the preceding estimate of 75 kt, a difference of -27 kt. The answer evidence lives in the retrieved records; this section only summarises what they contain. The published balance is calculated differently from gross production minus grindings.

Switch the same question to captured-as-of. The inherited studies captured these sources in August, so strict replay cannot use them in June. That difference is the point of the app.

| Mode | Eligibility |
| --- | --- |
| Published by then | Source-vintage public availability is at or before the cutoff |
| Captured by then | Public availability and inherited source-study capture are both at or before it |
| Current snapshot, either mode | Capture must also precede the cutoff; current CFTC values are never backdated |

Public mode is a retrospective reconstruction from later-captured extracts. Strict mode uses the inherited study's capture time; I am not claiming this app existed at that time. Neither mode implies the corpus covers everything the market knew.

## Optional live AI

Keep a key in `.env.local` as `OPENAI_API_KEY=...`; never put it in the browser or commit it. Set `RAG_ENABLE_LIVE=true`, or start with `scripts/start.ps1 -LiveAi`. The UI still defaults to evidence-only mode, and selecting AI answer or vector search incurs API usage only on submit. One thing I learned the hard way: a ChatGPT subscription does not come with API credit.

The live smoke attempt on 4 September 2026 reached the API but received HTTP 429. No live answer or vector-quality result was produced, and the cause was not resolved beyond an account or rate-limit response. The retained output is at `evals/results/live-smoke-20260904-attempt2.json`. Treat the live path as untested until a successful run exists.

```
python scripts/live_smoke.py --confirm-api-cost --hybrid --output evals/results/local-new-run.json
```

This runs a bounded revision question, a strict-replay abstention and a future-override question through the actual service. Each run requires a new output path. It is a smoke check, nothing more.

## Verification

```
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy
python scripts/build_corpus.py --check
python scripts/evaluate.py --check
```

Tests prohibit network requests, including to local HTTP services. On Windows, only asyncio's internal socket-pair construction is allowed as local IPC. CI installs dependencies first, then runs the offline checks without secrets. The corpus rebuild does not need the sibling repos. The publication-exclusion tests require Git and use a fresh temporary repository to verify that credentials, runtime logs and test scratch files stay ignored while public inputs remain usable.

The evaluation report records misses alongside hits, and keyword matches on unsupported questions never count as successful refusals. Semantic faithfulness, citation precision, live-model refusal quality and dense retrieval quality remain **NOT EVALUATED**.

## Boundaries

Date filtering runs before BM25 statistics, embedding and DuckDB registration, so the model cannot move the cutoff. Output checks require retrieved IDs, eligible sources, exact excerpts and numeric-token presence. If the model writes limitation prose it cannot cite, that prose is discarded. Calculations use Python Decimal and retain both operand citations.

These checks do not establish entailment, relevance, compatible units, causality or prediction. The model can still misread an eligible passage. Number words and units need human review, and retrieval confidence is not calibrated. Evidence-only mode returns passages rather than an answer. Conflicts are model-flagged; there is no independently validated conflict detector yet.

DuckDB currently filters cited passages only, and the complete typed positioning histories are outside its scope for now. Cross-encoders, company-filing ingestion, full-paper scientific review and a PDF-page corpus are all future work. The repo has no live trading feed, no private or licensed datasets, no fine-tuning, no multimodal analysis and no broker connection, and it makes no return-prediction claim.

The single-agent run has turn and tool budgets plus a timeout. Embedding cancellation stops new batches but cannot retract a request already sent to the provider. Tracing and response storage are disabled in requests; provider handling is governed by the account's API data policies.

## Next work

Add a small permitted original-document corpus with verified page/section locators, a tested typed CSV-history adapter, a real reranker, and a separately reviewed held-out answer eval. Then measure the live pipeline before considering public hosting.

See source boundaries, dependency reasons, agent prompt, and AI usage. Publishing the source does not deploy the app: it still runs locally, with no public hosted service.

## Publication history

This repository publishes an existing local prototype in topic-based commits: setup, source data, retrieval controls, the application, and tests/evaluation. The commits are publication stages rather than a reconstruction of the development timeline, and their timestamps record the publication work itself. The imported studies retain their own source dates, capture times and commit references.
