"""Saved real SEC responses; missing-response and damage cases are synthetic.

No test contacts SEC. The saved Sandisk filing is 0001193125-24-264578,
filed 2024-11-25; unprovided responses fail explicitly instead of inventing bytes.
"""

import json
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests

from app import backup, cases, db, documents, sec


FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://www.sec.gov/Archives/edgar/data/2023554/000119312524264578/"
FILING = BASE + "0001193125-24-264578-index.html"
MAIN = BASE + "d835366d1012b.htm"
STATEMENT = BASE + "d835366dex991.htm"


@pytest.fixture(autouse=True)
def no_live_requests(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Automated SEC tests must never make a live request")
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)


@pytest.fixture
def research(tmp_path):
    data = tmp_path / "data"
    db.initialize(data)
    sec.save_contact(data, "Synthetic Tester", "test@example.invalid")
    case = cases.create_case(data, "Sandisk saved filing test")
    return data, case["id"]


@pytest.fixture
def saved_fetch(monkeypatch):
    requested, unavailable = [], set()
    def fetch(url, user_agent):
        requested.append(url)
        name = urlsplit(url).path.rsplit("/", 1)[-1]
        matches = list(FIXTURES.glob("sandisk_20241125_" + name))
        if url in unavailable or len(matches) != 1:
            raise requests.Timeout("Synthetic missing saved response: " + name)
        return matches[0].read_bytes()
    monkeypatch.setattr(sec, "fetch", fetch)
    return requested, unavailable


def item_by_url(record, url):
    return next(item for item in record["items"] if item["url"] == url)


@pytest.mark.parametrize('inline_viewer', [False, True])
def test_real_filing_index_and_exhibit_url_share_association(inline_viewer):
    filing = sec.resolve_url(FILING)
    exhibit = sec.resolve_url(STATEMENT)
    assert filing["filing_url"] == exhibit["filing_url"] == FILING
    assert filing["base_url"].rstrip("/") == BASE.rstrip("/")
    assert filing["accession_number"] == "0001193125-24-264578"
    assert filing["cik"].lstrip("0") == "2023554"
    content = (FIXTURES / "sandisk_20241125_0001193125-24-264578-index.html").read_bytes()
    if inline_viewer:  # Synthetic viewer links around the saved real document list.
        content = content.replace(b'href="/Archives/', b'href="/ix?doc=/Archives/')
        assert sec.resolve_url('https://www.sec.gov/ix?doc=' + urlsplit(MAIN).path)['url'] == MAIN
    parsed = sec.parse_index(content, filing)
    assert parsed["filing_date"] == "2024-11-25"
    assert parsed["form_type"] == "10-12B"
    assert item_by_url(parsed, MAIN)["document_type"] == "10-12B"
    assert item_by_url(parsed, STATEMENT)["document_type"] == "EX-99.1"
    assert item_by_url(parsed, STATEMENT)["name"] == "d835366dex991.htm"
    assert len(parsed["items"]) == 73
    directory = json.loads((FIXTURES / "sandisk_20241125_index.json").read_text())
    raw_exhibit = next(item for item in directory["directory"]["item"] if item["name"] == "d835366dex991.htm")
    assert raw_exhibit["type"] == "text.gif"  # The directory does not supply exhibit labels.


@pytest.mark.parametrize("url", [
    "https://example.com/Archives/edgar/data/2023554/000119312524264578/d835366dex991.htm",
    "file:///C:/Windows/win.ini", "http://127.0.0.1/", "https://www.sec.gov/Archives/edgar/data/../secret",
    'https://www.sec.gov/ix?doc=https://example.com/filing.htm',
    'https://example.com/ix?doc=' + urlsplit(MAIN).path,
    'https://www.sec.gov/ix?doc=' + urlsplit(MAIN).path + '&doc=' + urlsplit(STATEMENT).path,
    'https://www.sec.gov/ix?doc=' + urlsplit(MAIN).path + '&extra=1',
])
def test_synthetic_invalid_urls_are_rejected(url):
    with pytest.raises(ValueError):
        sec.resolve_url(url)


def test_saved_statement_search_repeat_import_and_shared_filing_identity(research, saved_fetch):
    data, case_id = research
    requested, _ = saved_fetch
    import_id = sec.prepare_import(data, case_id, STATEMENT)
    sec.run_import(data, import_id)
    record = sec.list_imports(data, case_id)[0]
    statement = item_by_url(record, STATEMENT)
    assert statement["status"] == "fetched"
    assert statement["document_id"] is not None
    hits = documents.search(data, case_id, "Dear Future Sandisk Corporation Stockholder")
    assert any(hit["document_id"] == statement["document_id"] for hit in hits)
    with closing(db.connect(data)) as connection:
        original_rows = [tuple(row) for row in connection.execute("SELECT id, logical_document_id, original_sha256 FROM documents ORDER BY id")]
    original_files = sorted(path.relative_to(data).as_posix() for path in (data / "documents").rglob("*") if path.is_file())
    repeated_id = sec.prepare_import(data, case_id, FILING)
    assert repeated_id == import_id
    sec.run_import(data, repeated_id)
    assert len(sec.list_imports(data, case_id)) == 1
    with closing(db.connect(data)) as connection:
        assert [tuple(row) for row in connection.execute("SELECT id, logical_document_id, original_sha256 FROM documents ORDER BY id")] == original_rows
    assert sorted(path.relative_to(data).as_posix() for path in (data / "documents").rglob("*") if path.is_file()) == original_files
    assert BASE + "index.json" in requested and FILING in requested


