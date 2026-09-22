-- Extend the existing run log without changing saved IDs or summary references.
CREATE TABLE model_runs_new (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    task_type TEXT NOT NULL CHECK (task_type IN ('summary','facts')),
    request_key TEXT NOT NULL,
    request_json TEXT NOT NULL,
    source_json TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','connecting','submitted','completed','failed','cancelled','timed_out','interrupted')),
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    completed_at TEXT,
    response_text TEXT,
    usage_json TEXT,
    usage_uncertain INTEGER NOT NULL DEFAULT 0 CHECK (usage_uncertain IN (0,1)),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    retry_count INTEGER NOT NULL DEFAULT 0
);

INSERT INTO model_runs_new SELECT * FROM model_runs;
CREATE TABLE summaries_new (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    run_id INTEGER NOT NULL UNIQUE REFERENCES model_runs_new(id),
    created_at TEXT NOT NULL,
    result_json TEXT NOT NULL
);
INSERT INTO summaries_new SELECT * FROM summaries;
DROP TABLE summaries;
DROP TABLE model_runs;
ALTER TABLE model_runs_new RENAME TO model_runs;
ALTER TABLE summaries_new RENAME TO summaries;
CREATE INDEX model_runs_cache ON model_runs(case_id, request_key, status);
CREATE TRIGGER summaries_preserve_update BEFORE UPDATE ON summaries BEGIN
    SELECT RAISE(ABORT, 'Saved summaries are immutable; create a new run');
END;
CREATE TRIGGER summaries_preserve_delete BEFORE DELETE ON summaries BEGIN
    SELECT RAISE(ABORT, 'Saved summaries must be preserved');
END;
CREATE TRIGGER model_runs_preserve_request
BEFORE UPDATE OF case_id, task_type, request_key, request_json, source_json, snapshot_json ON model_runs BEGIN
    SELECT RAISE(ABORT, 'Model run inputs are immutable');
END;

CREATE TABLE facts (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    fact_key TEXT NOT NULL,
    document_id INTEGER REFERENCES documents(id),
    run_id INTEGER REFERENCES model_runs(id),
    previous_id INTEGER REFERENCES facts(id),
    origin TEXT NOT NULL CHECK (origin IN ('model','human')),
    status TEXT NOT NULL CHECK (status IN ('extracted','checked','contradicted','unknown')),
    created_at TEXT NOT NULL,
    value_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    UNIQUE(run_id,fact_key)
);
CREATE INDEX facts_case_key ON facts(case_id,fact_key,origin,id);
CREATE TRIGGER facts_preserve_update BEFORE UPDATE ON facts BEGIN
    SELECT RAISE(ABORT, 'Facts are immutable; record a correction or new proposal');
END;
CREATE TRIGGER facts_preserve_delete BEFORE DELETE ON facts BEGIN
    SELECT RAISE(ABORT, 'Fact history must be preserved');
END;
