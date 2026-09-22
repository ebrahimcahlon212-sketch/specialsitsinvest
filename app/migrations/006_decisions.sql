CREATE TABLE decisions (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    document_ids_json TEXT NOT NULL,
    scenario_ids_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TRIGGER decisions_preserve_update BEFORE UPDATE ON decisions
BEGIN SELECT RAISE(ABORT, 'Saved decisions are immutable; add a new decision'); END;
CREATE TRIGGER decisions_preserve_delete BEFORE DELETE ON decisions
BEGIN SELECT RAISE(ABORT, 'Saved decisions must be preserved'); END;
