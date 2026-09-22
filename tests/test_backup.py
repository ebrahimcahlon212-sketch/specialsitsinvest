"""Synthetic storage fixtures test offline backup and export, not source behaviour."""

import csv
import hashlib
import json
import os
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest

from app import backup, db


@pytest.fixture
def research(tmp_path):
    data = tmp_path / "research"
    db.initialize(data)
    text = "Synthetic storage fixture; not a real filing."
    original = text.encode("utf-8")
    original_hash = hashlib.sha256(original).hexdigest()
    original_path = f"documents/{original_hash}.txt"
    clean_path = f"documents/{original_hash}.html"
    (data / original_path).write_bytes(original)
    (data / clean_path).write_text(f"<p>{text}</p>", encoding="utf-8")
    with closing(db.connect(data)) as connection, connection:
        connection.execute(
            "INSERT INTO cases(id, title, created_at, question) VALUES (1, ?, ?, ?)",
            ("Synthetic backup fixture", "2026-09-19T12:00:00+00:00", "An owner-entered research question"),
        )
        connection.execute(
            "INSERT INTO documents(id, logical_document_id, case_id, name, retrieved_at, original_sha256, "
            "original_path, cleaner_version, clean_html_path, canonical_text, text_hash) "
            "VALUES (1, 'synthetic-document', 1, 'Synthetic text', '2026-09-19T12:00:00+00:00', ?, ?, 'fixture-1', ?, ?, ?)",
            (original_hash, original_path, clean_path, text, original_hash),
        )
        connection.execute(
            "INSERT INTO blocks(id, document_id, start_offset, end_offset, text) VALUES (1, 1, 0, ?, ?)",
            (len(text), text),
        )
        connection.execute("INSERT INTO blocks_fts(rowid, heading, text) VALUES (1, '', ?)", (text,))
        connection.execute(
            "INSERT INTO scenarios(id, case_id, name, kind, inputs_json, outputs_json, display_json, created_at) "
            "VALUES (1, 1, 'Hypothetical valuation', 'spinoff', ?, ?, ?, '2026-09-19T12:01:00+00:00')",
            (json.dumps({"price": "0.100000000000000000001", "currency": "GBP"}),
             json.dumps({"equity_value": "12.50", "currency": "GBP"}),
             json.dumps({"equity_value": {"value": "12.50", "unit": "GBP"}})),
        )
        connection.execute(
            "INSERT INTO decisions(id, case_id, decision, reason, document_ids_json, scenario_ids_json, evidence_json, created_at) "
            "VALUES (1, 1, 'Research further', 'Synthetic fixture only', '[1]', '[1]', ?, '2026-09-19T12:02:00+00:00')",
            (json.dumps([{"document_id": 1, "text_hash": original_hash, "start_offset": 0,
                          "end_offset": len(text), "quote": text}]),),
        )
        connection.execute("INSERT INTO settings(key, value) VALUES ('fixture_marker', 'NEVER_EXPORT_THIS_SETTING')")
    (data / "app.log").write_text("NEVER_EXPORT_THIS_LOG", encoding="utf-8")
    return data


def snapshot(data):
    return Path(backup.create_backup(data)["path"])


def alter_manifest(path, edit):
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    edit(manifest)
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def refresh_database_entry(path, manifest):
    database = (path / "app.db").read_bytes()
    manifest["files"]["app.db"] = {"sha256": hashlib.sha256(database).hexdigest(), "size": len(database)}


