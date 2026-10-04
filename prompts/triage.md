# Sort today's filings

The table under "Candidates for this run" lists new SEC filings that may be special situations. Each one has an excerpt of the filing in excerpt.txt and its details in meta.json.

For each candidate, read its excerpt and details, then write one line of JSON describing it. Work only from those two files. Where something is not in them, say so instead of guessing. This task replaces the report format in the rules above, so do not write a report.

Each line must be a JSON object with these keys.

| Key | What to put in it |
|---|---|
| id | The candidate's ID from the table, exactly as written |
| company | The listed company whose shares a stock investor would trade |
| ticker | Its ticker, or an empty string |
| type | One of merger, tender offer, spin-off, bankruptcy, early signal or other |
| headline | One plain sentence saying what is happening |
| how_money | One plain sentence on how an investor would make money here, with numbers if the excerpt gives them |
| terms | What holders receive and when, in one or two sentences |
| key_dates | Dates that matter, such as the expiry, vote, record or outside date |
| target_ticker | The ticker of the shares that receive the payout, which may differ from the table's ticker when the filing came from the buyer. An empty string if unknown |
| structure | One of cash, stock, cash_and_stock, partial_tender, cash_plus_cvr, spac_redemption, other or none |
| cash_per_share | Cash paid per share at closing, as a plain number, or null |
| stock_ratio | Acquirer shares paid per share, or null |
| acquirer_ticker | The acquirer's ticker when part of the payment is its shares, or an empty string |
| expected_close | The expected closing or payment date as YYYY-MM-DD, your estimate if the excerpt only gives a quarter, or null |
| cvr_min | For a CVR, its smallest possible payout above zero, or null |
| cvr_max | For a CVR, its largest possible payout, or null |
| cvr_payment_date | For a CVR, the earliest date it could pay, as YYYY-MM-DD, or null |
| trust_per_share | For a SPAC, the cash in trust per public share if the excerpt gives it, or null |
| proceeds_may_be_withheld | true if the excerpt says payments to non-US holders may be treated as dividends and have US tax withheld, which is common in company buybacks, issuer tender offers and SPAC redemptions. false if it says they count as a sale. null if it doesn't say |
| spread | If the table gives a quote and the terms are fixed, the gross spread or discount with the math. Otherwise an empty string |
| annualized | The return per year if held to the expected payout, with the math, for example "1.9% over 93 days, about 7.5% a year". Use the expected closing or payment date from the excerpt, and say when it is your estimate. Empty if it cannot be worked out |
| annualized_pct | That yearly return as a plain number, for example 7.5, or null |
| odd_lot | For a tender offer or buyback, "yes" if holders of fewer than 100 shares get their shares bought without proration, "no" if the excerpt says they don't, otherwise "unknown". For anything else, an empty string |
| fits_investor | One sentence on whether this suits the investor profile below, for example that it needs a short sale the account can't make, or that 99 shares cost more than the account holds. Empty if there is no profile |
| why_mispriced | One or two sentences on why the price might be wrong, or "No obvious reason" |
| red_flags | Anything that makes it unattractive or risky |
| score | A whole number from 1 to 5, using the scale below |
| score_reason | One sentence explaining the score |

The scale for score

- 5 means holders of a listed security get a defined value or event on a known timetable, the documents give enough to size the risk, and there is a clear reason it could be mispriced.
- 4 means the same but with one important unknown, or a less obvious reason for mispricing.
- 3 means an early situation worth watching, such as a spin-off announced before its Form 10 is filed.
- 2 means probably not a special situation for a stock investor, such as a listed acquirer buying a private company or a fund's routine repurchase offer.
- 1 means not relevant, such as a routine filing or a company whose shares do not trade.

A Python calculator works out the spread and the return per year from the fields above and the latest prices, so getting those fields right matters more than your own arithmetic.

If the investor's tax profile says they are not a US person, remember that the US usually doesn't tax their gains from a sale, but does withhold tax from dividends. A company buying back its own shares, or a SPAC redemption, can count as a dividend, and then tax may be withheld from the whole payment, which can wipe out a small spread. Mention that risk in red_flags when it applies. If the investor holds an ISA, shares that trade over the counter (the Exchange column says OTC) generally can't be held in it, so score those 1 and say why in fits_investor. You may leave spread and annualized empty when those fields are filled.

If an investor profile is given at the end, score for that investor rather than a generic one. A trade that only works with a short sale scores 2 at most for an account that can't short. A payoff more than 12 months away scores 3 at most, unless most of the value arrives sooner. A tender offer with odd-lot priority, where the investor can afford 99 shares and the premium is meaningful, deserves at least a 4, because those shares are bought in full. Smaller companies are often mispriced because large funds can't trade them, so mention the market cap in why_mispriced when it helps explain the opportunity.

Liquidation candidates are companies proposing to wind up and pay out their cash. The money is made if the distributions exceed the price, so look for the estimated amount per share, when it would be paid, and what could reduce it, such as costs, claims or tax. Put the estimate in cash_per_share and the expected payment date in expected_close, and use structure cash.

Post-reorganization candidates are companies that have just come out of bankruptcy with new shares. Look at how many new shares exist, who received them, whether they trade on an exchange or over the counter, and any plan value per share.

Some candidates are early signals rather than announced deals. Examples are a new activist stake (Schedule 13D), a review of strategic alternatives, a lender forbearance, a restructuring support agreement or a new shareholder rights plan. For these, the score reflects how likely a tradeable situation is to follow soon and how clearly the filing points to it. Most early signals deserve a 2 or a 3. Give a 4 only when the filing makes a deal or a restructuring close and concrete, as a signed restructuring support agreement often does.

Write in plain language and do not use em dashes.

Put the JSON lines, one per candidate and nothing else, between a line that contains only <<<BEGIN OUTPUT>>> and a line that contains only <<<END OUTPUT>>>.
