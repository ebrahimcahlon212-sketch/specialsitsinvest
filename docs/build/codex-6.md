# Round 6 build handoff

Addressed review-5 against the system specification and its amendments. The local defects below have fixes and regression coverage. Phase 1 is still not accepted. The configured broker's missing adjustment evidence and limited history cannot be repaired by assigning invented fields to its OHLCV responses. Amendment 12 still requires Ebrahim's live build.

The specification and amendments were not changed. No live broker, FDA, SEC or model request was made. The installed Claude CLI help was read locally to check its permission flags. No deal data or investor feedback was invented.

## Verification

| Check | Result |
|---|---|
| `python3 -m unittest discover -v` | 111 tests passed |
| `bash -n run.sh` | Passed |
| `git diff --check` | Passed |

The full suite includes the existing numerical and nonempty renderer compatibility baselines. Added tests exercise actual shell argument construction with a recording stub, the broker guard's accept/deny decisions, exclusions without tickers or 8-Ks, differing evidence ranges, human resolutions, profile wording, split-aware comparable checks, conflicting FDA windows and numeric claims missing from actual prose. Tests do not certify a live broker connection or a historical census.

## Review-5 findings

| Item | Change and status |
|---|---|
| 1. Broker history interface | Partly addressed. The request now names contract-ID `get_price_history`, its `FIVE_YEARS` period and the absence of an end-date parameter. Code reports requested dates outside the lookback. Original plain OHLCV, unsupported schemas and tool errors are retained as explicit gap records instead of aborting extraction or inventing split-adjusted values. The collector records these gaps and keeps affected events unpriced. The provider still cannot establish the two required close conventions from the supplied interface. No genuine saved broker sample exists here, so usable live mapping and price-convention verification remain open. |
| 2. Broker tool permissions | Removed server-wide tool grants from both historical and legacy broker sessions. `lib/ibkr_readonly.py` supplies exact read-tool permissions and a PreToolUse hook that rejects every tool outside its allowlist, including orders, watchlists, alerts, deletions, unknown tools and other MCP servers. Broker sessions omit user/project/local settings sources, so ordinary inherited grants cannot broaden the policy. Built-in tools are separately restricted to Read, Glob and Grep. Local CLI help confirms that `--tools` applies to built-ins, so the MCP restriction does not rely on that flag. Guard tests exercise denial paths directly. Live read-tool name compatibility still needs verification. |
| 3. Exclusions without ticker or 8-K | Reviewed exclusions now require identity, company and primary review evidence but skip inclusion-only ticker and announcement requirements. Builds verify their review seal before saving. Publication still rereads and rehashes their sources. The source candidate becomes reviewed, not pending. No fake ticker or announcement is added to the event payload. |
| 4. Review workflow | Reconciliation compares substantive assertions and feature values, allowing different evidence ranges, tag order, and drug-name case/spacing/punctuation. It preserves both complete model readings and hashes their primary sources. Material disagreements remain pending. Bare `refclass review` lists saved disagreements under `data/refclass/`. `--resolve CSV` accepts Ebrahim's chosen sourced decisions and reasons without editing the original reviews. Human-selected tags and the resolution are recorded explicitly; structured identities and dates remain immutable. |
| 5. Savara profile checks | Added the normal “no products approved for commercial sale” wording, English dates, dollar symbols and thousand/million/billion scaling, while retaining exact-value checks. False first-product claims require positive evidence of an existing US marketed product. Wrong amounts, dates and explicit foreign-dollar tokens are rejected. This remains a conservative parser, not a general interpretation of all filing language. |
| 6. Comparable price conventions | Acceptance now compares report prices with reaction `*_unadjusted_close` fields. Return calculations still use split-only adjusted closes. Targets explicitly declare `close_convention: as_traded` and `return_convention: split_only`, and must include both `day1_raw` and `day2_raw` as fractions. Both returns are checked at the report precision of two decimal percentage points. Regression coverage includes a later split that changes adjusted price levels without changing the returns. |
| 7. Catalyst currency inputs | The prompt now requests the anchor exactly in its source currency and unit, without model conversion to trading units. FX rates have an explicit direction and JSON shape. The existing Python conversion check can therefore see the mismatch. Legacy calculated and rendered values retain their required compatibility behavior and warn when their comparison differs from the converted result. |
| 8. Conflicting FDA windows | The collector rejects extra search date expressions that conflict with its recorded since/until window before any fetch. A redundant identical window is accepted to replay an existing sample. Acceptance still rejects every extra FDA search. Saved historic request URLs and response bodies were preserved, including the conflicting sample, which is tested as rejected input rather than relabelled as a full census. |
| 9. Housekeeping | Removed the obsolete commit/tracking claim from codex-5. Preserved the supplied nonempty review-5. Removed the committed raw `.manifest.lock` files and added an ignore rule. Fixed the next-version wording in the rules notebook. Updated the manual and the stale phase-one guide with the commands, raw source boundary, review resolution, actual gate policy and live limitations. Earlier investor feedback remains unavailable and is not substituted with engineering review notes. |
| 10. Older issues and live acceptance | Missing legacy evidence now emits an unverified warning without blocking. Strict prose extraction binds every numeric token in the actual output to source evidence or a checked calculation with sourced inputs, so an incomplete supplied arithmetic list cannot pass by itself. An existing report survives a failed check. Research stays exempt. Live census, genuine comparable/XBI bars, Savara documents and live `show savara` remain unavailable. |