def test_complete_backup_restores_rows_search_versions_and_every_file(research, tmp_path):
    result = backup.create_backup(research)
    saved = Path(result["path"])
    manifest = json.loads((saved / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert "second backup folder" in result["warning"]
    assert not (saved / "app.log").exists()
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "app.log").write_text("Existing diagnostic log", encoding="utf-8")
    (destination / "documents").mkdir()
    restored = backup.restore_backup(saved, destination)
    assert restored["schema_version"] == manifest["schema_version"]
    assert "Credentials must be entered again" in restored["warning"]
    for relative, entry in manifest["files"].items():
        contents = (destination / relative).read_bytes()
        assert hashlib.sha256(contents).hexdigest() == entry["sha256"]
        assert len(contents) == entry["size"]
    with closing(db.connect(destination)) as connection:
        for table, expected in manifest["row_counts"].items():
            assert connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == expected
        assert connection.execute("SELECT rowid FROM blocks_fts WHERE blocks_fts MATCH 'fixture'").fetchone()[0] == 1
        assert json.loads(connection.execute("SELECT inputs_json FROM scenarios").fetchone()[0])["price"] == "0.100000000000000000001"
        assert json.loads(connection.execute("SELECT evidence_json FROM decisions").fetchone()[0])[0]["document_id"] == 1
    assert (destination / "app.log").read_text(encoding="utf-8") == "Existing diagnostic log"
    assert backup.list_backups(research / "backups")[0]["path"] == str(saved)


@pytest.mark.parametrize("damage", ["missing", "hash", "incomplete", "future", "corrupt_database", "counts", "traversal", "extra"])
def test_invalid_snapshots_are_not_offered_or_restored(research, tmp_path, damage):
    saved = snapshot(research)
    document = next((saved / "documents").glob("*.txt"))
    if damage == "missing":
        document.unlink()
    elif damage == "hash":
        document.write_text("changed", encoding="utf-8")
    elif damage == "incomplete":
        alter_manifest(saved, lambda manifest: manifest.update(complete=False))
    elif damage == "future":
        with closing(sqlite3.connect(saved / "app.db")) as connection:
            connection.execute("PRAGMA user_version = 999")
        def future(manifest):
            manifest["schema_version"] = 999
            refresh_database_entry(saved, manifest)
        alter_manifest(saved, future)
    elif damage == "corrupt_database":
        (saved / "app.db").write_bytes(b"Synthetic corrupt database")
        alter_manifest(saved, lambda manifest: refresh_database_entry(saved, manifest))
    elif damage == "counts":
        alter_manifest(saved, lambda manifest: manifest["row_counts"].update(cases=300))
    elif damage == "traversal":
        def traversal(manifest):
            relative = document.relative_to(saved).as_posix()
            manifest["files"]["../outside.txt"] = manifest["files"].pop(relative)
        alter_manifest(saved, traversal)
    else:
        (saved / "unlisted.txt").write_text("Synthetic unlisted file", encoding="utf-8")
    warnings = []
    assert backup.list_backups(research / "backups", warnings=warnings) == []
    assert len(warnings) == 1 and "verification failed" in warnings[0]
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        backup.restore_backup(saved, tmp_path / "restored")
    assert not (tmp_path / "restored" / "app.db").exists()
    assert (research / "app.db").exists()


def test_missing_source_file_leaves_no_complete_or_incomplete_backup(research):
    next((research / "documents").glob("*.txt")).unlink()
    with pytest.raises(ValueError, match="missing"):
        backup.create_backup(research)
    assert not list((research / "backups").glob("backup-*"))
    assert not list((research / "backups").glob(".incomplete-*"))


def test_existing_database_and_unrelated_files_are_never_overwritten(research, tmp_path):
    saved = snapshot(research)
    destination = tmp_path / "existing"
    destination.mkdir()
    database = destination / "app.db"
    database.write_bytes(b"Preserve this existing database even if unusable")
    with pytest.raises(ValueError, match="never overwrites"):
        backup.restore_backup(saved, destination)
    assert database.read_bytes() == b"Preserve this existing database even if unusable"
    database.unlink()
    (destination / "other.txt").write_text("Preserve unrelated text", encoding="utf-8")
    with pytest.raises(ValueError, match="empty research folder"):
        backup.restore_backup(saved, destination)
    assert (destination / "other.txt").read_text(encoding="utf-8") == "Preserve unrelated text"


def test_restore_publication_failure_rolls_back_new_files_and_can_be_retried(research, tmp_path, monkeypatch):
    saved = snapshot(research)
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "app.log").write_text("Keep diagnostics", encoding="utf-8")
    real_link = os.link
    def fail_database(source, target):
        if target.name == "app.db":
            raise OSError("Synthetic publication failure")
        real_link(source, target)
    monkeypatch.setattr(backup.os, "link", fail_database)
    with pytest.raises(OSError, match="Synthetic publication failure"):
        backup.restore_backup(saved, destination)
    assert list(destination.iterdir()) == [destination / "app.log"]
    assert not list(tmp_path.glob(".restored-restore-*"))
    monkeypatch.setattr(backup.os, "link", real_link)
    backup.restore_backup(saved, destination)
    assert (destination / "app.db").is_file()


