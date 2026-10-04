# One research system: kit plus FDA reference class engine

Oct 4, 2026 · @Poop

## Purpose and principles

The system turns filings into dated, scored predictions, and every number in it traces to a source line or a labelled judgement. It merges the existing kit and the new reference class engine around one ledger, so there is one flow rather than two tools.

- **Code computes, models read.** Python does every calculation, date, unit and statistic. The language models read documents and make labelled judgements.
- **Every number has one home.** Sourced facts live in the evidence ledger with their source line and as-of date. Judgements live on the assumptions sheet with the reference class behind them.
- **Rules come before results.** Reference class filters and model conventions are written into knowledge files before any result is seen, and every change is versioned.
- **Agreement is not proof.** Two models reading the same excerpt share its blind spots, so checks re-read the primary source and disagreements go to Ebrahim.
- **The broker link is read-only.** The kit reads prices and positions and never places or changes orders.
- **Predictions come before outcomes.** Each decision logs its probability and the components behind it, and each settled outcome becomes a new row in the reference class tables.

## How the pieces fit

&#91;embedded content: system flow · 8 steps, 1 loop\]

Deep dives and models start from the reference class, and each settled outcome adds a row to it.

## Evidence ledger

Every model reads its numbers from one facts table per deal, and nothing is typed into a model by hand. The table lives at `deals/NAME/ledger/facts.csv`, so it is easy to read and to diff.

| Column | Meaning |
| --- | --- |
| fact\_id | Stable id, such as `cash_2026q2` |
| name | Plain description of the fact |
| value | The number or text as reported |
| unit | Unit and currency, such as USD m or GBp |
| as\_of | Date the fact describes |
| source | Path or URL of the primary document |
| locator | Line or page in that document |
| extracted\_by | Model or person that entered it |
| checks | Code checks passed, and the two model re-extractions |
| status | pending, verified, disputed or stale |

- A fact starts as pending and becomes verified only when the code checks pass and both checkers re-extract the same value from the primary source.
- A disputed fact blocks every model that uses it until Ebrahim resolves it in `./run.sh NAME ledger`.
- A fact past its freshness limit becomes stale, for example cash older than the latest 10-Q.
- Evidence gathered outside the kit, such as screenshots or emails, enters as a Markdown note in `deals/NAME/out/answers/` and is cited as that note.

## Reference class engine

A new `refclass` module keeps one table of historical FDA events with fixed feature tags, and Python computes base rates and price reactions from it. Models fill the tags but never choose the class, so the same rules give the same answer every time.

### Sources

| Source | What it gives | Phase |
| --- | --- | --- |
| Drugs@FDA data files | Approval dates and review priority | 1 |
| FDA CRL database on openFDA | Published complete response letters and their text | 1 |
| Company 8-Ks on EDGAR | Submission and goal dates, unpublished CRLs, extensions, offerings | 1 |
| IBKR daily bars | Closing prices for each company and for XBI | 1 |
| FDA orphan designations database | Orphan status and date | 2 |
| CDER breakthrough approvals list | Breakthrough status | 2 |
| FINRA short interest | Short interest by settlement date | 2 |
| Orange Book and Purple Book | Patent and exclusivity dates | 4 |
| CMS ASP files and NADAC | Drug prices over time | 4 |

### Tables

Everything sits in `data/refclass.sqlite`. Event types are approval, crl, refusal\_to\_file, extension and resubmission\_accepted.

| Table | Key columns |
| --- | --- |
| events | event\_id, company, ticker, drug, application, event\_type, announced\_at, goal\_date, source |
| tags | event\_id, feature, value, tagger, locator, agreed |
| prices | ticker, date, close, adjusted\_close |
| reactions | event\_id, pre\_close, day1\_close, day2\_close, XBI on the same days, abnormal returns, offering\_within\_5d |

### Tagging

The features are modality, first product, single asset, market value band at the pre-news close, orphan, breakthrough, priority review, prior CRL type, prior refusal to file, major-amendment extension, advisory committee outcome, contract manufacturer for drug substance or drug product, 60-day run-up against XBI, short interest and label surprise.

- Two models tag each event independently from its source documents and cite a line for every tag.
- Agreed tags are stored, and disagreements wait in `./run.sh refclass review` for Ebrahim.
- The feature list lives in `knowledge/refclass-features.md`, and adding a feature means re-tagging every event.
- Events for companies later delisted or acquired stay in the table, and any event IBKR cannot price is kept and counted as unpriced.

