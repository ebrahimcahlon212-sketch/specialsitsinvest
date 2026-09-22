"""Offline task integration with labelled synthetic data and isolated folders."""

import json
from contextlib import closing
from pathlib import Path

import pytest

from app import cases, db
from app.bridge import Bridge
from test_calc import worksheet


def test_bridge_offline_workflow_and_saved_evidence(tmp_path, monkeypatch):
    data_dir = tmp_path / "research"
    data_dir.mkdir()
    bridge = Bridge(data_dir)
    assert bridge.app_state({})["needs_setup"] is True
    assert not (data_dir / "app.db").exists()
    assert bridge.start_fresh({})["error"] is None
    assert bridge.start_fresh({})["error"]
    created = bridge.create_case({"title": "Synthetic offline case", "question": "Synthetic question"})
    assert created["error"] is None
    case_id = created["case"]["id"]
    source = tmp_path / "synthetic.txt"
    source.write_text("First paragraph.\nRepeated words here.\nSecond context.\nRepeated words here.", encoding="utf-8")
    monkeypatch.setattr("app.bridge._pick", lambda *_args, **_kwargs: source)
    assert bridge.import_local({"case_id": case_id})["error"] is None
    assert bridge.import_local({"case_id": case_id})["error"] is None
    detail = bridge.case_detail({"case_id": case_id})
    assert detail["error"] is None
    assert len(detail["documents"]) == 1
    document_id = detail["documents"][0]["id"]
    assert detail["documents"][0]["filing_date"] is None
    hits = bridge.search_documents({"case_id": case_id, "query": "Repeated words"})
    assert hits["error"] is None
    last_hit = hits["hits"][-1]
    passage = bridge.read_document({"document_id": document_id, "block_id": last_hit["block_id"], "quote": "Repeated words here."})
    assert passage["error"] is None
    assert "<mark>" in passage["document"]["html"]
    scenario = bridge.save_scenario({"case_id": case_id, "kind": "spinoff", "name": "Synthetic valuation",
                                     "inputs": worksheet().model_dump(mode="json")})
    assert scenario["error"] is None
    assert scenario["scenario"]["outputs"]["base"]["value_per_share"]["value"] == "14"
    saved = bridge.save_decision({
        "case_id": case_id, "decision": "Continue hypothetical research", "reason": "Synthetic reason, not investment advice.",
        "document_ids": [document_id], "scenario_ids": [scenario["scenario"]["id"]],
        "evidence": [{"document_id": document_id, "block_id": last_hit["block_id"], "quote": "Repeated words here."}],
    })
    assert saved["error"] is None
    restarted = Bridge(data_dir)
    assert restarted.update_case({"case_id": case_id, "title": "Updated synthetic case", "question": "Changed notes", "status": "watching"})["error"] is None
    historical = restarted.read_saved_evidence({"decision_id": saved["decision"]["id"], "index": 0})
    assert historical["error"] is None
    assert historical["document"]["citation"] == passage["document"]["citation"]
    assert restarted.case_detail({"case_id": case_id})["decisions"][0]["reason"] == saved["decision"]["reason"]
    destination = tmp_path / "exports"
    destination.mkdir()
    monkeypatch.setattr("app.bridge._pick", lambda *_args, **_kwargs: destination)
    exported = restarted.export_case({"case_id": case_id})
    assert exported["error"] is None
    markdown = (Path(exported["path"]) / "case.md").read_text(encoding="utf-8")
    assert "Repeated words here." in markdown and "No model summary" in markdown
    assert '"value": "14"' in markdown


def test_decision_rejects_cross_case_references(tmp_path):
    db.initialize(tmp_path)
    first = cases.create_case(tmp_path, "Synthetic first case")
    second = cases.create_case(tmp_path, "Synthetic second case")
    scenario = cases.save_scenario(tmp_path, first["id"], "Synthetic scenario", "spinoff", worksheet().model_dump(mode="json"))
    with pytest.raises(ValueError, match="does not belong"):
        cases.save_decision(tmp_path, second["id"], "Synthetic decision", "Synthetic reason", [], [scenario["id"]], [])
    assert cases.list_decisions(tmp_path, second["id"]) == []


def test_new_migrations_upgrade_prior_batch_without_losing_records(tmp_path):
    db.initialize(tmp_path, target_version=3)
    with closing(db.connect(tmp_path)) as connection, connection:
        connection.execute("INSERT INTO settings VALUES ('saved_text', 'Synthetic original note')")
        connection.execute("INSERT INTO cases(title, created_at) VALUES ('Synthetic old case', '2026-09-19')")
    db.initialize(tmp_path, target_version=6)
    with closing(db.connect(tmp_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert connection.execute("SELECT value FROM settings").fetchone()[0] == "Synthetic original note"
        assert connection.execute("SELECT question FROM cases").fetchone()[0] == ""
    assert len(list((tmp_path / "backups").glob("pre-migration-*.db"))) == 1


def test_bridge_rejects_arbitrary_paths_and_numeric_money(tmp_path):
    db.initialize(tmp_path)
    bridge = Bridge(tmp_path)
    assert bridge.import_local({"case_id": 1, "path": "C:/unselected.txt"})["error"]
    assert bridge.restore_backup({"path": "C:/unselected"})["error"]
    inputs = worksheet().model_dump(mode="json")
    inputs["profit"]["value"] = 50
    assert "must be text" in bridge.calculate_scenario({"case_id": 1, "kind": "spinoff", "name": "Synthetic", "inputs": inputs})["error"]


def test_bridge_backups_warn_and_restore_to_empty_copy(tmp_path, monkeypatch):
    data_dir = tmp_path / "research"
    db.initialize(data_dir)
    bridge = Bridge(data_dir)
    assert bridge.save_text({"text": "Synthetic backup note"})["error"] is None
    backed_up = bridge.create_backup({})
    assert backed_up["error"] is None and backed_up["warning"]
    snapshot = Path(backed_up["path"])
    target = tmp_path / "restored-copy"
    target.mkdir()
    selections = iter([snapshot, target])
    monkeypatch.setattr("app.bridge._pick", lambda *_args, **_kwargs: next(selections))
    assert bridge.restore_backup({"to_new_folder": True})["error"] is None
    assert Bridge(target).read_text({})["text"] == "Synthetic backup note"
    assert bridge.read_text({})["text"] == "Synthetic backup note"
    manifest = snapshot / "manifest.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    metadata["complete"] = False
    manifest.write_text(json.dumps(metadata), encoding="utf-8")
    state = bridge.app_state({})
    assert state["error"] is None
    assert state["backup_names"] == [] and state["backup_warnings"]


def test_failed_backup_scan_does_not_block_opening_research(tmp_path, monkeypatch):
    db.initialize(tmp_path)
    cases.create_case(tmp_path, "Synthetic available case")

    def unreadable(*_args, **_kwargs):
        raise PermissionError("Synthetic unreadable backup folder")

    monkeypatch.setattr("app.backup.list_backups", unreadable)
    bridge = Bridge(tmp_path)
    state = bridge.app_state({})
    assert state["error"] is None and state["backup_names"] is None
    assert state["backup_warnings"]
    assert bridge.list_cases({})["cases"][0]["title"] == "Synthetic available case"
