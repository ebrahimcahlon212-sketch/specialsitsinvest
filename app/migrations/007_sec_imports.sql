CREATE TABLE sec_imports (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    request_url TEXT NOT NULL,
    filing_url TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    cik TEXT NOT NULL,
    filing_date TEXT,
    form_type TEXT,
    status TEXT NOT NULL,
    detail TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    selected_document_url TEXT,
    items_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(case_id, filing_url)
);
