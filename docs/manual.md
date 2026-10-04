# Special situations research kit, full manual

This kit has all three models work from the same primary documents and check each other's work. The result is one report with every number tied to a page. Each model runs through its company's own command-line tool, signed in with your subscription, so nothing is billed per token.

## How a run works

1. Prep. The filings are converted so every model sees the same thing. Each PDF page becomes a text file and an image, and a search file tags every line with its page number.
2. Draft. One model (Claude by default) writes the report from a fixed template and the checklist for the situation type.
3. Review. The other two models check the draft against the cited pages at the same time. They report errors, unsupported claims, missing items and their own math, and make the case against the thesis.
4. Final. The drafting model rechecks every disputed point against the page and fixes the report. The final version lists each disagreement and how it was settled.

A separate sizing step then has Claude Code read your IBKR account and fill in the position sizing section.

Before the draft, a map step sorts every section of every document into material and generic, so the models read what matters in full and skim the boilerplate. See What the models read below.

There is also a finder, which checks the SEC's new filings for situations worth a look and ranks them on one page. See Finding situations below.

## Why it uses the official command-line tools

A subscription only covers the company's own apps. Anthropic's terms say a Claude Pro or Max login may only be used in Claude Code and Claude.ai, so third-party chat apps cannot use it. This kit calls each company's official tool directly, which keeps each model on its own plan. run.sh also hides any API keys in your shell from these tools so none of them quietly switches to pay-per-token billing.

## What you need

- A Claude plan that includes Claude Code (Pro or Max) and a ChatGPT plan that includes Codex (Plus or Pro).
- A Kimi Code plan. Kimi K3 needs the Plus plan or above, or Moderato or above on the older plans. Lower plans get kimi-for-coding, which Moonshot describes as close to K3.
- A Mac or Linux computer, or Windows with WSL (see On Windows below).
- poppler for PDF conversion and python3. tesseract is optional and adds OCR for scanned filings.

## On Windows

The kit runs inside WSL, a free part of Windows that adds an Ubuntu Linux window. OpenAI recommends it for running Codex on Windows, and the other two tools install there with their Linux instructions. Your files and your browser stay in Windows.

1. Right-click the Start button and choose Terminal (Admin) or Windows PowerShell (Admin). Type `wsl --install` and press Enter, then restart when it asks. If it reports that virtualization is turned off, that setting has to be switched on in the PC's firmware first.
2. After the restart, Ubuntu opens and asks you to choose a username and password. The password stays invisible while you type, which is normal.
3. In the Ubuntu window, paste these lines one at a time and press Enter after each. They install the PDF tools and a recent Node.js, which Codex needs.

```
sudo apt update
sudo apt install -y poppler-utils tesseract-ocr python3 unzip curl
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
```

4. Install the three tools, then close the Ubuntu window and open it again from the Start menu.

```
curl -fsSL https://claude.ai/install.sh | bash
sudo npm install -g @openai/codex
curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash
```

5. Download the kit's zip in Windows as usual, then copy it into Ubuntu and unpack it. Replace YOURNAME with the name of your folder under C:\Users.

```
cp /mnt/c/Users/YOURNAME/Downloads/special-sits-kit.zip ~
cd ~ && unzip special-sits-kit.zip && cd special-sits-kit
```

6. Continue with the sign-in and IBKR steps in the next section, skipping its install commands. When a tool shows a link instead of opening a browser, copy the link into your browser. If the IBKR login doesn't come back to Ubuntu, run `claude mcp login ibkr --no-browser` and follow what it prints.

Day to day, open Ubuntu from the Start menu and type `cd ~/special-sits-kit` before using the commands below. `./run.sh new NAME` opens the new deal's filings folder in File Explorer so you can drag the PDFs in, and the viewer opens in your normal browser.

## One-time setup

Install the tools.

```
curl -fsSL https://claude.ai/install.sh | bash                 # Claude Code
npm install -g @openai/codex                                   # Codex (or brew install --cask codex)
curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash   # Kimi Code
brew install poppler tesseract                                 # macOS
sudo apt install poppler-utils tesseract-ocr python3           # Ubuntu or Debian
```

Sign in with your subscriptions, not API keys.

```
claude          # then type /login and choose your Claude subscription
codex login     # choose Sign in with ChatGPT
kimi login      # sign in with your Kimi account
```

Open each of the three tools once inside the kit folder and accept any prompt asking whether you trust the folder. Then quit.

Connect IBKR to Claude Code. A browser window opens for the IBKR login.

```
claude mcp add --transport http --scope user ibkr https://api.ibkr.com/v1/api/mcp-public
claude mcp login ibkr
```

Check everything.

```
chmod +x run.sh
./run.sh doctor
```

## Running a deal

```
./run.sh new acme-merger
```

Put the filings in `deals/acme-merger/filings`. If IBKR is connected, the run fills in current prices in `deals/acme-merger/market.md` by itself, and otherwise you type them in. Then run the pipeline, and the sizing step when you want it.

