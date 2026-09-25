"""Migration checks use isolated folders and explicitly synthetic records."""

import sqlite3
from contextlib import closing

import pytest

from app import db


def test_fresh_migrations_and_reopened_persistence(tmp_path):
    db.initialize(tmp_path, target_version=3)
    with db.connect(tmp_path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 3
        assert connection.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        assert {'settings', 'checks', 'cases', 'companies', 'case_companies',
                'documents', 'blocks', 'blocks_fts'} <= tables
        connection.execute(
            "INSERT INTO cases(title, created_at) VALUES (?, ?)",
            ('Synthetic migration check', '2026-09-19T00:00:00Z'),
        )
    connection.close()
    db.initialize(tmp_path, target_version=3)
    with db.connect(tmp_path) as reopened:
        assert reopened.execute('SELECT title FROM cases').fetchone()[0] == (
            'Synthetic migration check'
        )
    reopened.close()
    assert not list((tmp_path / 'backups').glob('*.db'))


def test_phase_zero_upgrade_preserves_records_and_backs_up(tmp_path):
    db.initialize(tmp_path, target_version=2)
    with db.connect(tmp_path) as connection:
        connection.execute('INSERT INTO settings VALUES (?, ?)',
                           ('test_text', 'Synthetic saved record'))
        connection.execute(
            'INSERT INTO checks(name, available, checked_at, detail) '
            'VALUES (?, ?, ?, ?)',
            ('synthetic_check', 1, '2026-09-19T00:00:00Z', 'Synthetic result'),
        )
    connection.close()
    db.initialize(tmp_path, target_version=3)
    with db.connect(tmp_path) as upgraded:
        assert upgraded.execute('PRAGMA user_version').fetchone()[0] == 3
        assert upgraded.execute('SELECT value FROM settings').fetchone()[0] == (
            'Synthetic saved record'
        )
        assert upgraded.execute('SELECT COUNT(*) FROM checks').fetchone()[0] == 1
    upgraded.close()
    backups = list((tmp_path / 'backups').glob('pre-migration-*.db'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute('PRAGMA user_version').fetchone()[0] == 2
        assert backup.execute('SELECT value FROM settings').fetchone()[0] == (
            'Synthetic saved record'
        )
        assert backup.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'cases'"
        ).fetchone()[0] == 0
    backup.close()


def test_failed_upgrade_rolls_back_changes(tmp_path):
    db.initialize(tmp_path, target_version=2)
    # Deliberately malformed synthetic Phase 0 database: force migration 003
    # to fail after its earlier CREATE TABLE statements have executed.
    with db.connect(tmp_path) as connection:
        connection.execute('CREATE TABLE documents (synthetic_marker TEXT)')
        connection.execute("INSERT INTO documents VALUES ('preserve me')")
    connection.close()
    with pytest.raises(sqlite3.OperationalError, match='already exists'):
        db.initialize(tmp_path, target_version=3)
    with db.connect(tmp_path) as reopened:
        assert reopened.execute('PRAGMA user_version').fetchone()[0] == 2
        assert reopened.execute('SELECT * FROM documents').fetchone()[0] == (
            'preserve me'
        )
        assert reopened.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'cases'"
        ).fetchone()[0] == 0
    reopened.close()


def test_document_versions_preserve_text_and_unknown_metadata(tmp_path):
    db.initialize(tmp_path, target_version=3)
    with db.connect(tmp_path) as connection:
        connection.execute("INSERT INTO cases VALUES (1, NULL, 'synthetic-date')")
        values = ('synthetic-document', 1, 'synthetic-date', 'a' * 64,
                  'documents/' + 'a' * 64, 'synthetic-cleaner-1',
                  'documents/synthetic-clean.html', 'Synthetic canonical text.',
                  'b' * 64)
        insert_version = (
            'INSERT INTO documents(logical_document_id, case_id, retrieved_at, '
            'original_sha256, original_path, cleaner_version, clean_html_path, '
            'canonical_text, text_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
        )
        connection.execute(insert_version, values)
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            connection.execute("UPDATE documents SET canonical_text = 'changed'")
        with pytest.raises(sqlite3.IntegrityError, match='preserved'):
            connection.execute('DELETE FROM documents')
        saved = connection.execute('SELECT * FROM documents').fetchone()
        assert saved['canonical_text'] == 'Synthetic canonical text.'
        assert saved['filing_date'] is None
        assert saved['accession_number'] is None
        assert saved['company_id'] is None
        next_version = values[:5] + (
            'synthetic-cleaner-2', 'documents/synthetic-clean-2.html',
            'Synthetic revised canonical text.', 'c' * 64,
        )
        connection.execute(insert_version, next_version)
        # Identical bytes in another filing association remain representable
        # without fabricating any real accession or creating another file.
        connection.execute(insert_version, ('synthetic-other-association',) + values[1:])
        versions = connection.execute(
            'SELECT id, logical_document_id, canonical_text, original_path '
            'FROM documents ORDER BY id'
        ).fetchall()
        assert len(versions) == 3
        assert len({row['original_path'] for row in versions}) == 1
        assert versions[0]['id'] != versions[1]['id']
        assert versions[0]['logical_document_id'] == versions[1]['logical_document_id']
        assert versions[0]['canonical_text'] == 'Synthetic canonical text.'
    connection.close()


@pytest.mark.parametrize('force_failure', [False, True], ids=['upgrade', 'rollback'])
def test_question_migration_preserves_runs_summaries_and_fact_history(tmp_path, force_failure):
    db.initialize(tmp_path, target_version=9)
    with closing(db.connect(tmp_path)) as connection, connection:
        connection.execute("INSERT INTO cases(id,title,created_at,question) VALUES (5,'Synthetic migration case','synthetic-date','Preserve owner notes')")
        connection.execute("INSERT INTO settings VALUES ('synthetic-preserved','Original setting')")
        for identity, kind in ((41, 'summary'), (57, 'facts')):
            connection.execute(
                "INSERT INTO model_runs VALUES (?,5,?,'synthetic-key','{\"input\":\"preserve\"}',"
                "'{\"source\":7}','{\"snapshot\":5}','completed','Synthetic result','created','submitted',"
                "'completed','original response','{\"tokens\":12}',1,'{\"metadata\":\"original\"}',2)",
                (identity, kind),
            )
        connection.execute("INSERT INTO summaries VALUES (12,5,41,'created','{\"summary\":\"original\"}')")
        for identity, previous, run, origin in ((80, None, 57, 'model'), (10, 80, None, 'human'), (90, 10, None, 'human')):
            # The lower ID references a higher ID, so copying in ID order must
            # still preserve the complete self-referencing correction chain.
            connection.execute(
                "INSERT INTO facts VALUES (?,5,'parent_name',NULL,?,?,?,'checked','created',?,?)",
                (identity, run, previous, origin, '{"value":"Synthetic ' + str(identity) + '"}', '[{"quote":"preserve me"}]'),
            )
        if force_failure:
            connection.execute("CREATE TABLE qa (synthetic_marker TEXT)")
            connection.execute("INSERT INTO qa VALUES ('preserve failed-upgrade marker')")
        before = {table: [tuple(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY 1')]
                  for table in ('cases', 'settings', 'model_runs', 'summaries', 'facts')}
    if force_failure:
        with pytest.raises(sqlite3.OperationalError, match='already exists'):
            db.initialize(tmp_path, target_version=10)
    else:
        db.initialize(tmp_path, target_version=10)
    with closing(db.connect(tmp_path)) as connection, connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == (9 if force_failure else 10)
        assert connection.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
        for table, expected in before.items():
            assert [tuple(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY 1')] == expected
        assert not connection.execute("SELECT name FROM sqlite_master WHERE name LIKE '%_new'").fetchall()
        for sql in ("UPDATE facts SET status='unknown' WHERE id=10", "DELETE FROM facts WHERE id=90",
                    "UPDATE summaries SET result_json='{}' WHERE id=12", "DELETE FROM summaries WHERE id=12",
                    "UPDATE model_runs SET request_json='{}' WHERE id=41"):
            with pytest.raises(sqlite3.IntegrityError, match='immutable|preserved'):
                connection.execute(sql)
        if force_failure:
            assert connection.execute('SELECT * FROM qa').fetchone()[0] == 'preserve failed-upgrade marker'
        else:
            connection.execute("INSERT INTO model_runs(id,case_id,task_type,request_key,request_json,source_json,snapshot_json,status,detail,created_at) "
                               "VALUES (92,5,'qa','synthetic-question','{}','{}','{}','completed','Synthetic answer','created')")
            connection.execute("INSERT INTO qa VALUES (26,5,92,'created','Synthetic question?','{\"answer\":\"original\"}')")
            for sql in ("UPDATE qa SET question='Changed' WHERE id=26", "DELETE FROM qa WHERE id=26"):
                with pytest.raises(sqlite3.IntegrityError, match='immutable|preserved'):
                    connection.execute(sql)
            with pytest.raises(sqlite3.IntegrityError, match='UNIQUE'):
                connection.execute("INSERT INTO qa VALUES (27,5,92,'created','Duplicate run','{}')")
            with pytest.raises(sqlite3.IntegrityError, match='FOREIGN KEY'):
                connection.execute("INSERT INTO qa VALUES (28,5,999,'created','Missing run','{}')")
    snapshot, = (tmp_path / 'backups').glob('pre-migration-*-v9.db')
    with closing(sqlite3.connect(snapshot)) as previous:
        assert previous.execute('PRAGMA user_version').fetchone()[0] == 9
        for table, expected in before.items():
            assert previous.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall() == expected


def test_fresh_question_schema_initializes_without_migration_backup(tmp_path):
    db.initialize(tmp_path, target_version=10)
    with closing(db.connect(tmp_path)) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 10
        assert connection.execute('SELECT count(*) FROM qa').fetchone()[0] == 0
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    assert not list((tmp_path / 'backups').glob('*.db'))
