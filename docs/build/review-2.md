I couldn't run the tests. This session's permission mode refused `python3 -m unittest discover -v` both times I tried it, as it did in round 1. codex-2.md says 54 tests pass, but I haven't confirmed that. Everything below comes from reading the diff of `9446bc3` and its call sites. To run the tests yourself, use `python3 -m unittest discover -v` from the kit folder.

## Review-1 items still open

| # | Item | Status |
|---|---|---|
| 1 | Comparable test is circular | **Open.** The test is renamed and the fixture README now says it is not the acceptance test. No independent bars or timestamps exist yet. |
| 2 | No data collection | **Open.** There are still no collectors for FDA, openFDA, EDGAR or IBKR, and there is no census. |
| 3 | Synthetic XBI | **Open.** There is no real XBI series. The new guard only rejects price sources whose label contains "synthetic" or "fixture" (`refclass/engine.py:209-212`). |
| 4 | Gates off by default | **Partly fixed, but easy to bypass.** The default is now strict. However, `validate` accepts `{"not_applicable": "..."}` for all seven gates, including arithmetic (`refclass/quality.py:129`). A report full of numbers can pass with an all-N/A block, and that is exactly how the test "publishes" (`tests/test_review_fixes.py:26,61`). |
| 11 | Background build | **Mostly fixed.** The real detached run is untested, and `--foreground` only works if it comes straight after `build` or `update` (`run.sh:1257`). |
| 12 | `show NAME` ignores NAME | **Partly fixed.** The profile's `source` and `locator` are plain strings that are never re-read. The class is chosen only from `first_product` and `market_value` (`engine.py:316-324`). There is no Savara profile, so `refclass show savara` still prints global context. |
| 15 | Gate inputs taken on trust | **Partly fixed.** Supplied evidence is now re-read, but the inventory of filings is still taken on trust. |

Items 5 to 10, 13, 14 and 16 are fixed as described. The fixes for 5 and 8 introduce new problems, covered below.

## New problems, most serious first

1. **Strict-by-default breaks existing commands.** Spec line 216 requires them to keep working.
   - These renderers call `preflight(out)`, which needs `out/quality.json`, and nothing in the kit writes that file:
     - `lib/catalysts.py:176`
     - `lib/biotech.py:269,296`
     - `lib/finder.py:872`
     - `lib/ukevents.py:43`
     - `lib/valuation.py:287`
   - So by default, `catalysts`, the `biotech` calendar, `find`, UK events and fundamentals valuation all stop with an uncaught `GateError`. The catalyst test hides this by patching out `preflight` (`tests/test_review_fixes.py:119`).

2. **The calculator can never find its evidence, so it is silently skipped.**
   - `extract_output.py:115` writes `terms.txt.quality.json`, but `calc.py:430` looks for `terms.json.quality.json`. Both fall back to `quality.json`, which doesn't exist, so `calc.py deal` fails.
   - `run_terms` turns that failure into "the report will do its own arithmetic" (`run.sh:273`). Every deal report then ships without Python's numbers, which breaks "code computes, models read".
   - `step_biotech`'s `calc.py deal` and `relabel` path fails the same way.

3. **Steps classed as publication die without a QUALITY block.**
   - The research list at `run.sh:184` leaves out `fund-draft`, `fund-review` (it doesn't start with `review`), `gather-web`, `valuation`, `check-*`, `ask-*`, `angles`, `explain`, `sizing` and `idea-*`.
   - `./run.sh NAME ask` now needs a full seven-gate evidence block, or it stops with "No answer was produced".

4. **Research steps can be killed by bad evidence.**
   - The QUALITY instructions are appended to every prompt, drafts included (`run.sh:140`).
   - In research mode, any block that is present is still validated, and a failure exits 1 (`extract_output.py:110-119`).
   - So a draft model that tries the evidence and gets a line range wrong kills the draft step. That brings back the problem item 5 was meant to fix.

5. **The gate's "re-read the primary source" accepts any file.**
   - `source_excerpt` opens whatever path the model gives it (`refclass/quality.py:57-65`). Nothing limits it to `work/` or `filings/`.
   - A date sentence in the model's own `out/draft.md` would therefore pass the date-type gate.

6. **Parallel steps append to the same prompt file while models read it.**
   - The review, fund-review and check steps (`run.sh:230`, `:499`, `:828`) start several `run_step` calls in the background on one `$p`.
   - Each call appends the instruction block again, so with three reviewers the prompt gets it three times. The appends can land while another model is reading the file.

7. **Two minor issues.**
   - A gate failure is reported as "could not read the reply from MODEL" (`run.sh:190`), which hides the reason in that message.
   - The decision-date recognizer rejects any sentence containing "expect", "anticipat" or "submit". It would reject common wording such as "PDUFA target action date of November 20, 2026 for the NDA submitted in March". It also doesn't match "Nov. 20" or "20 November 2026" (`quality.py:76-81`).

8. **Housekeeping.** `docs/build/review-2.md` is untracked and empty.

**Verdict:** Phase 1 is still not accepted, and this commit regresses the kit. Data collection, real XBI and the comparable acceptance test are still open, and making strict gates the default without anything that produces the evidence breaks catalysts, biotech, find, fundamentals, ask and the deal calculator.
