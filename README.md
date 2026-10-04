# Special situations research kit

A command-line toolkit I built to research event-driven investments from primary documents, such as takeovers awaiting regulatory approval, FDA decisions, fund wind-downs and forced selling from index changes.

It collects filings from SEC EDGAR and UK regulatory announcements, has language models read and cross-check them with citations to the page or line, and leaves every calculation to Python. Decisions and probability forecasts go into a hash-chained ledger with Bitcoin timestamps, so the track record can be verified later.

## What it does

- Finds new situations every day from SEC filings and the Takeover Panel's disclosure table, and writes a short card for each.
- Writes a full report on any situation, drafted by one model and reviewed independently by two others, with each figure traced to its source page in a viewer.
- Tests regulatory risk with data. For FirstCash's purchase of Ramsdens it mapped both chains' stores, measured local overlaps and estimated how many areas the CMA might flag, scaling a random sample up with a margin of error.
- Builds a calendar of upcoming FDA decisions, works out each company's cash runway from XBRL data, and runs deep dives that weigh manufacturing readiness alongside the clinical evidence.
- Keeps a calendar of dated catalysts in undervalued companies, including trust continuation votes, sale processes, legal rulings and index deletions.
- Sizes positions with half-Kelly inside set limits, and scores each prediction against the odds implied by the market price.

## Design

- **Models read, Python counts.** Spreads, implied odds, distances, runway, sizing and sample estimates are all computed in Python from extracted inputs.
- **Every claim is cited.** Reports point to a document and page or line, and the viewer shows an image of each cited page.
- **Read-only by default.** Models can read files but not change them, and no step can place a trade. Only the steps that need the web can browse.
- **Reproducible.** Each run keeps its prompts, inputs, raw replies and logs.

## Case study

[FirstCash's takeover of Ramsdens](case-studies/ramsdens.md), written on 30 September 2026 before the outcome was known. It combines the scheme documents, store-level overlap mapping, OFT and CMA precedent and a probability estimate with a sensitivity range.

## Stack

Bash and the Python standard library, Poppler for PDFs, the SEC EDGAR and XBRL APIs, postcodes.io, OpenStreetMap, Interactive Brokers through MCP, and the Claude Code, Codex and Kimi command-line tools.

## Running it

It needs Linux or WSL, Python 3, Poppler and at least one of the model command-line tools. Copy `settings.example.env` to `settings.env`, fill in your details, then run `./run.sh doctor`. A made-up sample deal shows the output without any setup, with `./run.sh halvern view`. The [full manual](docs/manual.md) covers every command.

This is a personal research tool, not investment advice.

## License

MIT
