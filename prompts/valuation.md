# Extract the valuation inputs for the calculator

A Python calculator values this business, so you don't have to. Read the fundamentals draft and its reviews listed under "Files for this run", and check any input you are unsure of against the filings. Where the reviews corrected the draft, use the corrected value.

Write one JSON object with the keys below. Use plain numbers without currency signs or commas. Financial figures are in millions of the reporting currency, and share prices are per share in the trading currency.

| Key | What to put in it |
|---|---|
| price_currency | GBX for pence, GBP or USD |
| reporting_currency | The currency of the accounts, such as GBP or USD |
| fx_to_price_currency | How many units of the price currency's main unit one unit of the reporting currency buys, for example 0.79 for USD accounts and a GBP price, or 1 when they match |
| shares_diluted_m | Diluted shares in issue, in millions |
| net_debt_m | Net debt including leases, in millions, negative for net cash |
| other_claims_m | Minority interests, pension deficits, earn-outs or other claims ahead of shareholders, in millions |
| undisturbed_price | The share price before any approach or rumour |
| offer_price | The offer or proposal price per share, or null |
| history | A list of years, each {"year", "revenue_m", "ebitda_m", "ebit_m", "capex_m", "fcf_m"}, using adjusted figures only if the reports explain them |
| forward | Next year's expected figures, {"year", "revenue_m", "ebitda_m", "ebit_m", "fcf_m", "basis"}, where basis says whether it is company guidance or your estimate |
| multiples | EV to EBITDA multiples worth testing, for example [6, 8, 10, 12] |
| leases_in_net_debt | true if net_debt_m already includes lease liabilities, so lease payments must not also be taken off free cash flow |
| scenarios | A list of cases, usually bear, base and bull. Build each from its parts rather than giving a free cash flow figure, as {"label", "revenue_m", "growth_pct", "ebit_margin_pct", "tax_rate_pct", "da_pct_revenue", "capex_pct_revenue", "working_capital_pct_revenue", "lease_payments_m", "years", "terminal_growth_pct", "discount_pct"}. revenue_m is the starting year's revenue, da_pct_revenue is depreciation as a share of revenue excluding amortisation of acquired intangibles, capex_pct_revenue includes the capex needed just to keep the business the same size, and working_capital_pct_revenue is working capital as a share of revenue, applied to the growth in revenue. The calculator works out free cash flow before interest from these, so don't add interest back anywhere |

Put only the JSON object between a line that contains only <<<BEGIN OUTPUT>>> and a line that contains only <<<END OUTPUT>>>.
