# Build round 8

Implemented the actionable phase 1 fixes in `review-7.md`. Read the system specification, amendments through 16, reference-class rules and research standards. No live collection, broker call or model review was run. The supplied `review-7.md` was left unchanged.

| Review item | Change and status |
|---|---|
| 1. Profile market value | Added `market_value_inputs`. Code verifies a saved Massive price, rereads common-share evidence from the deal documents, checks the latest periodic filing against saved SEC inventories, and multiplies the as-traded close by shares. It saves an exact decimal value and prints the calculation with both source references. A supplied market value must match. For a prospective deal, the profile describes the supplied as-of close. For an announced event, the supplied announcement and session calendar verify the pre-news session. No special market-value wording is required in the filing. The older direct-evidence format retains its strict checks for compatibility. |
| 2. First-product attribution | Removed unscoped absence-of-products matches. Positive evidence must refer to the company, including common filing wording such as "We do not have any products approved for sale". Disease-level and competitor statements fail. |
| 3. Broker adjustment convention | Compare IBKR against both Massive closes. Record both differences and which convention matches within one cent. Flag a difference above one cent from both. This avoids treating a split adjustment alone as a price discrepancy without claiming to know the live broker convention. |
| 4. Price-review destination | Bare `refclass review` now reads the selected database's price comparisons and lists flagged differences with both conventions and source references. It also counts missing observations. `--db` and `REFCLASS_DB` select the database. Build/show text summarizes matched, flagged and missing counts; JSON retains all comparison rows. |
| 5. Census collection performance | Request a full history window in one pair of calls per ticker, bounded at 50,000 calendar days. Increased the response-size ceiling to accommodate those windows. Reuse successful exact requests across saved download dates after checksum and response validation. Failed requests remain retryable; `--refresh` bypasses reuse. Added `--calls-per-minute`, defaulting to the free-tier limit of five. Paid history does not silently raise the rate. The existing `run.sh` route already detached collect/build/update and logged under `~/special-sits-kit-logs/`; new tests verify collection dispatch, log placement and inherited locking. Direct Python execution and explicit `--foreground` remain synchronous. |
| 6. Review readability and old results | Show only differing substantive fields and feature values, alongside review reasons and evidence errors. Discover older disagreement files under `data/refclass` even without registry entries. Current registry entries supersede stale rows, including resolved candidates. |
| 7. Conflicting updates | Reject conflicting IBKR observations before replacing the existing dataset. Equal observations deduplicate. The regression checks that a rejected update leaves the database bytes unchanged. |
| 8. Earlier deferred and live work | Still open as specified below. No phase 3 implementation or live acceptance is claimed. |

Updated the manual and phase 1 notes with the calculated profile schema, review output, resumable collection and paid-plan options. Reference-class rules are now version 4 to record the clarified broker comparison. Existing databases must be rebuilt before reporting or updating under the new rules.

## Validation

| Check | Result |
|---|---|
| `python3 -m unittest discover -v` | All 132 tests passed, including eight new round-eight tests. Final run took 2.674 seconds. |
| `bash -n run.sh` | Passed. |
| `git diff --check` | Passed. |

New tests use temporary synthetic filing and price evidence, plus the existing saved Massive responses. They cover profile calculation and class C selection, exact saved-value revalidation, price and inventory tampering, historical session selection, disease attribution, split-adjusted matching, price differences in the actual review command, atomic update rejection, old review discovery, field-only differences, long-window request counts, cache reuse across dates, refresh, checksum failures, paid-rate spacing and collection job dispatch. Existing legacy compatibility tests also pass.

## Still open

- Review-6 problem B remains phase 3 work. The standalone strict numeric prose checker is still not wired into a real publication command. This preserves the amendments' legacy warn-only behavior and research exemptions.
- Ebrahim must run the live checks assigned by amendments 4, 5, 10, 12 and 14. These include IBKR response shapes, contract mapping and adjustment convention; the upgraded full census and coverage counts; the four comparable prices from Massive; target transcription against the original report; and a real Savara profile followed by `show savara` and acceptance. This checkout still lacks the complete live inputs. The new synthetic profile regression proves the code path, not Savara's facts or acceptance.
- Resume requires the same explicit request dates. Changed dates make new requests. Changed historical vintages need refresh and preservation in a new dated directory if existing normalized bars differ. No automatic paid-plan entitlement detection is claimed.
- The connector authorization note in the review concerns the user's external connector settings. Those connectors were not needed or changed for this build.