```
./run.sh acme-merger
./run.sh acme-merger size
```

Everything lands in `deals/acme-merger/out`.

| File | What it is |
|---|---|
| report.md | The final report |
| report-with-sizing.md | The final report with position sizing from IBKR |
| draft.md | The first draft |
| review-codex.md and review-kimi.md | The reviews (named after whichever models reviewed) |
| viewer.html | Everything above in one page, with citations that open the cited page |
| logs/ | Each tool's progress output, for when something goes wrong |
| prompts/ | The exact prompt each step sent |

You can rerun any single step, for example `./run.sh acme-merger final` after updating prices in market.md.

For a stock-for-stock merger, attach both companies so the report gets both sets of filings and both prices. Give each a role, and the kit gathers their filings and prices them from IBKR.

```
./run.sh new centerspace
./run.sh add-company centerspace IRT acquirer
./run.sh add-company centerspace CSR target
./run.sh centerspace
```

## What the models read

The map step splits every document into sections at its headings and scores each one two ways. The first is how specific it is, meaning its dollar amounts, dates and checklist terms. The second is how much of its wording also appears in other companies' filings. Sections come out labelled material, standard with changes, supporting or generic, and Claude then turns that into a document map that lists where each checklist item sits and flags terms that look unusual for this kind of deal. The draft and review steps read everything the map marks as material from start to finish.

Standard with changes is the label to watch. It means a clause mostly matches the usual wording but something was added or altered, which is often where the deal-specific catch is.

Nothing is thrown away. Generic sections are still searchable, and the reviewers are told to read anything material the draft skipped. The comparison library starts small, so at first generic wording is judged mainly by section titles. It grows with every deal you run, every morning's finder excerpts and a few recent peer filings downloaded for each new deal, and it gets sharper as it grows. The map shows up as its own tab in the viewer.

## Finding situations

The finder reads the SEC's list of new filings and picks out the ones that signal a special situation. Those are merger agreements and merger proxies, tender offers, spin-off registrations and bankruptcy filings. It also watches for early signals that often come before a deal or a restructuring, such as a new activist stake, a review of strategic alternatives, a lender forbearance, a restructuring support agreement or a new shareholder rights plan. A model reads an excerpt of each one and writes a short card, and the cards are ranked on one page.

The SEC asks every automated visitor for a name and email, so give it yours once.

```
./run.sh contact "Your Name you@example.com"
```

Then run the finder whenever you want the latest.

```
./run.sh find
```

The shortlist opens in your browser, and the newest one is always at `finder/latest.html`. Each card has the terms, the key dates, a spread when there is a price, a reason it might be mispriced and what to watch out for. The score is a reading order, not a verdict.

To study one properly, copy the command on its card, for example `./run.sh promote PDNT-8K`. That makes a deal folder with the filing's documents and fills in the price. From then on the finder saves every new filing from that company into the deal's folder, and the shortlist tells you when there's something new. To follow a deal you started yourself, use `./run.sh track acme-merger ACME`.

A few details.

- The first run looks back one day. `./run.sh find 7` looks back a week, and it never goes back more than 10 days.
- Only situations involving a listed company are kept, plus spin-offs, since the new company isn't listed yet.
- Once IBKR is connected to Claude Code, prices come from your IBKR account, live or delayed depending on your market data subscriptions. Anything IBKR can't price, and everything before IBKR is connected, comes from Stooq, a free source of delayed quotes. `FINDER_PRICES=stooq` always uses Stooq, and `FINDER_PRICES=off` skips prices.
- `FINDER_MODELS="claude codex kimi"` spreads the reading across all three plans instead of using Claude alone.
- If some cards are missing, usually because a model hit its usage limit, `./run.sh retriage` writes just those. Put a different model in front of it to use another plan, for example `FINDER_MODELS=kimi ./run.sh retriage`.

To let it work while you're away, run a hunt. It runs the finder, picks the best new cards (score 4 or more, leaving out early signals and companies you already have a deal for) and writes a full report on each. The shortlist then shows an Open the full report button on those cards.

```
./run.sh hunt
HUNT_MAX=3 ./run.sh hunt           # full reports on up to three cards instead of two
HUNT_EVERY_HOURS=3 ./run.sh hunt   # repeat every three hours until you press Ctrl+C
```

Each full report uses a good share of your plans' limits, which is why the default is two per hunt. Before leaving it running, set Windows not to sleep while plugged in, keep the Ubuntu window open, and log out of the IBKR desktop app so it doesn't take over the IBKR session the kit uses for prices.

To run it every weekday morning on Windows, paste this into PowerShell (not Ubuntu). The PC has to be on and you have to be signed in at that time.

```
$action = New-ScheduledTaskAction -Execute "wsl.exe" -Argument '-e bash -lc "cd ~/special-sits-kit && ./run.sh find >> finder/finder.log 2>&1; ./run.sh ledger sync >> finder/finder.log 2>&1"'
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 7:30am
Register-ScheduledTask -TaskName "Special sits finder" -Action $action -Trigger $trigger
```

