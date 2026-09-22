ALTER TABLE documents ADD COLUMN media_type TEXT;
ALTER TABLE documents ADD COLUMN processing_error TEXT;
ALTER TABLE blocks ADD COLUMN partial INTEGER NOT NULL DEFAULT 0 CHECK (partial IN (0, 1));

-- Local imports have no filing metadata. Reimporting the same bytes in a case
-- reuses its raw record; a different case keeps its own association.
CREATE UNIQUE INDEX documents_local_original
ON documents(case_id, original_sha256)
WHERE cleaner_version IS NULL AND source_url IS NULL AND accession_number IS NULL;