def test_failed_statement_is_visible_and_retry_preserves_saved_versions(research, saved_fetch):
    data, case_id = research
    _, unavailable = saved_fetch
    unavailable.add(STATEMENT)
    import_id = sec.prepare_import(data, case_id, FILING)
    sec.run_import(data, import_id)
    failed = sec.list_imports(data, case_id)[0]
    assert item_by_url(failed, STATEMENT)["status"] == "failed"
    assert "Synthetic missing saved response" in item_by_url(failed, STATEMENT)["detail"]
    with closing(db.connect(data)) as connection:
        before = {row["id"]: tuple(row) for row in connection.execute("SELECT * FROM documents")}
    unavailable.remove(STATEMENT)
    assert sec.prepare_import(data, case_id, FILING) == import_id
    sec.run_import(data, import_id)
    recovered = sec.list_imports(data, case_id)[0]
    assert item_by_url(recovered, STATEMENT)["status"] == "fetched"
    with closing(db.connect(data)) as connection:
        after = {row["id"]: tuple(row) for row in connection.execute("SELECT * FROM documents")}
    assert all(after[identity] == row for identity, row in before.items())


def test_interrupted_import_keeps_its_reason_and_manifest(research):
    data, case_id = research
    import_id = sec.prepare_import(data, case_id, FILING)
    sec.recover_interrupted(data)
    queued = sec.list_imports(data, case_id)[0]
    assert queued["status"] == "interrupted"
    with closing(db.connect(data)) as connection, connection:
        connection.execute("UPDATE sec_imports SET status = 'running' WHERE id = ?", (import_id,))
    sec.recover_interrupted(data)
    interrupted = sec.list_imports(data, case_id)[0]
    assert interrupted["status"] == "interrupted"
    assert interrupted["detail"]
    assert interrupted["items"] == queued["items"]


def test_synthetic_alternative_exhibit_needs_explicit_selection(research, saved_fetch, monkeypatch, tmp_path):
    data, case_id = research
    cases.update_case(data, case_id, "Synthetic alternate exhibit-label test", "", "watching")
    real_parse = sec.parse_index
    def alternate_label(content, info):
        parsed = real_parse(content, info)
        # Synthetic structural variant: these are not the actual filing's exhibit labels.
        item_by_url(parsed, STATEMENT)["document_type"] = "EX-99.2"
        return parsed
    monkeypatch.setattr(sec, "parse_index", alternate_label)
    import_id = sec.prepare_import(data, case_id, FILING)
    sec.run_import(data, import_id)
    missing = sec.list_imports(data, case_id)[0]
    assert missing["status"] == "partial"
    assert missing["selected_document_url"] is None
    assert "Exhibit 99.1 is absent" in missing["detail"]
    exported = backup.export_case(data, case_id, tmp_path / "export")
    text = Path(exported["paths"][0]).read_text(encoding="utf-8")
    assert "Exhibit 99.1 is absent" in text and '"status": "not fetched"' in text
    sec.run_import(data, import_id, selected_url=STATEMENT)
    selected = sec.list_imports(data, case_id)[0]
    assert selected["selected_document_url"] == STATEMENT
    assert selected["status"] == "complete"
    assert item_by_url(selected, STATEMENT)["status"] == "fetched"


def test_v6_upgrade_backup_restore_and_export_include_import_failures(tmp_path, saved_fetch):
    data = tmp_path / "data"
    db.initialize(data, target_version=6)
    sec.save_contact(data, "Synthetic Tester", "test@example.invalid")
    case_id = cases.create_case(data, "Sandisk saved response upgrade test")["id"]
    old_export = backup.export_case(data, case_id, tmp_path / "old-export")
    assert "No SEC filing imports" in Path(old_export["paths"][0]).read_text(encoding="utf-8")
    db.initialize(data, target_version=7)
    migrations = list((data / "backups").glob("pre-migration-*-v6.db"))
    assert len(migrations) == 1
    with closing(db.connect(data)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
    _, unavailable = saved_fetch
    unavailable.add(STATEMENT)
    import_id = sec.prepare_import(data, case_id, FILING)
    sec.run_import(data, import_id)
    imports = sec.list_imports(data, case_id)
    snapshot = Path(backup.create_backup(data)["path"])
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["row_counts"]["sec_imports"] == 1
    restored = tmp_path / "restored"
    backup.restore_backup(snapshot, restored)
    assert sec.list_imports(restored, case_id) == imports
    exported = backup.export_case(restored, case_id, tmp_path / "export")
    markdown = Path(exported["paths"][0]).read_text(encoding="utf-8")
    assert "0001193125-24-264578" in markdown and "2024-11-25" in markdown
    assert "EX-99.1" in markdown and '"status": "failed"' in markdown
    assert "Synthetic missing saved response" in markdown
    assert "Filing document statuses" in markdown


def test_schema_seven_backup_rejects_missing_import_table(research):
    data, _ = research
    with closing(db.connect(data)) as connection, connection:
        connection.execute("DROP TABLE sec_imports")
    with pytest.raises(ValueError, match="missing required research tables"):
        backup.create_backup(data)