def test_symbolic_document_path_is_rejected_without_reading_its_target(research, tmp_path):
    original = next((research / "documents").glob("*.txt"))
    outside = tmp_path / "outside.txt"
    original.rename(outside)
    try:
        original.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symbolic links requires an unavailable Windows privilege.")
    with pytest.raises(ValueError, match="symbolic links"):
        backup.create_backup(research)
    assert outside.exists()


def test_retention_keeps_ten_complete_snapshots_and_preserves_other_files(research):
    legacy = research / "backups" / "pre-migration-fixture.db"
    legacy.write_bytes(b"Preserve existing pre-migration backup")
    names = [snapshot(research).name for _ in range(11)]
    retained = backup.list_backups(research / "backups")
    assert len(retained) == 10
    assert names[0] not in {item["name"] for item in retained}
    assert names[-1] in {item["name"] for item in retained}
    assert legacy.read_bytes() == b"Preserve existing pre-migration backup"
    assert len(list((research / "documents").iterdir())) == 2


def test_second_location_failure_preserves_valid_local_backup(research, tmp_path, monkeypatch):
    def fail_copy(*args, **kwargs):
        raise OSError("Synthetic unavailable second disk")
    monkeypatch.setattr(backup.shutil, "copytree", fail_copy)
    result = backup.create_backup(research, tmp_path / "second")
    assert "second copy failed" in result["warning"]
    assert "Synthetic unavailable second disk" in result["warning"]
    assert backup.list_backups(research / "backups")[0]["path"] == result["path"]
    assert not list((tmp_path / "second").glob(".incomplete-*"))


def test_second_copy_is_verified_and_same_volume_is_identified(research, tmp_path):
    result = backup.create_backup(research, tmp_path / "second")
    assert "same volume" in result["warning"]
    assert len(backup.list_backups(tmp_path / "second")) == 1


def test_backup_holds_data_lock_until_documents_are_copied(research, monkeypatch):
    started = threading.Event()
    completed = threading.Event()
    real_copy = backup.shutil.copyfile
    writer = None
    def write_later():
        started.set()
        with db.DATA_LOCK, closing(db.connect(research)) as connection, connection:
            connection.execute("UPDATE cases SET title = 'Later title' WHERE id = 1")
        completed.set()
    def check_lock(source, target):
        nonlocal writer
        if writer is None:
            writer = threading.Thread(target=write_later)
            writer.start()
            assert started.wait(1)
            assert not completed.wait(0.05)
        return real_copy(source, target)
    monkeypatch.setattr(backup.shutil, "copyfile", check_lock)
    saved = snapshot(research)
    writer.join(timeout=2)
    assert completed.is_set()
    with closing(db.connect(saved)) as connection:
        assert connection.execute("SELECT title FROM cases WHERE id = 1").fetchone()[0] == "Synthetic backup fixture"


