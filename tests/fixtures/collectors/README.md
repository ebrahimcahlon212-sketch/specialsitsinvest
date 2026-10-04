# Small primary-source response samples

Downloaded on 4 October 2026 with the collectors in this checkout. No response body was edited. `manifest.json` records each request URL, UTC download time, HTTP status, byte count, local filename and SHA-256. Repeated SEC submissions requests share a content-addressed response file. The saved SEC contact was used as the SEC User-Agent and is deliberately absent from the manifest.

The sample contains two Drugs@FDA application records from the official openFDA Drugs@FDA endpoint, two published CRLs, one SEC company submissions response and three 8-K document sets. One set includes an EX-99.1 exhibit. These are parser fixtures, not a historical census or a reference-class acceptance dataset. The FDA source here is the API representation of Drugs@FDA, not its bulk ZIP.

The Drugs@FDA search matched submission dates, including supplements. Only the original approved submission's own date is emitted. Tests check that narrowing the action window does not admit the supplement date as an original approval. The CRL sample includes a supplemental application that is excluded, and a letter whose application later shows an approved status. The latter remains a CRL candidate at its letter date. Original BLA versus biosimilar eligibility is not certified by this sample.

The SEC sample supplies structured 8-K acceptance times for event timing under amendment 8. Current tickers and exchanges are labelled current, never treated as proof of historical listing. Keyword hits retain their source document and exact extracted-text line. They are research leads, not verified drug events.

All tests replay local responses with network access disabled at the transport boundary. Edge-case tests modify these responses in memory or use explicitly artificial transport responses. They do not pass those modifications off as downloaded fixtures.

The separate `../legacy-baseline.json` records calculator results and Markdown plus catalyst calculations from commit `1429cc8`, using a fixed date of 4 October 2026. Those artificial examples test compatibility, not investment conclusions.

Round 5 downloaded three bounded openFDA requests on 4 October 2026, two Drugs@FDA date windows and one CRL letter_date window. Their exact URLs, bodies and hashes are saved here and under data/refclass/raw/<source>/<download-date>/. Offline replay now uses exact request URLs without a substitution shim. These bounded samples do not establish census coverage.