### Filters and outputs

Filters come from `knowledge/refclass-rules.md`, saved before any results, and every output records the rules version. Results are shown for nested classes from broad to narrow, with the event count at each level, so a thin class is obvious.

For each class the engine reports:

- approval rate with counts and a 90% Wilson interval
- time from submission to action, median and interquartile range
- CRL reason mix, and resubmission outcomes and timing by CRL type
- day-one and day-two abnormal returns against XBI for approvals and for CRLs, median and interquartile range
- share of approvals followed by an equity offering within five trading days
- launch price and price erosion after exclusivity ends, from phase 4

### Likelihood ratios

```latex
LR = \frac{P(\text{feature} \mid \text{approved})}{P(\text{feature} \mid \text{rejected})}
```

Counts get 0.5 added before dividing, and every ratio is shown with its counts. A ratio resting on fewer than 10 events in either group is flagged and never applied automatically. Correlated features, such as orphan and breakthrough, are reported together so they are not counted twice.

### Backtest

The engine builds its tables from events up to a cutoff, 31 December 2022 by default, and predicts every later event. It reports the Brier score and a calibration table by probability band. Live use starts only after this test passes, and the test reruns whenever rules or features change.

## Model builder

Each deal's Excel model is generated from the ledger and the reference class outputs, using formulas only, so changing one fact or assumption updates every result. The existing Savara model is the template.

| Sheet | Contents | Reads from |
| --- | --- | --- |
| Facts | Verified ledger rows, read-only | Ledger |
| Assumptions | Each judgement with its range and the reference class behind it | Ebrahim and the deep dive |
| Probability | Base rate, likelihood ratios, posterior odds and probability | Assumptions and refclass |
| Outcomes | Mutually exclusive outcomes split by failure type, with probabilities and event prices | Probability and EventPrice |
| EventPrice | Approval and rejection reactions from the reference class, applied to the live price | refclass and IBKR |
| Valuation | Risk-adjusted NPV across markets, with competition and exclusivity inputs | Facts and Assumptions |
| MarketImplied | Approval probability and approval price implied by the live price | Outcomes and IBKR |
| Sensitivity | Each input moved across its range, ranked by effect on expected value | All sheets |

- Every calculated cell is a formula, and numbers appear only on Facts and Assumptions.
- Event prices drive expected value and Valuation is a cross-check, because the approval-day price and fundamental value answer different questions.
- Probability uses the odds form, where posterior odds equal base-rate odds multiplied by each likelihood ratio.
- Python recomputes every output before saving, and the workbook must match it to the cent.

## Memory and questions

Everything the kit learns is saved in four stores, and every question to the CLI reads all of them before answering.

| Store | What it holds | Where |
| --- | --- | --- |
| Evidence ledger | Facts per deal with sources and check status | `deals/NAME/ledger/` |
| Reference classes | Historical FDA events, tags and price reactions | `data/refclass.sqlite` |
| Decision log | Decisions, predictions, their components and outcomes | `journal/` |
| Knowledge | Research standards, lessons and saved feedback | `knowledge/` |

- `./run.sh NAME ask` reads the deal's verified facts first, then refclass outputs, the decision log, knowledge and finally the deal's documents, citing each source.
- A new `./run.sh ask "..."` answers across all deals and the reference classes, for questions such as how manufacturing-only rejections have resolved.
- An answer never becomes a fact by itself. A new number in an answer enters the ledger as pending and goes through the same checks.
- Python computes any number an answer reports from the stores, and unverified or stale items are labelled as such.
- This ships with phase 3. Its test is that asking for Savara's cash returns the ledger value with its source line.

## Quality gates

Code checks run before any card or model is written, and a failed check stops that step with a plain message. Each gate answers an error from recent runs, named in the last column.

| Gate | Rule | Error it would have caught |
| --- | --- | --- |
| Units and currency | Convert NAV and price to one currency and unit, and flag any discount below -50% or above 90% | PEY's -5047% discount |
| Staleness | Reject cash or share counts older than the latest 10-Q | Viridian's 2019 cash |
| Listing status | Check for a Q suffix and 8-K Item 1.03 filings since the as-of date | BioXcel's Chapter 11 |
| Attribution | The applicant must be the company, or a partner with disclosed economics | Edgewise and Jade carrying competitors' dates |
| Date type | A decision date must be an FDA action or goal date, not a submission or readout | Opus and Viridian |
| Arithmetic | Recompute every reported number, and use all cash and marketable securities for runway | Agios runway |
| Partial tenders | Headline the whole-holding return at the expected entitlement | HVPE's 37% headline |
| Run lock | Refuse a second start of a job that holds a lock file | The double Savara run |

