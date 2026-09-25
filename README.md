# InvestResearch

**Work in progress.** Features and checks are still being completed.

InvestResearch is a Windows desktop app for researching US company spinoffs. It keeps filings, notes, calculations and decisions together on your computer.

You can import a filing, search its text and open the source passage behind a quotation. The calculators cover spinoff valuations and fixed-price tender offers. Saved scenarios keep the assumptions used for each calculation.

You can export cases, make backups and use an existing ChatGPT subscription for summaries, proposed deal terms and questions about saved documents. Model results need review. A matching quotation confirms the words occur in the filing, not that the interpretation is right.

Research is stored locally in SQLite and document files. The app does not place trades. Automatic discovery and broker connections are not implemented.

## Setup

You need Windows, Microsoft Edge WebView2, Python and Node.js with npm. Python 3.13 is the project target. The current checks were run with Python 3.12; Python 3.13 compatibility is still unverified.

Open PowerShell in the project folder. With Python 3.13 already installed:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Location ui
npm.cmd ci
npm.cmd run build
Set-Location ..
```

The app does not install or upgrade Python. The Python 3.12 trial uses a separate environment and launcher.

## Run

From the project folder:

```powershell
.\.venv\Scripts\python.exe -m app
```

The normal data folder is `%LOCALAPPDATA%\InvestResearch`. On first launch, choose **Start fresh** or restore a complete backup into an empty folder. Restoring does not replace an existing research folder.

To create the desktop shortcut with the project's virtual environment:

```powershell
.\create-shortcut.ps1
```

Then open **InvestResearch** from the desktop. If Windows blocks the shortcut script, use the Python launch command above without changing security settings.

If you already use **InvestResearch Trial**, keep using that shortcut and its existing data folder to retain your saved research.

## First case

Create a case, then import a local HTML, UTF-8 text or text-PDF file. To import an SEC filing URL, first enter your name and contact email in **Settings** for the SEC request header. Contact details are stored locally, not in the source code.

Open the case to search documents, save calculations and record decisions. **Evidence / edit** opens the source for an extracted term and lets you save a correction with a reason. Earlier values are retained.

Under **Ask about a document**, select a saved document version, type a question and click **Ask question**. The answer lists the passages used. Click **Quote matched** to open its source. Previous answers remain in **Saved answers**; an unchanged request reuses its saved result. **Cancel** stops a pending request without restarting it.

## Optional subscription features

Summaries, deal terms and document answers require an installed Codex client and an existing ChatGPT login. The currently pinned client is `0.155.0-alpha.16`, using `gpt-6-sol` with high reasoning for case briefings and `gpt-5.6-luna` with low reasoning for deal terms and document questions. If Codex replaces this executable during an update, the app stops generation until the replacement is checked. It does not install Codex or fall back to paid API calls.

Use **Settings > Check connection** before a request. Under **Case briefing**, select up to six documents and click **Generate case briefing** or **Refresh case briefing**. Expand **Supporting quotation** and click **Open quoted passage** to inspect evidence. Generation runs only when requested. The model process has broad read-only filesystem access; it is not isolated to a document folder. Supported optional tools and connectors are disabled, but universal prevention of tool execution has not been established.

## Development

The interface uses React, TypeScript and Mantine. Python handles storage, document processing and Decimal calculations. The interface calls Python through the pywebview bridge; there is no separate backend service.

```powershell
.\.venv\Scripts\python.exe -m pytest
Set-Location ui
npm.cmd run build
```

Automated tests use temporary data folders and saved fixtures. They do not call live services. Some proposal fixtures are explicitly constructed for validation tests; they are not presented as real model answers.

For interface development, run `npm.cmd run dev` inside `ui`, then set `$env:APP_DEV = '1'` in the PowerShell window that launches Python. Remove that variable to return to the built interface.
