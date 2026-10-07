# Special situations research kit

A personal research system I use to find and analyse event-driven investments, mainly UK and US situations with a dated outcome such as takeovers, tender offers, wind-downs, spin-offs and FDA decisions. It reads filings and regulatory announcements, drafts a report for each situation, has other models check the draft against the source documents, and keeps a log of predictions made before the outcome is known.

I built it because I invest a small ISA and wanted a process where every number in a write-up traces back to a document I can open. My degree is in bioprocessing, so the FDA side pays particular attention to manufacturing, which is where many rejections actually come from.

## What a run looks like

`./run.sh find` scans the day's SEC filings and UK announcements, including the Takeover Panel's offer list and notices of tenders, liquidations, returns of capital and demergers. Each candidate gets a short card with the terms, key dates, how the money is made and what to watch out for, plus a score from 1 to 5. The score is a reading order, not a verdict.

A recent card, trimmed:

> **Tribal Group plc, UK liquidation.** Tribal has published a circular for a subsidiary sale followed by a proposed cash liquidation. The board estimates at least 105p per share, with an initial distribution expected in Q1 2027 and a final one in Q2 2027. Unexpected claims, taxes or costs could reduce distributions. Score 4 of 5.

Promoting a card creates a deal folder with the documents and starts the research. One model drafts the report and two others review it independently. A final step then re-reads every disputed point in the source before deciding, and the report records each disagreement and how it was settled. Prices come from a read-only IBKR connection, and a Python calculator works out the returns, so no model ever does the arithmetic.

## Rules the code enforces

- **Code computes, models read.** Python does every calculation. Models read documents and make labelled judgements.
- **Sources for every number.** Reports cite the document and line behind each figure. A ledger that gives every fact a single home is planned for the next phase.
- **Rules before results.** The filters for the FDA reference classes were fixed in writing before any results were seen.
- **Agreement is not proof.** When reviewers agree, the check still goes back to the primary document.
- **Predictions before outcomes.** Every call is logged with a probability and a date, then settled and scored.

## The FDA reference-class engine

The newest part, still in development, builds a database of FDA approvals and rejections since 2015 with the share price reaction to each. Daily prices come from Massive in both as-traded and split-adjusted form, with IBKR as a cross-check. The aim is to replace hand-picked comparables with a proper sample, so a deep dive can say how shares in similar situations actually moved on approval or rejection.

Phase 1 code is complete with 142 tests passing. It counts as accepted only once a live run reproduces the comparables from my Savara analysis.

## One bug worth describing

During the build, a model reviewer stated that EDGAR's acceptance timestamps are US Eastern time despite ending in Z, and the claim went into the code. A check against 539 saved filings showed the opposite. Read as UTC, 521 filing dates fit EDGAR's 5:30pm cut-off, against 196 under the Eastern reading. The change was reverted, and a regression test now runs over the saved filings. It is the clearest example of why agreement between models is not treated as proof.

## Commands
./run.sh find # daily sweep
./run.sh promote ID name # turn a card into a deal folder
./run.sh name # research a deal
./run.sh name check # re-check the report against its sources
./run.sh name view # open the report
./run.sh name biotech # FDA deep dive
./run.sh new name # start a deal yourself
./run.sh track name TICKER # attach a company to it
./run.sh predict # log a dated prediction
./run.sh settle # score it once the outcome is known
./run.sh refclass build # build the FDA reference-class database

Full details are in `docs/manual.md`, and the design is in `docs/system-spec.md`.

## How it was built

I wrote the specifications and reviewed every build round. Most of the code was written by OpenAI's Codex and reviewed by Claude. Each round's task and review is saved in `docs/build`, so the full record of what was asked for and what the reviews found is there to read.

The earlier commits in this repository hold my first attempt, a Windows desktop app for researching US spin-offs, which this kit replaced.

## Setup

The kit runs on Linux or WSL with Python 3. Copy `settings.example.env` to `settings.env` and add your own keys, which stay out of git. Prices need a read-only IBKR connection, and the research steps call Claude, Codex and Kimi, as described in the manual.

## Status

This is a personal tool shared to show how it works, not a product, and nothing in it is investment advice. Known gaps include CBER decisions missing from the openFDA data, and companies added by hand not yet getting automatic UK documents or prices.
