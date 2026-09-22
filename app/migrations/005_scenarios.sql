ALTER TABLE cases ADD COLUMN question TEXT NOT NULL DEFAULT '';
ALTER TABLE cases ADD COLUMN status TEXT NOT NULL DEFAULT 'research';
ALTER TABLE cases ADD COLUMN updated_at TEXT;

CREATE TABLE scenarios (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('spinoff', 'tender')),
    inputs_json TEXT NOT NULL,
    outputs_json TEXT NOT NULL,
    display_json TEXT NOT NULL,
    warning TEXT,
    created_at TEXT NOT NULL
);

CREATE TRIGGER scenarios_preserve_update BEFORE UPDATE ON scenarios
BEGIN SELECT RAISE(ABORT, 'Saved scenarios are immutable; save a new scenario'); END;
CREATE TRIGGER scenarios_preserve_delete BEFORE DELETE ON scenarios
BEGIN SELECT RAISE(ABORT, 'Saved scenarios must be preserved'); END;
