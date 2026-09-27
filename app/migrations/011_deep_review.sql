-- Widen the run type while retaining IDs and all incoming references.
-- Replacement child tables refer only to replacement parents, including facts'
-- self-reference. The migration runner keeps foreign keys enabled throughout.
CREATE TABLE model_runs_new (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    task_type TEXT NOT NULL CHECK (task_type IN ('summary','facts','qa','review')),
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

CREATE TABLE facts_new (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    fact_key TEXT NOT NULL,
    document_id INTEGER REFERENCES documents(id),
    run_id INTEGER REFERENCES model_runs_new(id),
    previous_id INTEGER REFERENCES facts_new(id),
    origin TEXT NOT NULL CHECK (origin IN ('model','human')),
    status TEXT NOT NULL CHECK (status IN ('extracted','checked','contradicted','unknown')),
    created_at TEXT NOT NULL,
    value_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    UNIQUE(run_id,fact_key)
);
INSERT INTO facts_new SELECT * FROM facts;

CREATE TABLE qa_new (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    run_id INTEGER NOT NULL UNIQUE REFERENCES model_runs_new(id),
    created_at TEXT NOT NULL,
    question TEXT NOT NULL,
    result_json TEXT NOT NULL
);
INSERT INTO qa_new SELECT * FROM qa;
DROP TABLE qa;
DROP TABLE facts;
DROP TABLE summaries;
DROP TABLE model_runs;
ALTER TABLE model_runs_new RENAME TO model_runs;
ALTER TABLE summaries_new RENAME TO summaries;
ALTER TABLE facts_new RENAME TO facts;
ALTER TABLE qa_new RENAME TO qa;

CREATE INDEX model_runs_cache ON model_runs(case_id, request_key, status);
CREATE INDEX facts_case_key ON facts(case_id,fact_key,origin,id);
CREATE TRIGGER model_runs_preserve_request
BEFORE UPDATE OF case_id, task_type, request_key, request_json, source_json, snapshot_json ON model_runs BEGIN
    SELECT RAISE(ABORT, 'Model run inputs are immutable');
END;
CREATE TRIGGER summaries_preserve_update BEFORE UPDATE ON summaries BEGIN
    SELECT RAISE(ABORT, 'Saved summaries are immutable; create a new run');
END;
CREATE TRIGGER summaries_preserve_delete BEFORE DELETE ON summaries BEGIN
    SELECT RAISE(ABORT, 'Saved summaries must be preserved');
END;
CREATE TRIGGER facts_preserve_update BEFORE UPDATE ON facts BEGIN
    SELECT RAISE(ABORT, 'Facts are immutable; record a correction or new proposal');
END;
CREATE TRIGGER facts_preserve_delete BEFORE DELETE ON facts BEGIN
    SELECT RAISE(ABORT, 'Fact history must be preserved');
END;


CREATE TRIGGER qa_preserve_update BEFORE UPDATE ON qa BEGIN
    SELECT RAISE(ABORT, 'Saved answers are immutable; ask a new question');
END;
CREATE TRIGGER qa_preserve_delete BEFORE DELETE ON qa BEGIN
    SELECT RAISE(ABORT, 'Saved answers must be preserved');
END;
CREATE TABLE review_results (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    run_id INTEGER NOT NULL UNIQUE REFERENCES model_runs(id),
    plan_key TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('batch','report')),
    created_at TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE INDEX review_results_plan ON review_results(case_id,plan_key,phase);
CREATE TRIGGER review_results_preserve_update BEFORE UPDATE ON review_results BEGIN
    SELECT RAISE(ABORT, 'Saved reviews are immutable; create another review');
END;
CREATE TRIGGER review_results_preserve_delete BEFORE DELETE ON review_results BEGIN
    SELECT RAISE(ABORT, 'Saved reviews must be preserved');
END;