On a Mac, run `crontab -e` and add this line.

```
30 7 * * 1-5 cd ~/special-sits-kit && /bin/bash -lc './run.sh find; ./run.sh ledger sync' >> finder/finder.log 2>&1
```

## UK situations

Every finder run and hunt also reads the Takeover Panel's Disclosure Table, the official list of every UK company in an offer period. A company that is new to the list, or has a new bidder or deadline, gets a card. The card shows the stage, for example a possible offer or a firm offer, and the Rule 2.6 deadline, which is the date a possible bidder must make a firm offer or walk away. The table also shows whether an offer is likely to be all cash.

To write those cards, Claude reads the offer announcements, and for this step alone it may browse, but only official sources such as RNS announcements, company websites and the Panel. It has no access to your IBKR account while browsing. Prices come from IBKR by ISIN in a separate step. Buying Main Market shares in UK companies costs 0.5% stamp duty while AIM shares are exempt, and the cards allow for it.

The first run finds every company already on the list, so it writes cards for the 12 with the nearest deadlines and firm offers first, and the rest follow on later runs. `FINDER_UK_MAX` changes that number and `FINDER_UK=off` skips the UK step.

Full reports collect documents from EDGAR, which doesn't hold UK filings, so for a UK deal make the folder yourself and put the key PDFs in it, such as the Rule 2.7 announcement and the scheme document. Then run it as usual.

```
./run.sh new tribal
./run.sh tribal
```

## A verifiable trade record

The ledger keeps a record of your trades and research that can't be edited without it showing. Every entry carries a fingerprint (a SHA-256 hash) of the entry before it, so changing or deleting anything breaks every fingerprint after it. Once a day the latest fingerprint is timestamped with OpenTimestamps, a free service that records it in the Bitcoin blockchain, so anyone can later confirm the ledger existed in exactly that form on that date. Every final report and finder shortlist is fingerprinted automatically when it's created, which lets you prove the research came before the trade.

Setup, once.

1. Open a separate IBKR account just for this strategy. The ledger can prove nothing was changed, but only a dedicated account's statements prove nothing was left out.
2. In IBKR's Client Portal, open Performance & Reports, then Flex Queries. Create an Activity Flex Query with the Trades section (execution level) and the Open Positions section, in XML format, covering the last 30 days. Note its Query ID.
3. On the same page, turn on the Flex Web Service and generate a token. Tokens expire, so note the date and generate a new one before then.
4. Give the kit the token and the query ID, and install the OpenTimestamps client. On Ubuntu that's the first two lines below, then close and reopen the window. On a Mac, use `brew install pipx` instead of the apt line.

```
sudo apt install -y pipx
pipx install opentimestamps-client
./run.sh ledger setup YOUR_TOKEN YOUR_QUERY_ID
```

Day to day.

```
./run.sh ledger sync      # records new trades from IBKR and stamps the ledger
./run.sh ledger add FILE "September statement"   # fingerprints any file, such as IBKR's monthly statement PDF
./run.sh ledger verify    # rechecks every fingerprint and timestamp
./run.sh ledger pnl       # writes realized and unrealized P&L to ledger/pnl.md
```

The daily stamp covers everything recorded up to that point. When the timing of a thesis matters, run `./run.sh ledger stamp --force` before placing the trade, so the research is anchored before the order exists.

Download IBKR's official monthly statement each month and add it with `ledger add`, since the statement is the record an auditor would rely on. To let someone else check a timestamp, send them a file from `ledger/stamps` with its `.ots` proof and they can drop both into opentimestamps.org. Back up the whole `ledger` folder somewhere else as well, because the proofs only help if the files survive. The Flex token is stored in `settings.env`, readable only by your user, so leave that file out if you ever share the kit.

## Choosing the IBKR account

If your IBKR login has more than one account, tell the kit which one to size against and what kind of account it is. The account ID starts with U and appears in the account menu at the top right of IBKR. The note is passed to every report step, so the models won't recommend trades the account can't make.

```
echo 'IBKR_ACCOUNT="U1234567"' >> settings.env
echo 'IBKR_ACCOUNT_NOTE="UK Stocks and Shares ISA. No short selling or margin."' >> settings.env
```

For the ledger, build the Flex Query for that same account only.

To have the finder score cards for you rather than a generic investor, describe yourself in one line. It then marks trades your account can't make, works out the return per year to the payout date, flags odd-lot offers you can afford, and sorts cards with the same score by return per year.

```
echo 'INVESTOR_PROFILE="About 450 dollars to invest. Wants payoffs within 12 months. Can buy odd lots of cheaper stocks."' >> settings.env
```

## Tax

Tell the kit your tax position and it allows for it. The calculator then counts US dividends after the tax withheld at source, and for company buybacks and SPAC redemptions it shows what happens if the payment counts as a dividend and tax is withheld from the whole of it. The models read each offer document's tax section for non-US holders, and the finder marks over-the-counter shares, which generally can't go in an ISA. For a UK resident with a W-8BEN investing through an ISA, the two lines are these.

