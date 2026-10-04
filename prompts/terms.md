# Extract the deal terms for the calculator

A Python calculator works out this deal's numbers, so you don't have to. Your job is to give it correct inputs. Read the files listed under "Files for this run", which are either a draft and its reviews or a previous report and new documents, and check any input you are unsure of against the filings. Where the reviews corrected the draft, use the corrected value.

Give dividends at their full amount before any tax, because the calculator applies the investor's tax rate itself. Write one JSON object with the keys below. Leave out any key that does not apply, and use null when a value applies but is unknown. Use plain numbers without currency signs or commas. Use the same currency unit throughout, and for UK shares use pence with "currency" set to "GBX".

| Key | What to put in it |
|---|---|
| structure | One of cash, stock, cash_and_stock, partial_tender, cash_plus_cvr, spac_redemption or other |
| target_ticker | The ticker of the shares an investor would buy |
| currency | USD, GBX or GBP |
| cash_per_share | Cash paid per target share at closing |
| stock_ratio | Acquirer shares paid per target share |
| acquirer_ticker | The acquirer's ticker, when part of the payment is its shares |
| dividends_to_close | A list of dividends still to be paid before closing, each {"who": "target" or "acquirer", "date": "YYYY-MM-DD", "amount": number} |
| close_scenarios | A list of possible closing dates, each {"date": "YYYY-MM-DD", "prob": number between 0 and 1}. The probabilities are the chance of closing on each date, and together they are the overall chance of closing |
| expected_close | A single expected closing date, if you give no scenarios |
| p_close | The overall chance of closing, if you give no scenarios |
| break_price | Where the target would likely trade if the deal failed |
| costs_pct | One-off buying costs as a percentage, for example 0.5 for UK stamp duty on Main Market shares |
| hurdles_pct | Target returns per year to test, for example [10, 15] |
| tender | For a tender offer, {"price", "shares_sought", "shares_outstanding", "shares_held_by_bidder", "expiry": "YYYY-MM-DD", "odd_lot_priority": true or false, "back_end_prices": {"label": price}} where back_end_prices are plausible prices for shares returned through proration |
| cvr | For a CVR, {"min_payout", "max_payout", "earliest_payment": "YYYY-MM-DD", "scenarios": [{"label", "payout", "prob"}]} with the scenarios optional |
| trust_per_share | For a SPAC, the cash in trust per public share |
| proceeds_may_be_withheld | true if the offer document's tax section says payments to non-US holders may be treated as dividends and have US tax withheld, which is common in company buybacks, issuer tender offers and SPAC redemptions. false if it says they are treated as a sale. null if it says nothing |
| otc | true if the shares trade over the counter rather than on an exchange |
| redemption_date | For a SPAC, when redeemed shares are paid |

Put only the JSON object between a line that contains only <<<BEGIN OUTPUT>>> and a line that contains only <<<END OUTPUT>>>.