def test_export_preserves_decimal_text_and_decision_evidence_without_settings_or_logs(research, tmp_path):
    result = backup.export_case(research, 1, tmp_path / "exports")
    markdown, facts = map(Path, result["paths"])
    content = markdown.read_text(encoding="utf-8")
    assert "0.100000000000000000001" in content
    assert '"currency": "GBP"' in content
    assert "2026-09-19T12:02:00+00:00" in content
    assert '"quote": "Synthetic storage fixture; not a real filing."' in content
    assert "original sha256" in content and "text hash" in content
    assert "No model summary has been produced" in content
    assert "No extracted facts have been saved" in content
    assert "NEVER_EXPORT_THIS_SETTING" not in content
    assert "NEVER_EXPORT_THIS_LOG" not in content
    with facts.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    assert len(rows) == 1
    assert {"unit", "currency", "quote", "document_id", "text_hash"}.issubset(rows[0])
    assert len(list(markdown.parent.iterdir())) == 2
    second = backup.export_case(research, 1, tmp_path / "exports")
    assert Path(second["paths"][0]).parent != markdown.parent
    assert markdown.read_text(encoding="utf-8") == content


def save_synthetic_fact_history(data):
    """Storage fixture only: these are not validated financial observations."""
    value = {'value': '0.100000000000000000001', 'unit': 'GBP', 'currency': 'GBP',
             'entity': 'Synthetic entity', 'period': 'Hypothetical period', 'basis': 'pro_forma',
             'kind': 'assumption', 'finding': 'value', 'reason': 'Synthetic storage example',
             'qualifications': 'Not a real financial observation'}
    with closing(db.connect(data)) as connection, connection:
        document = connection.execute('SELECT * FROM documents WHERE id=1').fetchone()
        citation = {'document_id': 1, 'text_version_id': 1, 'document_hash': document['original_sha256'],
                    'start_offset': 0, 'end_offset': len(document['canonical_text']),
                    'quote': document['canonical_text'], 'status': 'quote matched'}
        evidence = [{'citation': citation, 'fields': ['value']}]
        connection.execute("INSERT INTO model_runs(id,case_id,task_type,request_key,request_json,source_json,"
                           "snapshot_json,status,detail,created_at) VALUES (1,1,'facts','synthetic','{}','{}',"
                           "'{}','completed','Synthetic saved fixture','2026-09-20T12:00:00+00:00')")
        connection.execute("INSERT INTO facts(id,case_id,fact_key,document_id,run_id,origin,status,created_at,"
                           "value_json,evidence_json) VALUES (1,1,'cash_at_separation',1,1,'model','extracted',"
                           "'2026-09-20T12:00:00+00:00',?,?)", (json.dumps(value), json.dumps(evidence)))
        corrected = {**value, 'value': '0.200000000000000000002', 'reason': 'Synthetic owner correction'}
        connection.execute("INSERT INTO facts(id,case_id,fact_key,document_id,previous_id,origin,status,created_at,"
                           "value_json,evidence_json) VALUES (2,1,'cash_at_separation',1,1,'human','checked',"
                           "'2026-09-20T12:01:00+00:00',?,?)", (json.dumps(corrected), json.dumps(evidence)))
        return [dict(row) for row in connection.execute('SELECT * FROM facts ORDER BY id')]


def test_schema_nine_backup_restores_fact_history_and_immutable_corrections(research, tmp_path):
    expected = save_synthetic_fact_history(research)
    saved = snapshot(research)
    manifest = json.loads((saved / 'manifest.json').read_text())
    assert manifest['schema_version'] == 9 and manifest['row_counts']['facts'] == 2
    destination = tmp_path / 'isolated-facts-restore'
    backup.restore_backup(saved, destination)
    with closing(db.connect(destination)) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 9
        assert [dict(row) for row in connection.execute('SELECT * FROM facts ORDER BY id')] == expected
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            connection.execute("UPDATE facts SET status='unknown' WHERE id=2")