A further integration fix preserves an already reviewed snapshot's candidates when adding a separate bar collection. Without it, the documented review-to-build flow lost its candidate links. A regression checks this path.

Acceptance now permits recorded IBKR gaps outside the four mandatory comparables. This follows the specification's instruction to retain and count unpriceable events. It does not permit an unpriced comparable, a synthetic bar, pending candidate reviews or an incomplete FDA census window.

## Interfaces to use

```sh
./run.sh refclass review
./run.sh refclass review --prepared data/refclass/prepared/candidates.json --reviews data/refclass/reviewed/claude.csv data/refclass/reviewed/codex.csv --resolve data/refclass/resolutions.csv --output data/refclass/reviewed
./run.sh refclass profile savara --input SOURCED_PROFILE.json
./run.sh refclass acceptance --targets PRIMARY_TARGETS.json
```

Resolution CSV columns are `candidate_id`, `decision`, `event_json` and `reason`. Only resolved candidates need rows. A decision is include or exclude. Supply the chosen complete event and one selected tag per feature. Both model reviews remain unchanged. Resolution attribution is workflow metadata, not an authenticated identity system.

Acceptance targets contain exactly the four tickers, their action dates, three session dates, three as-traded closes, both price-convention declarations and both split-adjusted raw returns. The source target file must be under an allowed primary path. Ebrahim must check its transcription against the original report; a manually prepared JSON file is not proof that the report was transcribed correctly.

Strict prose `numeric_claims` use zero-based start/end character offsets into the final extracted body. A fact uses primary line `evidence`. A calculated token uses a zero-based `computation` index into `arithmetic` and `input_evidence` keyed by input paths, such as `/pre` and `/post`. Every numeric token needs a binding. These checks establish numeric coverage and recomputation, not whether a source's number has been interpreted in the right economic context. Unsupported source formatting fails closed instead of silently estimating it.

## Still open

- The configured broker provides neither explicit as-traded and split-only adjusted closes nor history before its rolling five-year limit. The command preserves the responses and gaps, but cannot reproduce the comparables from plain OHLCV alone. Actual primary adjustment support and any older broker history require a verified capability or an approved specification change. The code does not choose a different price provider.
- Verify actual read-tool names and response schemas against Ebrahim's configured IBKR connection. Unknown names are denied by the explicit allowlist. This build used no live broker calls and cannot claim that its artificial transport tests establish live compatibility.
- Ebrahim must collect and review the historical census, including sponsor coverage and the known CBER and unpublished-CRL gaps. The saved bounded responses are parser fixtures, not census acceptance evidence.
- Supply the Savara documents, sourced profile, checked target transcription, genuine company and XBI bars and a sourced session calendar. Then run the four-comparable check and live `show savara`. Those documents and results are not present here.
- Earlier investor feedback is absent. The notebook accurately identifies the standards it does have; it cannot reconstruct missing feedback.
- The numerical prose gate does not establish source interpretation, omitted nonnumeric claims, whether N/A reasons are justified, or a complete SEC search. Those remain review responsibilities. Automatic evidence production for legacy outputs is still phase 3 work under amendment 1.

All changes are delivered as workspace files for review. This handoff does not claim a commit, a completed live build or phase-one acceptance.