```
echo 'TAX_PROFILE="UK resident with a W-8BEN on file, investing through a Stocks and Shares ISA, so no UK tax on gains or income. US dividends have 15% withheld and US capital gains are not taxed."' >> settings.env
echo 'US_DIVIDEND_TAX_PCT="15"' >> settings.env
```

This is general, not tax advice, so check anything that matters with HMRC's guidance or an adviser.

## Numbers and prices

The models don't do the arithmetic. After the reviews, a terms step pulls the deal's inputs into `out/terms.json`, such as the offer price, the exchange ratio, dates, dividends and probabilities. Python then works out the spread, the return per year for each closing date, the chance of closing the market implies, the probability-weighted result and break-even prices, plus proration scenarios for partial tenders, CVR payoffs and SPAC trust discounts. The final report quotes those figures and includes them in a section called Numbers from the calculator. Cards on the shortlist work the same way.

Prices come from IBKR when a step runs. Before the US market opens at 14:30 UK time that means yesterday's close, because thin pre-market trades are ignored. To refresh later:

```
./run.sh prices                          # every card on the latest shortlist and every deal
./run.sh centerspace prices              # one deal
PRICES_EVERY_MINUTES=30 ./run.sh prices  # keep refreshing until you press Ctrl+C
```

A refresh is one short request to IBKR through Claude, with no model reading documents, so it costs very little. The calculated figures change and the written text stays as it was.

## Fundamentals report

The deal report asks whether a deal closes. The fundamentals report asks what the business is worth on its own, which decides your downside if a bidder walks away and whether an offer is fair.

```
./run.sh ashtead fundamentals
```

It works from first principles. It covers what the business does, its revenue written as an equation of its drivers, unit economics, five years of financials with adjusted figures reconciled to statutory ones, cash conversion, the balance sheet, competitive position, risks, management and ownership, and a standalone value range. Claude drafts it, Codex and Kimi review it hard, Python does the valuation (multiples at each price and a discounted cash flow for each case), and Claude writes the final version. It appears as a Fundamentals tab in the viewer.

The valuation builds free cash flow from its parts, meaning operating profit after tax, plus depreciation, minus capex and the working capital growth needs, so nothing is counted twice. It also shows how the value moves with the discount rate and long-term growth, and the yearly return a buyer would earn at each price if a case comes true. `./run.sh NAME revalue` redoes the valuation and the final report without paying for a new draft and reviews.

For a UK possible offer, the deal report weighs the signals that usually predict whether the bidder makes a firm offer by the deadline, such as the board's language, due diligence access, the bidder's price path, financing, large shareholders and extensions. Its calculator section shows the chance of completion each entry price needs to break even.

## UK events and liquidations

Each finder run also looks for UK special situations beyond takeovers, meaning investment trust tender offers, wind-downs, returns of capital, liquidations with a cash payout, demergers, compulsory acquisitions and deeply discounted rights issues. Claude searches the week's regulatory announcements, reads each one and writes a card, in a step that can browse but has no access to your IBKR account. Prices come from IBKR afterwards. For a tender that buys only part of each holding, the card shows the return if every holder tenders and if half do, with the rest of your shares kept at today's price. They appear in a UK events section, and `./run.sh promote` works on their IDs too. `FINDER_UK_EVENTS=off` skips the step.

On the US side, the finder also searches for plans of liquidation or dissolution and for companies emerging from bankruptcy with new shares.

## Decisions, trade rate and watching

Log every situation you look at, with your decision and the reason. Decisions are also added to the ledger's hash chain, so the record can't be quietly rewritten.

```
./run.sh decide ashtead pass "fairly priced at 528p, downside too big"
./run.sh decide UKE-SDCLENERGY-TND watch "wait for the discount to widen"
./run.sh resolve ashtead completed "Ember's firm offer closed at 615p"
./run.sh journal
```

The journal shows how many cards were screened and situations researched, your trade rate, and how the tool's probabilities compared with what actually happened. It also shows how the situations you passed on turned out. If many of them complete anyway, you and the tool are being too cautious, and if they fail, the caution is earning its keep.

`./run.sh watch` refreshes prices, then shows every open deal's spread, return per year, expected return, and the market's odds against the report's. It flags any deal whose return per year passes `WATCH_MIN_RETURN` (20% by default) with a positive expected value, or where the market's odds have fallen well below the report's estimate. That is how you catch a spread that widens on a scare.

`./run.sh insiders` reads the last few days of Form 4 filings and lists smaller US companies where directors and officers bought shares on the open market with their own money, most buyers first. It needs no model, so it costs nothing but time, and the list also appears on the shortlist page.

## Looking further back

A daily run looks at the days since the last run, up to 10. For a one-off catch-up, ask for up to 45 days and raise the limits for that run. Spreading the cards across all three plans keeps any one of them from running out.

```
FINDER_MAX=150 FINDER_UK_MAX=40 FINDER_UK_EVENTS_DAYS=30 FINDER_UK_EVENTS_MAX=30 FINDER_MODELS="codex kimi claude" ./run.sh find 30
```

