"""Migration checks use isolated folders and explicitly synthetic records."""

import sqlite3

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
