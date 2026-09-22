# InvestResearch

**Work in progress.** Features and checks are still being completed.

InvestResearch is a Windows desktop app for researching US company spinoffs. It keeps filings, notes, calculations and decisions together on your computer.

You can import a filing, search its text and open the source passage behind a quotation. The calculators cover spinoff valuations and fixed-price tender offers. Saved scenarios keep the assumptions used for each calculation.

You can export cases, make backups and use an existing ChatGPT subscription for summaries and proposed deal terms. Model results need review. A matching quotation confirms the words occur in the filing, not that the interpretation is right.

Research is stored locally in SQLite and document files. The app does not place trades. Automatic discovery, document questions and broker connections are not implemented.

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

For a provisional Python 3.12 setup, replace `py -3.13` with `py -3.12`. The app does not install or upgrade Python.

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

Create a case, then import a local HTML or text file. To import an SEC filing URL, first enter your name and contact email in **Settings** for the SEC request header. Contact details are stored locally, not in the source code.

Open the case to search documents, save calculations and record decisions. **Evidence / edit** opens the source for an extracted term and lets you save a correction with a reason. Earlier values are retained.

## Optional subscription features

Summaries and deal terms require an installed Codex client and an existing ChatGPT login. The tested client is `0.155.0-alpha.9.2`, using `gpt-5.6-luna` with low reasoning. Other client versions are unverified. The app does not install Codex or fall back to paid API calls.

Use **Settings > Check connection** before a request. Generation runs only when requested. The model process has broad read-only filesystem access; it is not isolated to a document folder. Supported optional tools and connectors are disabled, but universal prevention of tool execution has not been established.

Extraction has been checked against saved fixtures and a live Sandisk filing example. Two revised batches completed; the financial batch timed out, leaving its earlier saved results in place. Some Windows interactions and document punctuation still need checking.

## Development

The interface uses React, TypeScript and Mantine. Python handles storage, document processing and Decimal calculations. The interface calls Python through the pywebview bridge; there is no separate backend service.

```powershell
.\.venv\Scripts\python.exe -m pytest
Set-Location ui
npm.cmd run build
```

Automated tests use temporary data folders and saved fixtures. They do not call live services. Some proposal fixtures are explicitly constructed for validation tests; they are not presented as real model answers.

For interface development, run `npm.cmd run dev` inside `ui`, then set `$env:APP_DEV = '1'` in the PowerShell window that launches Python. Remove that variable to return to the built interface.
