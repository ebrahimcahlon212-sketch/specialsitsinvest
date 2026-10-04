# Fill in section 11 from the IBKR account

Use the Interactive Brokers tools to read the account. Read only. Do not create orders or trade instructions of any kind.

1. Read the final report listed under "Files for this run".
2. From IBKR, get net liquidation value, excess liquidity, margin in use and current positions. Get current quotes for every ticker in the report and for any hedge instrument it mentions.
3. Note any existing exposure to these names or to closely linked ones, such as the acquirer, the parent, the spun-off company or peers the report mentions.
4. Using the report's downside case, work out positions at 1%, 2%, 3% and 5% of net liquidation value. For each size show the number of shares, the cost, the loss if the downside case happens (in dollars and as a percentage of net liquidation value) and, if IBKR provides volume, the position as a share of average daily volume.
5. If the price has moved since the report was written, recompute the spread and the annualized return at the current price.
6. If the trade needs a hedge, for example shorting the acquirer's stock in a stock deal, show the hedge size and, if IBKR provides it, whether shares are available to borrow and at what rate.
7. Suggest a size range and explain it in a few sentences. Base it on the report's downside case and on concentration with existing positions.

If you cannot reach the IBKR tools, say so in the section and stop.

Output only section 11, starting with the heading "## 11. Position and sizing", between the output markers.