Filings already carded in earlier runs are skipped, and prices are fetched fresh, so older situations show today's spreads. If a plan hits its limit partway, `./run.sh retriage` finishes the missing cards later.

## Predictions and sizing

Log your own probability for any question, with the market's and the tool's where you have them, and settle it when the answer is known. The kit scores all three, so over time you'll see whether your calls beat the market's.

```
./run.sh predict "Ember makes a firm offer for Ashtead by 21 October 2026" 70 --market 68 --by 2026-10-21 --deal ashtead
./run.sh predict "Hormuz traffic back to normal by 31 December 2026" 20 --by 2026-12-31
./run.sh settle P001 yes "Rule 2.7 announcement on 15 October"
./run.sh predictions
```

If your view changes, log a new prediction on the same question rather than editing the old one. Only your latest prediction on each question is scored, and earlier ones show as updated, so the record shows how your thinking moved. A duplicate logged by mistake can be withdrawn with `./run.sh withdraw P004 "logged twice"`, which keeps it in the tamper-proof record but leaves it out of the scores.

`./run.sh NAME sizecalc` works out how much to put into a deal. It takes the gain if the deal completes and the loss if it fails, and your own logged prediction for that deal, or else the report's estimate. The Kelly formula gives the share of the account that grows it fastest over many bets, the kit uses half of it because the odds are estimates, and then it applies your ISA rules. If the expected return isn't positive, it suggests no position and says what chance would change that. The sizing step uses the same numbers as its upper limit. Set the rules in settings.env.

```
echo 'ISA_VALUE="500"' >> settings.env
echo 'MAX_POSITION_PCT="25"' >> settings.env
echo 'CASH_RESERVE_PCT="20"' >> settings.env
echo 'TRADE_COST_GBP="3"' >> settings.env
```

## Angles and ideas

`./run.sh NAME angles` reads a deal's documents adversarially, the way a sceptical specialist would, for anything that could create value for a small holder. That includes proration and odd-lot rules, record dates, vote thresholds, conditions and fees, adjustments to the payout, tax treatment and drafting errors. For each angle it says how much it could be worth, whether you could use it in your account, whether it's allowed, and whether it's a known technique or looks unusual. Add `--web` to check angles against how they've played out elsewhere. It appears as an Angles tab in the viewer.

`./run.sh idea "..."` saves an idea in seconds. Add `--check` to test it properly with web research. The check restates the idea as a mechanism, looks for anyone who has done it before and how it turned out, and if nobody has, reasons from first principles about whether it could work rather than dismissing it. It checks the legal position, works out what it would pay at your size and lists cheap ways to test it. When the legal position is uncertain in a way that matters, it writes a one-page brief you can send to a solicitor. `--deal NAME` points the check at a deal's documents, and `./run.sh ideas` lists every idea with its verdict.

```
./run.sh ashtead angles --web
./run.sh idea "buy just before the record date in schemes where holders keep the dividend" --check
./run.sh ideas
```

Ideas that rely on inside information, misleading the market or manipulating a price or a vote are ruled out, and the check says so plainly and suggests a legitimate version where one exists.

## A record that proves itself

Every decision, outcome, prediction and idea goes into the ledger, and four layers make the record provable.

- **A hash chain.** Each entry contains the fingerprint of the one before it, so changing any past entry breaks every fingerprint after it, and `./run.sh ledger verify` says exactly where.
- **Bitcoin timestamps.** Straight after each new entry, the chain's latest fingerprint is anchored in Bitcoin through OpenTimestamps. That proves the record existed in exactly that state at that time, so nobody can write a history after the fact. Only the fingerprint leaves your computer, and your decisions stay private.
- **Your signature.** `./run.sh ledger keygen "Your Name"` makes a signing key that only you hold, and every stamp is then signed with it, proving the record came from you. The public half goes in `ledger/allowed_signers` so anyone can check. Email yourself the fingerprint it prints, which gives an independent, dated record of which key is yours.
- **Copies.** A tamper-evident record can still be deleted, so keep a copy of the ledger folder, and a private backup of your signing key, somewhere else.

To switch on the timestamps and the signature, install the OpenTimestamps client and make your key.

```
sudo apt install -y pipx && pipx install opentimestamps-client && pipx ensurepath
./run.sh ledger keygen "Your Name"
```

Close and reopen Ubuntu after the first line so the `ots` command is found. Anyone can check a stamp independently by dropping a `head-*.txt` file and its `.ots` file into opentimestamps.org.

## Store overlaps for retail mergers

When two chains merge, the CMA draws a catchment around each store, counts the rival brands inside it, and usually asks for a store to be sold wherever too few would be left. `./run.sh NAME overlap` does a rough version of that screen with OpenStreetMap, which tags UK shops by brand, so Python fetches every matching shop in one request with no model involved.

```
./run.sh ramsdens overlap "Ramsdens" "H&T|H & T" --shop pawnbroker --radius 3 --label-b "H&T"
```

