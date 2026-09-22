CREATE TABLE cases (
    id INTEGER PRIMARY KEY,
    title TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE companies (
    id INTEGER PRIMARY KEY,
    name TEXT,
    cik TEXT UNIQUE
);

CREATE TABLE case_companies (
    case_id INTEGER NOT NULL REFERENCES cases(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    role TEXT CHECK (role IN ('parent', 'spinco')),
    PRIMARY KEY (case_id, company_id)
);

-- Each row identifies one immutable version. Separate filing associations can
-- share an original file; logical_document_id groups versions of one association.
CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    logical_document_id TEXT NOT NULL,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    company_id INTEGER REFERENCES companies(id),
    name TEXT,
    source_url TEXT,
    retrieved_at TEXT NOT NULL,
    filing_date TEXT,
    accession_number TEXT,
    form_type TEXT,
    exhibit_label TEXT,
    original_sha256 TEXT NOT NULL CHECK (length(original_sha256) = 64),
    original_path TEXT NOT NULL,
    cleaner_version TEXT,
    clean_html_path TEXT,
    canonical_text TEXT,
    text_hash TEXT CHECK (text_hash IS NULL OR length(text_hash) = 64),
    CHECK (
        (cleaner_version IS NULL AND clean_html_path IS NULL
         AND canonical_text IS NULL AND text_hash IS NULL)
        OR
        (cleaner_version IS NOT NULL AND clean_html_path IS NOT NULL
         AND canonical_text IS NOT NULL AND text_hash IS NOT NULL)
    ),
    UNIQUE (logical_document_id, original_sha256, cleaner_version)
);

CREATE TRIGGER documents_preserve_version
BEFORE UPDATE OF id, logical_document_id, original_sha256, original_path,
                 cleaner_version, clean_html_path, canonical_text, text_hash
ON documents
BEGIN
    SELECT RAISE(ABORT, 'Document versions are immutable; insert a new version');
END;

CREATE TRIGGER documents_preserve_saved_version
BEFORE DELETE ON documents
BEGIN
    SELECT RAISE(ABORT, 'Saved document versions must be preserved');
END;

CREATE TABLE blocks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    heading TEXT,
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset > start_offset),
    text TEXT NOT NULL,
    UNIQUE (document_id, start_offset, end_offset)
);

-- Index population belongs to task 1.3, alongside the canonical text cleaner.
CREATE VIRTUAL TABLE blocks_fts USING fts5(
    heading, text, content='blocks', content_rowid='id'
);