## Commands

Existing commands keep their names and behaviour, and the new ones sit beside them.

### New

| Command | What it does |
| --- | --- |
| `./run.sh refclass build` | Builds the event table from all sources and tags it, run in the background |
| `./run.sh refclass update` | Adds events since the last build, including settled predictions |
| `./run.sh refclass show NAME` | Prints nested classes, base rates, price reactions and likelihood ratios for a deal |
| `./run.sh refclass backtest [CUTOFF]` | Runs the calibration test from a cutoff date |
| `./run.sh refclass review` | Lists tag disagreements to resolve |
| `./run.sh NAME ledger` | Shows the deal's facts with status and sources |
| `./run.sh NAME model` | Generates the Excel model from the ledger and refclass |
| `./run.sh screen froth` | Lists stocks up over 200% in a year and checks them for the Babcock filing pattern |

### Changed

| Command | Change |
| --- | --- |
| `./run.sh NAME biotech` | Starts from `refclass show` and lists every likelihood ratio it applies |
| `./run.sh NAME check` | Verifies ledger facts against primary sources and the refclass tables |
| `./run.sh NAME sizecalc` | Uses the event-price distributions from refclass |
| `./run.sh settle` | Appends the outcome to refclass and scores each logged component |
| `./run.sh insiders` | Flags routine and opportunistic insiders, with an option to show sales |
| `./run.sh decide ID pass` | Records the price and reason so passes can be settled later |

## Build phases and acceptance tests

Phase 1 should be finished by 13 November, so the Savara note can use it before the 20 November decision. Later phases follow the order in which live decisions need them.

1. **Event prices and quality gates, by 13 November.** Approvals and CRLs since 2015 for the first products of companies under $3 billion, with day-one and day-two abnormal returns, plus every gate in the quality section.
   - It reproduces the four comparables in the Savara report to the cent, Verona, KalVista, Crinetics and Liquidia.
   - It reports how many events it found and how many it could not price.
   - It marks any event whose announcement time is unknown.
   - `./run.sh refclass show savara` prints the nested classes with counts.
2. **Rates and likelihood ratios, by 31 December.** Feature tags, approval and resubmission rates, likelihood ratios and the backtest.
   - The backtest from a 2022 cutoff reports a Brier score and a calibration table.
   - Every likelihood ratio shows its counts.
   - `refclass show uncy` and `refclass show achv` print resubmission outcomes by CRL type.
   - Tag disagreements stay under 10% of tags, or the feature definitions are tightened.
3. **Ledger and model builder, by 31 January 2027.** Facts tables for live deals and generated workbooks.
   - The generated Savara workbook matches the existing model's outputs.
   - Changing one fact updates every dependent cell.
4. **Prices and exclusivity, by 31 March 2027.** CMS price series and Orange Book and Purple Book dates feeding the valuation sheet.
   - Erosion curves are produced for a test set of drugs with known exclusivity losses.
   - Each curve cites its CMS files.
5. **Froth screen and insider flags, after phase 4.**
   - The screen finds Babcock & Wilcox in its 2026 data, with each of the four signals cited.
   - Insider flags match the routine definition, a trade in the same calendar month for three years running.

## Working instructions for Claude Code

Build in small steps inside `~/special-sits-kit`, and pass each phase's acceptance list before starting the next.

- Read `knowledge/research-standards.md` and `knowledge/refclass-rules.md` first, and follow both.
- Keep every existing `run.sh` command working, and add subcommands rather than renaming.
- Put the engine in a Python package with unit tests for the odds form, Wilson intervals, abnormal returns and currency conversion.
- Use the existing IBKR MCP connection for prices only, and never call an order endpoint.
- Respect SEC fair-access limits, using the saved contact and a request rate limit.
- Write long jobs to logs under `~/`, and refuse a second start of a running job.
- Never delete deal folders, and write outside the kit folder only for logs.
- When a source cannot be reached or parsed, record the gap and report the count rather than guessing.
- Generated reports use plain, direct prose without em dashes or decorative metaphors, and avoid  jargon without explaining simply.