For exact locations, point it at each chain's own store list. Every UK postcode on the page is read and located with postcodes.io, a free service, while rival shops still come from OpenStreetMap.

```
./run.sh ramsdens overlap "Ramsdens" "H&T|H & T" --shop pawnbroker --radius 3 --label-b "H&T" --list-a "https://www.ramsdenspawnbrokers.co.uk/stores" --list-b "https://www.handt.co.uk/store-finder"
```

If a store page builds its list with scripts, fewer stores will be located than the chain claims. Open the page in your browser, let the full list load, save it with Ctrl+S, and pass the saved file instead, for example `--list-a /mnt/c/Users/YOUR-NAME/Downloads/stores.html`. A map of every store, with the overlaps in red, is written to out/overlap-map.html.

Rival shops come from OpenStreetMap, which misses many independents and can be busy. `--rival "Name=web address or file"` adds a rival chain from its own store list in the same way, and can be given more than once. If no rivals load at all, the run says so and doesn't report brand counts, since every overlap would wrongly look like two brands becoming one.

It lists every area where both chains have a store within the radius, how many brands are there before and after, and how many areas would fail the screens the CMA commonly uses. Compare the number of stores found with the chains' own counts, since a shop missing from the map means an overlap missing from the results. Straight-line distance stands in for the drive times the CMA uses, so it's worth running a tighter radius too. The results appear in an Overlap tab, and the ask and angles commands read them.

## Competition assessment and folding research into the report

Proximity only shows where two chains meet. `./run.sh NAME competition` judges how many of those areas could worry the CMA. It reads what the companies themselves say about competitors in their annual reports and scheme document, looks for CMA precedent on how the market has been defined, sets out a few competitor definitions from narrow to broad, and checks the web for rival shops near the closest overlap areas. It then counts the areas that would fail each screen under each definition, as ranges with the assumptions stated. It needs the overlap check first, checks up to 20 areas by default, and `COMPETITION_AREAS=30` changes that. For pawnbroking it starts from the OFT's 2007 decision on Albemarle & Bond buying Herbert Brown, defines rivals by the service offered rather than the shop's label, and uses the one-mile radius from that decision as its starting point.

The closest overlaps are the worst cases, so their results can't be applied to every area. `COMPETITION_SAMPLE=random ./run.sh NAME competition` checks a random sample from the rest instead, skipping the 12 closest if they've already been checked. Python splits the remaining areas into equal bands by distance and picks one at random from each, so the sample covers near and far overlaps alike. After the web checks, Python works out the share of sampled areas that fail each screen, with a 90% margin of error, scales it up to all the areas and adds the closest ones exactly. The result appears in an Estimate tab, and `./run.sh NAME competition estimate` recalculates it. `COMPETITION_AREAS` sets the sample size, 12 by default, where a larger sample gives a narrower range. The sample is fixed by a seed, so rerunning picks the same areas. Choosing a different `COMPETITION_SEED` after seeing a result you dislike would bias the estimate, so decide on the sample before you look.

`./run.sh NAME update` now also revises the full report when new research has arrived since it was written, such as an overlap analysis, a competition assessment, a fundamentals report or answers to questions, even with no new documents.

## Choosing which model does what

Each job can go to whichever plan has the most room. To lean on Codex and save your Claude allowance, add these to settings.env.

```
DRAFTER="codex"
MAPPER="codex"
ASK_MODEL="codex"
WEB_MODEL="codex"
FINDER_MODELS="codex"
```

The final report follows the drafter, and the reviews then go to Claude and Kimi, since reviews are done by the models that didn't draft. `REVIEWERS="kimi"` makes Kimi the only reviewer if you want to save Claude further. The steps that read your IBKR account stay on Claude, because that's where the IBKR connection is set up, but they're short. Kimi can't search the web, so WEB_MODEL is claude or codex. `./run.sh doctor` shows which model does each job.

Codex turns on web search with `-c tools.web_search=true` by default. If your Codex version uses a different option, such as `--search`, set `CODEX_WEB_FLAGS="--search"`. A quick way to check it works is a small web question, such as `./run.sh ramsdens ask --web "What is the latest announcement from Ramsdens?"`, and seeing whether the answer cites web pages.

## Dated catalysts

`./run.sh catalysts` builds a calendar of undervalued companies with a dated event that should close the gap. A browsing model, which can run on Codex, searches announcements, reports, AIC data and index notices for trust continuation votes and tender triggers, sale processes with offer deadlines, court and arbitration rulings, refinancing deadlines, forced selling from index changes and moves to AIM, and European squeeze-outs. Each comes with a value anchor, such as asset value, a claim or a minimum buy-out price, and the single question that decides it.

