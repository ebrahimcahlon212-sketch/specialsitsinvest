"""Phase 0 capability checks; every database uses a temporary folder."""

import sqlite3
import subprocess
import sys
from contextlib import closing

from app.bridge import Bridge
from app.db import check_search, connect, initialize


def test_saved_text_survives_a_new_process(tmp_path):
    initialize(tmp_path)
    text = "Synthetic persistence check: £12.50\nSecond line."
    result = Bridge(tmp_path).save_text({"text": text})
    assert result == {"text": text, "error": None}
    command = (
        "import json, sys; from pathlib import Path; from app.bridge import Bridge; "
        "print(json.dumps(Bridge(Path(sys.argv[1])).read_text({})))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", command, str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    import json

    assert json.loads(completed.stdout) == {"text": text, "error": None}


def test_missing_text_differs_from_saved_empty_text(tmp_path):
    initialize(tmp_path)
    bridge = Bridge(tmp_path)
    assert bridge.read_text({}) == {"text": None, "error": None}
    assert bridge.save_text({"text": ""}) == {"text": "", "error": None}
    assert bridge.read_text({}) == {"text": "", "error": None}


def test_failed_read_and_invalid_save_are_visible(tmp_path, caplog):
    initialize(tmp_path)
    bridge = Bridge(tmp_path)
    assert bridge.save_text({"text": 42})["error"]
    assert bridge.save_text({"text": "synthetic-private-input", "extra": True})["error"]
    assert "synthetic-private-input" not in caplog.text
    with closing(connect(tmp_path)) as connection, connection:
        connection.execute("DROP TABLE settings")
    assert bridge.read_text({})["error"]


def test_search_check_is_dated_and_persisted(tmp_path):
    initialize(tmp_path)
    checked = check_search(tmp_path)
    assert checked["available"] is True
    assert checked["checked_at"].endswith("+00:00")
    saved = Bridge(tmp_path).read_search_check({})
    assert saved == {**checked, "error": None}


def test_failed_search_is_recorded_without_hiding_the_error(tmp_path, monkeypatch):
    initialize(tmp_path, target_version=2)
    real_connect = connect

    def deny_virtual_table(data_dir):
        connection = real_connect(data_dir)
        connection.set_authorizer(
            lambda action, *_: sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_CREATE_VTABLE else sqlite3.SQLITE_OK
        )
        return connection

    # Synthetic SQLite denial exercises the failure branch without a live service.
    monkeypatch.setattr("app.db.connect", deny_virtual_table)
    checked = check_search(tmp_path)
    assert checked["available"] is False
    assert "failed" in checked["detail"]
    assert "not authorized" in checked["detail"]
    assert Bridge(tmp_path).read_search_check({}) == {**checked, "error": None}
