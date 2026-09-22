CREATE TABLE model_runs (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    task_type TEXT NOT NULL CHECK (task_type = 'summary'),
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
CREATE INDEX model_runs_cache ON model_runs(case_id, request_key, status);

CREATE TABLE summaries (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    run_id INTEGER NOT NULL UNIQUE REFERENCES model_runs(id),
    created_at TEXT NOT NULL,
    result_json TEXT NOT NULL
);
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
