CREATE TABLE checks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    available INTEGER NOT NULL CHECK (available IN (0, 1)),
    checked_at TEXT NOT NULL,
    detail TEXT NOT NULL
);