def test_export_includes_actual_facts_history_source_and_decimal_text(research, tmp_path):
    save_synthetic_fact_history(research)
    result = backup.export_case(research, 1, tmp_path / 'facts-export')
    markdown, csv_path = map(Path, result['paths'])
    text = markdown.read_text(encoding='utf-8')
    assert 'Saved facts and correction history' in text
    assert 'Synthetic owner correction' in text and 'Synthetic storage example' in text
    assert 'No extracted facts' not in text and 'header only' not in result['warning']
    assert 'Document answers have not been produced' in result['warning']
    assert 'NEVER_EXPORT_THIS_SETTING' not in text and 'NEVER_EXPORT_THIS_LOG' not in text
    with csv_path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert rows[0]['value'] == '0.100000000000000000001'
    assert rows[1]['value'] == '0.200000000000000000002'
    assert rows[1]['previous_id'] == '1' and rows[1]['origin'] == 'human' and rows[1]['status'] == 'checked'
    assert rows[1]['unit'] == rows[1]['currency'] == 'GBP'
    assert rows[1]['entity'] == 'Synthetic entity' and rows[1]['period'] == 'Hypothetical period'
    assert rows[0]['quote'] == 'Synthetic storage fixture; not a real filing.'
    assert json.loads(rows[0]['evidence_json'])[0]['citation']['start_offset'] == 0


def test_schema_nine_snapshot_missing_facts_table_is_rejected(research):
    saved = snapshot(research)
    with closing(sqlite3.connect(saved / 'app.db')) as connection, connection:
        connection.execute('DROP TABLE facts')
    def changed(manifest):
        manifest['row_counts'].pop('facts')
        refresh_database_entry(saved, manifest)
    alter_manifest(saved, changed)
    with pytest.raises(ValueError, match='required research tables'):
        backup._validate_snapshot(saved)


def test_missing_backup_root_is_empty_but_read_failure_is_reported(tmp_path, monkeypatch):
    root = tmp_path / "backups"
    warnings = []
    assert backup.list_backups(root, warnings=warnings) == []
    assert warnings == []
    root.mkdir()
    original_iterdir = Path.iterdir
    def deny_root(path):
        if path == root:
            raise PermissionError("Synthetic directory read failure")
        return original_iterdir(path)
    monkeypatch.setattr(Path, "iterdir", deny_root)
    with pytest.raises(PermissionError, match="Synthetic directory read failure"):
        backup.list_backups(root)


def test_unreadable_restore_subfolder_is_not_treated_as_empty(research, tmp_path, monkeypatch):
    saved = snapshot(research)
    destination = tmp_path / "destination"
    blocked = destination / "unreadable"
    blocked.mkdir(parents=True)
    original_iterdir = Path.iterdir
    def deny_subfolder(path):
        if path == blocked:
            raise PermissionError("Synthetic subfolder read failure")
        return original_iterdir(path)
    monkeypatch.setattr(Path, "iterdir", deny_subfolder)
    with pytest.raises(PermissionError, match="Synthetic subfolder read failure"):
        backup.restore_backup(saved, destination)
    assert not (destination / "app.db").exists()


def test_restore_rejects_a_source_snapshot_changed_while_copying(research, tmp_path, monkeypatch):
    earlier = snapshot(research)
    extra = research / "documents" / "synthetic-second.txt"
    extra.write_bytes(b"Synthetic second storage document")
    with closing(db.connect(research)) as connection, connection:
        connection.execute(
            "INSERT INTO documents(logical_document_id, case_id, name, retrieved_at, original_sha256, original_path) "
            "VALUES ('synthetic-second', 1, 'Synthetic second', '2026-09-19T12:03:00+00:00', ?, 'documents/synthetic-second.txt')",
            (hashlib.sha256(extra.read_bytes()).hexdigest(),),
        )
    later = snapshot(research)
    original_copytree = backup.shutil.copytree
    def changed_source(source, target, *args, **kwargs):
        return original_copytree(later if source == earlier else source, target, *args, **kwargs)
    monkeypatch.setattr(backup.shutil, "copytree", changed_source)
    destination = tmp_path / "restored"
    with pytest.raises(ValueError, match="changed while being copied"):
        backup.restore_backup(earlier, destination)
    assert not destination.exists()