Python keeps every catalyst across runs, prices the companies through IBKR, and works out the discount to the anchor, the days to the date and, where the anchor is actually paid on the date, the yearly return. The page ranks them by score, discount and how soon the date falls. `./run.sh catalysts prices` refreshes prices without searching again, `./run.sh catalysts 6` narrows the window to six months, and `CATALYSTS_EUROPE=off` keeps it to the UK. `./run.sh promote CAT-...` turns one into a deal folder, gathering from EDGAR for US companies and from official websites otherwise, and `./run.sh NAME fundamentals` then tests the value anchor.

## Biotech catalysts

US-listed companies state their FDA decision dates, often called PDUFA dates, in their filings. `./run.sh biotech` searches the last 120 days of filings for those dates, keeps the ones still ahead, and works out from the SEC's own data each company's cash, monthly burn and months of runway, plus market value and cash per share once IBKR supplies prices. Smaller companies with a decision in the next nine months get cards, written from excerpts of the filing, covering the drug, the indication, whether it's a biologic or a cell therapy, who manufactures it, how much of the company rides on it and the red flags. The calendar opens as a page in the day's finder folder.

`./run.sh promote BIO-TICKER` turns a decision into a deal folder with its filings, and `./run.sh NAME biotech` runs the deep dive. That covers the evidence, the FDA's likely concerns, base rates, money, and manufacturing readiness, meaning who makes the product, where, the sites' inspection history and any process changes, since many rejections cite manufacturing rather than efficacy. It ends with the decision date, the chance of approval, and the likely price if approved and if rejected. Those three numbers feed the usual calculator, so sizecalc, watch and the journal work as they do for deals, and the result appears in an FDA decision tab.

`BIO_MONTHS`, `BIO_MAX_CAP` and `BIO_HORIZON_MONTHS` change which decisions get cards and how far ahead the calendar looks, and `BIO_MODEL` picks the model for the cards.

## Page images for HTML filings

PDF filings show the cited page as an image under its text in the viewer. HTML filings, such as most SEC 10-Ks and 10-Qs, have no pages of their own, so when WeasyPrint is installed (`sudo apt install -y weasyprint`), preparation also prints each HTML filing to pages. The viewer then matches each cited line to the printed page it falls on, by its wording, and shows that page under the text. Filings prepared before WeasyPrint was installed are printed the next time the deal is prepared, for example with `./run.sh NAME prep`. `HTML_PAGES=off` turns this off.

## Learning from feedback

`knowledge/research-standards.md` holds rules learned from independent critiques, such as starting probabilities from reference classes, splitting failure outcomes by type, treating the event-day price as rigorously as the probability, and preferring primary sources. Every step is told to follow it, and every check tests the work against it and lists each breach.

When you get feedback from anyone, save it as a text file and run `./run.sh feedback FILE NAME`. It copies the feedback into that deal's folder, so the deal's next steps read it, then turns it into general rules and adds them to the standards with their source and date, skipping anything already covered. Leave out NAME for feedback that isn't about one deal.

## Independent checks of FDA deep dives

The full report on a deal is drafted by one model and reviewed by the others, but the FDA deep dive and the questions run on a single model. `./run.sh NAME check` closes that gap. The models that did not write the deep dive, Claude and Kimi with the default settings, each check it and every saved answer against the filings, side by side. They list factual errors, recompute the key numbers, flag overstated claims and missing risks, give their own probability range, and say whether anything should change the decision. They do not browse, so claims resting on web sources they cannot see are marked unverified. The checks appear in the viewer as "Check by Claude" and "Check by Kimi". They run automatically at the end of every `./run.sh NAME biotech` deep dive, and `BIO_CHECK=off` skips them for a run.

## Knowledge notebook

The models remember nothing between runs, so the kit keeps its own memory as plain notes in `knowledge/`, one per topic, with an index. Every step is told where the notebook is and reads the notes that matter for its task, treating them as starting points to check rather than facts. The first run creates it from a starting set covering UK merger control, the Takeover Code, deal arithmetic, FDA manufacturing, wind-down funds and data pitfalls.

`./run.sh NAME remember` reads a deal's research and answers, picks out up to ten lessons worth carrying into future deals, and adds them to the right notes with their sources, dates and confidence. It never overwrites earlier lessons, and corrections are added as corrections, so the history stays traceable. `./run.sh knowledge` shows the notebook, and you can edit the notes directly, since they're ordinary Markdown. The notebook stays on your machine and is left out of GitHub.

## Asking questions

Ask anything about a deal in plain English. The answer comes from the deal's documents with a citation for every fact, starts with a direct answer and ends with what it means for the investment. Every answer is saved to a Questions tab in the viewer.

```
./run.sh ashtead ask "Which Middle East countries does Ashtead work in, and how much revenue comes from each?"
./run.sh ashtead ask --web "How exposed is Ashtead's Middle East work to disruption near the Strait of Hormuz?"
```

Add --web for questions the filings can't answer, such as current events. That step can search the web but has no access to your IBKR account, and it gives each web source with its address and date.

## UK deals

Promote works for UK cards too, using the ID on the card.

```
./run.sh promote UK-ASHTEADTECHNOL ashtead
./run.sh ashtead fundamentals
./run.sh ashtead
```

UK filings aren't on EDGAR, so Claude finds the company's official documents, such as annual reports, results and offer announcements, on its website and RNS. That step can browse but has no access to your IBKR account, and Python does the downloading. Anything that fails to download can be saved into the deal's filings folder by hand. Prices for UK deals come from IBKR using the ISIN.

## Updating a report

When a tracked deal gets new filings, update it instead of starting again. The update reads the previous report and only the new documents, adds a section called What changed since the last report and redoes the numbers. The previous version is kept in `out/history`. If nothing new has arrived, it just refreshes prices and numbers.

```
./run.sh centerspace update
```

## Reading the report

Every report opens with a section called In plain English, written for someone new to special situations. It says what is happening, how you could make money and how you could lose it, with the real numbers, and it has a table of the dates that matter, including the last day to act. For a report made before this section existed, `./run.sh NAME explain` adds it.

The final step also builds `out/viewer.html`, one file you can open in any browser. Tapping a citation opens the cited page with its text underneath, and figures from the claim that appear on the page are highlighted. A citation turns amber and says check when none of the claim's dollar amounts, dates or large numbers appear on the cited page. It is struck through when the page does not exist. The Next to check button steps through those.

The page images are inside the file, so you can send it to your phone and open it in a browser there. A file preview that doesn't run scripts still works, but citations then jump to the cited pages at the end instead of opening a panel.

To see it before running anything, try the sample deal. Its company and filings are made up.

```
./run.sh halvern view
```

## Getting the filings

For a deal that came from the finder, or one you've attached to a company with `./run.sh track NAME TICKER`, the kit collects the documents itself. `./run.sh NAME gather` reads the company's filing history, keeps the forms that matter for the situation type and downloads the main document and key exhibits of each, such as the merger agreement, the information statement and the tax matters agreement. For documents that get amended, only the latest version of each part is kept, and older copies move to `filings/superseded` so the models never read outdated terms. Promoting a card runs this automatically, and the finder repeats it whenever a tracked company files something new.

EDGAR serves most filings as HTML. The kit reads HTML as text, but saving the filing as a PDF from your browser's print dialog keeps page images, so the models can check tables visually and cite pages. Bankruptcy court documents aren't on EDGAR, so download the key ones yourself from the claims agent's website for the case, usually free PDFs. Short file names help, because they become the names used in citations, for example `merger_proxy.pdf` or `8k_2026_09_01.pdf`.

## Choosing models

Put these in front of the command.

| Setting | Example | Effect |
|---|---|---|
| DRAFTER | `DRAFTER=codex ./run.sh acme-merger` | Who writes the draft. The other two review it |
| FINALIZER | `FINALIZER=claude` | Who writes the final report. Defaults to the drafter |
| KIMI_MODEL | `KIMI_MODEL=kimi-code/k3-256k` | Kimi model. k3 with the 1M context uses about twice the quota of k3-256k |
| CLAUDE_MODEL | `CLAUDE_MODEL=opus` | Claude model |
| CODEX_MODEL | `CODEX_MODEL=gpt-6-astra` | Codex model. Use the name Codex shows under /model |
| CODEX_EFFORT | `CODEX_EFFORT=xhigh` | Codex reasoning effort (default high) |

If the Kimi model name is rejected, open `kimi`, type `/model` and use the name it shows.

## Usage limits

Each step uses your plan's allowance, and long filings with many page images use more. A 300-page merger proxy can take a while per step. If a model hits its limit, rerun that step after the limit resets, for example `./run.sh acme-merger review`.

## Updating the kit

Download the new zip, then run one command. It finds the newest kit zip in your Windows Downloads or Desktop, or your Linux home folder, checks it's newer than what you have and installs only the program files. Your settings, deals, finder history, ledger and library are never touched.

```
./run.sh upgrade
./run.sh version            # shows which version you have
./run.sh upgrade --rollback # goes back to the version before the last upgrade
```

It chooses by the version number inside each zip rather than the file date, so an old zip lying around can't be installed by mistake. Each upgrade keeps the program files it replaced in `.backups`.

## If something breaks

Check the log for the step in `out/logs`. The command-line tools change their flags from time to time, and every call is in one short function per tool near the top of run.sh, so a fix usually means editing one line there. This kit was written against each tool's documentation as of September 2026 and tested with stand-ins for the three tools, not against live accounts, so run a small filing first.

## Safety

The finder only reads public SEC data and delayed quotes, and it sends the SEC the name and email you gave it, as the SEC requires. Claude Code runs with read-only tools and Codex runs in a read-only sandbox. Kimi Code's non-interactive mode approves its own tool calls, so the prompts forbid writing files and browsing the web. Keep the kit in its own folder. The IBKR connector can only draft trade instructions that you approve inside IBKR, and the sizing prompt tells Claude not to draft any.

## Without the terminal

You can do the same thing by hand. Paste AGENTS.md followed by the step's prompt into each app and upload the filings. Then pass the draft and the reviews between the apps yourself. The template and checklists in `templates/` work the same way.
