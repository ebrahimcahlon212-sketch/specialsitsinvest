"""Saved real Sandisk sources/responses and labelled synthetic structural responses.

All research folders are isolated copies. Generation is replaced where used;
these checks never contact Codex and do not establish semantic accuracy.
"""

import copy
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from app import backup, cases, constants, db, documents, model, prompts, worker


SECTIONS = ("company", "event", "what_must_happen", "dates", "unknowns", "risks")
EVENT_QUOTE = "resulting in two independent, publicly traded companies."
COMPANY_QUOTE = "WDC will continue to lead the storage industry in delivering powerful HDD solutions for high-capacity applications."


def synthetic_response():
    """Deliberately synthetic sentences; only source quotation mechanics are tested."""
    return {
        "is_spinoff": "yes",
        "reasoning": {"text": "Synthetic classification explanation.",
                      "quote": EVENT_QUOTE, "status": "sourced", "passage_id": 1, "ai_comment": None},
        "sentences": [
            {"section": section, "text": f"Synthetic {section} statement.",
             "quote": COMPANY_QUOTE if section == "company" else None,
             "status": "sourced" if section == "company" else "unresolved",
             "passage_id": 1 if section == "company" else None, "ai_comment": None}
            for section in SECTIONS
        ],
    }


def test_saved_real_luna_summary_structure_and_quotes_match_exact_supplied_excerpt():
    path = Path(__file__).parent / "fixtures" / "sandisk_20241220_luna_summary.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    output = prompts.SummaryOutput.model_validate(fixture["response"]).model_dump()
    source, excerpt = fixture["source"], fixture["filing_excerpt"]
    assert fixture["model"] == "gpt-5.6-luna"
    assert source["start_offset"] == 0 and source["end_offset"] == len(excerpt) == 39988
    assert source["end_offset"] < source["total_chars"]
    checked = [cases._checked_statement(item, source, excerpt)
               for item in [output["reasoning"], *output["sentences"]]]
    assert sum(item["status"] == "quote matched" for item in checked) == 8
    assert sum(item["status"] == "unresolved" for item in checked) == 1
    for item in checked:
        citation = item["citation"]
        if item["status"] == "unresolved":
            assert citation is None and item["detail"]
            continue
        assert citation["document_id"] == citation["text_version_id"] == source["document_id"]
        assert citation["document_hash"] == source["original_sha256"]
        start, end = citation["start_offset"], citation["end_offset"]
        assert 0 <= start < end <= len(excerpt)
        assert citation["quote"] == excerpt[start:end]
        assert " ".join(citation["quote"].split()) == " ".join(item["quote"].split())


def test_saved_real_sol_mbgl_briefing_quotes_match_only_their_supplied_passages():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "mbgl_20260923_sol_briefing.json").read_text(encoding="utf-8"))
    output = prompts.BriefingOutput.model_validate(fixture["response"]).model_dump()
    assert fixture["model"] == "gpt-6-sol"
    passages = {item["id"]: item for item in fixture["passages"]}
    assert {item["document_id"] for item in fixture["sources"]} == {35, 49, 69, 75}
    assert {item["document_id"] for item in passages.values()} <= {35, 49, 69, 75}
    claims = [output["reasoning"], *output["sentences"]]
    assert sum(item["status"] == "sourced" for item in claims) == 22
    assert sum(item["status"] == "unresolved" for item in claims) == 3
    for item in claims:
        if item["status"] != "sourced":
            assert item["quote"] is None and item["passage_id"] is None
            continue
        passage = passages[item["passage_id"]]
        assert len(passage["text"]) == passage["end_offset"] - passage["start_offset"]
        start, end = documents.match_quote(passage["text"], item["quote"])
        assert " ".join(passage["text"][start:end].split()) == " ".join(item["quote"].split())


@pytest.fixture(scope="module")
def saved_filing(tmp_path_factory):
    template = tmp_path_factory.mktemp("summary-template")
    db.initialize(template)
    case = cases.create_case(template, "Sandisk saved-fixture test", "Synthetic owner note; preserve it.")
    path = Path(__file__).parent / "fixtures" / "sandisk_20241125_d835366dex991.htm"
    document = documents.import_local(template, case["id"], path)
    return template, case, document


@pytest.fixture
def research(saved_filing, tmp_path, monkeypatch):
    template, case, document = saved_filing
    data = tmp_path / "isolated-research"
    shutil.copytree(template, data)
    queued, calls = [], []
    context = {"runtime": "synthetic-runtime", "version": "synthetic-version-1",
               "sha256": "a" * 64, "config_hash": "b" * 64}
    response = {"status": "completed", "response_text": json.dumps(synthetic_response()),
                "usage": {"inputTokens": 100, "outputTokens": 40, "totalTokens": 140},
                "submitted": True, "usage_uncertain": False,
                "retry_notifications": [], "tool_activity": [], "error": None}

    def generate(_data, request, cancel_event, progress):
        calls.append(copy.deepcopy(request))
        progress("Synthetic request submitted.", submitted=True)
        return copy.deepcopy(response)

    monkeypatch.setattr(model, "runtime_context", lambda *args: copy.deepcopy(context))
    monkeypatch.setattr(model, "generate", generate)
    monkeypatch.setattr(worker, "submit", lambda function, *args: queued.append((function, args)))
    return {"data": data, "case": case, "document": document, "queued": queued,
            "calls": calls, "context": context, "response": response}


def finish(research, document_ids=None):
    data, case_id = research["data"], research["case"]["id"]
    cases.generate_summary(data, case_id, research["document"]["id"] if document_ids is None else document_ids)
    assert len(research["queued"]) == 1
    function, arguments = research["queued"].pop()
    function(*arguments)
    return cases.summary_status(data, case_id)


def rows(research, table):
    with closing(db.connect(research["data"])) as connection:
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]


def test_completed_summary_saved_quotes_reopen_and_unchanged_request_reuses_cache(research):
    state = finish(research)
    summary = state["summary"]
    assert summary is not None and not summary["stale"]
    assert len(research["calls"]) == 1
    original_documents = rows(research, "documents")
    original_summaries = rows(research, "summaries")
    for index, expected in ((0, EVENT_QUOTE), (1, COMPANY_QUOTE)):
        opened = cases.read_summary_evidence(research["data"], summary["id"], index)
        citation = opened["citation"]
        assert citation["document_id"] == research["document"]["id"]
        assert citation["status"] == "quote matched"
        assert " ".join(citation["quote"].split()) == expected
        marked = BeautifulSoup(opened["html"], "lxml").find_all("mark")
        assert "".join(mark.get_text() for mark in marked) == citation["quote"]
        assert documents.read_citation(research["data"], citation) == opened
    cached = finish(research)
    assert not research["queued"] and len(research["calls"]) == 1
    assert cached["summary"]["id"] == summary["id"]
    assert rows(research, "summaries") == original_summaries
    assert rows(research, "documents") == original_documents
    assert cases.list_cases(research["data"])[0]["question"] == research["case"]["question"]


@pytest.mark.parametrize("change", ["question", "prompt", "prompt_text", "runtime", "model", "effort", "retrieval"])
def test_effective_request_changes_prevent_cache_reuse(research, monkeypatch, change):
    first = finish(research)["summary"]
    case = research["case"]
    if change == "question":
        cases.update_case(research["data"], case["id"], case["title"], "Changed synthetic owner question.", case["status"])
    elif change == "prompt":
        monkeypatch.setattr(prompts, "SUMMARY_PROMPT_VERSION", "synthetic-next-prompt")
    elif change == "prompt_text":
        monkeypatch.setattr(prompts, "SUMMARY_PROMPT", prompts.SUMMARY_PROMPT + "\nSynthetic changed instructions.")
    elif change in ("model", "effort", "retrieval"):
        field, value = {"model": ("SUMMARY_MODEL_NAME", "synthetic-other-model"),
                        "effort": ("SUMMARY_MODEL_EFFORT", "synthetic-other-effort"),
                        "retrieval": ("SUMMARY_RETRIEVAL_VERSION", "synthetic-next-retrieval")}[change]
        monkeypatch.setattr(constants, field, value)
        saved = cases.summary_status(research["data"], case["id"])["summary"]
        assert saved["stale"]
        if change == "retrieval":
            assert any("passage-selection rules" in reason for reason in saved["stale_reasons"])
    else:
        research["context"]["config_hash"] = "c" * 64
    second = finish(research)["summary"]
    assert second["id"] != first["id"]
    assert len(research["calls"]) == 2
    assert research["calls"][0] != research["calls"][1]


def test_owner_checked_correction_changes_summary_inputs_and_marks_prior_summary_stale(research):
    data, case_id, document_id = research["data"], research["case"]["id"], research["document"]["id"]
    first = finish(research)["summary"]
    before, _, snapshot = cases.prepare_summary(data, case_id, document_id)
    assert "owner_facts" not in snapshot
    assert "owner_checked_or_corrected_facts" not in json.loads(before["input_text"])
    assert finish(research)["summary"]["id"] == first["id"] and len(research["calls"]) == 1
    assert cases.prepare_summary(data, case_id, document_id)[0] == before
    cases.correct_fact(data, case_id=case_id, key="parent_name", previous_id=None,
        value="Western Digital Corporation", unit=None, currency=None, entity=None, period=None,
        basis="not_applicable", kind="published", qualifications=None, reason="Synthetic owner source check.",
        document_id=document_id, quote="Dear Western Digital Corporation Stockholder:")
    after, _, snapshot = cases.prepare_summary(data, case_id, document_id)
    assert snapshot["owner_facts"][0]["status"] == "checked"
    assert json.loads(after["input_text"])["owner_checked_or_corrected_facts"] == snapshot["owner_facts"]
    assert after["prompt_version"] == before["prompt_version"] + "+owner-facts-1"
    old = cases.summary_status(data, case_id)["summary"]
    assert old["id"] == first["id"] and old["stale"]
    assert any("facts have changed" in reason for reason in old["stale_reasons"])
    refreshed = finish(research)["summary"]
    assert refreshed["id"] != first["id"] and not refreshed["stale"]
    assert len(research["calls"]) == 2


def test_new_document_and_changed_selection_mark_summary_stale_preserving_old_evidence(research, tmp_path):
    first = finish(research)["summary"]
    saved = cases.read_summary_evidence(research["data"], first["id"], 0)
    source = tmp_path / "synthetic-additional.txt"
    source.write_text("Clearly synthetic additional source for freshness testing.", encoding="utf-8")
    other = documents.import_local(research["data"], research["case"]["id"], source)
    assert cases.summary_status(research["data"], research["case"]["id"])["summary"]["stale"]
    cases.set_summary_source(research["data"], research["case"]["id"], other["id"])
    assert cases.summary_status(research["data"], research["case"]["id"])["summary"]["stale"]
    assert cases.read_summary_evidence(research["data"], first["id"], 0) == saved
    assert rows(research, "summaries")[0]["id"] == first["id"]
    research["document"] = other
    refreshed = finish(research)["summary"]
    assert refreshed["id"] != first["id"]
    assert refreshed["source"]["document_id"] == other["id"]
    assert research["calls"][0] != research["calls"][1]


def test_saved_summary_and_citation_remain_available_without_runtime(research, monkeypatch):
    summary = finish(research)["summary"]
    def unavailable(*args):
        raise FileNotFoundError("Synthetic unavailable Codex runtime.")
    monkeypatch.setattr(model, "runtime_context", unavailable)
    assert cases.summary_status(research["data"], research["case"]["id"])["summary"]["id"] == summary["id"]
    assert cases.read_summary_evidence(research["data"], summary["id"], 0)["citation"]["quote"] == EVENT_QUOTE


def test_unusable_current_source_preserves_saved_summary_and_its_quotation(research, monkeypatch):
    summary = finish(research)["summary"]
    original = cases._summary_sources
    def failed_current_source(connection, case_id, document_id=None):
        if document_id is None:
            raise ValueError("Synthetic newer source has no usable text.")
        return original(connection, case_id, document_id)
    monkeypatch.setattr(cases, "_summary_sources", failed_current_source)
    state = cases.summary_status(research["data"], research["case"]["id"])
    assert state["summary"]["id"] == summary["id"] and state["summary"]["stale"]
    assert state["source"] is None and "no usable text" in state["error"]
    assert cases.read_summary_evidence(research["data"], summary["id"], 0)["citation"]["quote"] == EVENT_QUOTE


def test_export_contains_saved_summary_and_real_citation_instead_of_absence_claim(research, tmp_path):
    summary = finish(research)["summary"]
    exported = backup.export_case(research["data"], research["case"]["id"], tmp_path / "isolated-export")
    markdown = Path(exported["paths"][0]).read_text(encoding="utf-8")
    assert summary["reasoning"]["text"] in markdown and EVENT_QUOTE in markdown
    assert f'"document_id": {research["document"]["id"]}' in markdown
    assert '"status": "quote matched"' in markdown
    assert "covers only the recorded portion" in markdown
    assert "No model summary" not in markdown


def test_completed_summary_run_and_quotation_survive_isolated_backup_restore(research, tmp_path):
    summary = finish(research)["summary"]
    evidence = cases.read_summary_evidence(research["data"], summary["id"], 0)
    snapshot = Path(backup.create_backup(research["data"])["path"])
    target = tmp_path / "isolated-restored-summary"
    backup.restore_backup(snapshot, target)
    restored = cases.summary_status(target, research["case"]["id"])
    assert restored["summary"] == summary
    assert cases.read_summary_evidence(target, summary["id"], 0) == evidence
    with closing(db.connect(target)) as connection:
        assert connection.execute("SELECT count(*) FROM model_runs WHERE status = 'completed'").fetchone()[0] == 1


@pytest.mark.parametrize("invalid", ["not-json", "missing-section", "extra-field", "bad-status", "empty-sourced-quote"])
def test_invalid_structured_output_does_not_create_summary_or_cache_success(research, invalid):
    response = synthetic_response()
    if invalid == "missing-section":
        response["sentences"].pop()
    elif invalid == "extra-field":
        response["guaranteed_return"] = "Synthetic forbidden extra field"
    elif invalid == "bad-status":
        response["sentences"][0]["status"] = "human checked"
    elif invalid == "empty-sourced-quote":
        response["sentences"][0]["quote"] = ""
    research["response"]["response_text"] = "not JSON" if invalid == "not-json" else json.dumps(response)
    finish(research)
    assert rows(research, "summaries") == []
    run, = rows(research, "model_runs")
    assert run["status"] != "completed"
    assert len(research["calls"]) == 1 and not research["queued"]
    assert cases.summary_status(research["data"], research["case"]["id"])["summary"] is None


@pytest.mark.parametrize("quote", ["Table of Contents", "This synthetic quotation does not occur."])
def test_ambiguous_missing_or_empty_quotes_remain_unresolved(research, quote):
    response = synthetic_response()
    response["sentences"][0]["quote"] = quote
    research["response"]["response_text"] = json.dumps(response)
    summary = finish(research)["summary"]
    assert summary["sentences"][0]["status"] == "unresolved"
    assert summary["sentences"][0]["citation"] is None
    with pytest.raises(ValueError):
        cases.read_summary_evidence(research["data"], summary["id"], 1)


def test_source_selection_rejects_document_from_another_case(research, tmp_path):
    other_case = cases.create_case(research["data"], "Synthetic other case")
    source = tmp_path / "synthetic-other.txt"
    source.write_text("Synthetic other-case text.", encoding="utf-8")
    other_document = documents.import_local(research["data"], other_case["id"], source)
    with pytest.raises(ValueError):
        cases.set_summary_source(research["data"], research["case"]["id"], other_document["id"])
    with pytest.raises(ValueError):
        cases.generate_summary(research["data"], research["case"]["id"], other_document["id"])
    assert not research["queued"] and not research["calls"]


def test_quote_after_supplied_portion_cannot_become_verified(research, monkeypatch):
    # The quote really exists at offset 712, but this request supplies only 400 characters.
    monkeypatch.setattr(constants, "SUMMARY_MAX_CHARS", 400)
    summary = finish(research)["summary"]
    assert summary["source"]["end_offset"] <= 400
    assert summary["sentences"][0]["status"] == "unresolved"
    assert summary["sentences"][0]["citation"] is None
    assert summary["reasoning"]["citation"]["end_offset"] <= 400


@pytest.mark.parametrize("binding", ["correct", "wrong-document", "unsupplied-passage"])
def test_multi_document_quotes_bind_to_only_the_named_supplied_passage(research, binding):
    data, case_id = research["data"], research["case"]["id"]
    quote = "Clearly synthetic second document supplies this distinct event description."
    other = documents.store_document(data, case_id, quote.encode(), "Synthetic second source", "text/plain")
    identities = [research["document"]["id"], other["id"]]
    request, _, snapshot = cases.prepare_summary(data, case_id, identities)
    passage = next(item for item in snapshot["retrieval"]["passages"] if item["document_id"] == other["id"])
    response = synthetic_response()
    response["sentences"][1].update(quote=quote, status="sourced", ai_comment="Synthetic interpretation of this evidence.",
        passage_id=passage["id"] if binding == "correct" else 1 if binding == "wrong-document" else 999999)
    research["response"]["response_text"] = json.dumps(response)
    summary = finish(research, identities)["summary"]
    assert {source["document_id"] for source in summary["sources"]} == set(identities)
    assert research["calls"][0] == request
    item = summary["sentences"][1]
    if binding == "correct":
        assert item["status"] == "quote matched" and item["ai_comment"] == response["sentences"][1]["ai_comment"]
        opened = cases.read_summary_evidence(data, summary["id"], 2)
        assert opened["citation"]["document_id"] == opened["citation"]["text_version_id"] == other["id"]
        assert opened["citation"]["document_hash"] == other["original_sha256"]
        assert opened["canonical_text"][opened["citation"]["start_offset"]:opened["citation"]["end_offset"]] == quote
        original = rows(research, "summaries")
        assert finish(research, list(reversed(identities)))["summary"]["id"] == summary["id"]
        assert len(research["calls"]) == 1 and rows(research, "summaries") == original
    else:
        assert item["status"] == "unresolved" and item["citation"] is None and item["ai_comment"] is None
        with pytest.raises(ValueError, match="no verified"):
            cases.read_summary_evidence(data, summary["id"], 2)
    assert json.loads(rows(research, "model_runs")[0]["response_text"]) == response


def test_two_versions_of_same_logical_document_cannot_be_combined(research):
    summary = finish(research)["summary"]
    data, case_id, first = research["data"], research["case"]["id"], research["document"]
    old_evidence = cases.read_summary_evidence(data, summary["id"], 0)
    revised = documents.store_document(data, case_id, b"Clearly synthetic revised document version.",
        "Synthetic revised source", "text/html", logical_document_id=first["logical_document_id"])
    for action in (cases.set_summary_source, cases.generate_summary):
        with pytest.raises(ValueError, match="one version"):
            action(data, case_id, [first["id"], revised["id"]])
    assert not research["queued"] and len(research["calls"]) == 1
    assert cases.summary_status(data, case_id)["summary"]["stale"]
    assert cases.read_summary_evidence(data, summary["id"], 0) == old_evidence


def test_failed_quote_removes_ai_comment_but_preserves_original_response(research):
    response = synthetic_response()
    response["sentences"][0].update(quote="Clearly synthetic absent quotation.",
                                   ai_comment="Synthetic interpretation that must not be promoted.")
    research["response"]["response_text"] = json.dumps(response)
    summary = finish(research)["summary"]
    item = summary["sentences"][0]
    assert item["status"] == "unresolved" and item["citation"] is None and item["ai_comment"] is None
    assert json.loads(rows(research, "model_runs")[0]["response_text"]) == response


@pytest.mark.parametrize("quote", ["no OCR was performed.", "Page 1", "1"])
def test_pdf_generated_notice_and_locator_substrings_are_not_issuer_evidence(research, quote):
    # Synthetic extracted-PDF markup tests citation boundaries, not PDF parsing.
    markup = (b"<p>[Extraction notice: Text extraction only; no OCR was performed.]</p>"
              b"<h2>Page 1</h2><p>Clearly synthetic source text follows the application locator.</p>")
    saved = documents.store_document(research["data"], research["case"]["id"], markup,
        "Synthetic extracted PDF structure", "text/html", cleaner_version="pdf-synthetic-boundary-test")
    text = documents.read_document(research["data"], saved["id"])["canonical_text"]
    start, end = documents.match_quote(text, quote)
    assert text[start:end] == quote  # A real match, rejected because its range is generated.
    response = synthetic_response()
    response["sentences"][0].update(quote=quote, ai_comment="Synthetic interpretation must remain hidden.")
    research["response"]["response_text"] = json.dumps(response)
    summary = finish(research, [saved["id"]])["summary"]
    item = summary["sentences"][0]
    assert item["status"] == "unresolved" and item["citation"] is None and item["ai_comment"] is None
    assert "not issuer evidence" in item["detail"]
    assert json.loads(rows(research, "model_runs")[0]["response_text"]) == response


def test_legacy_single_source_result_remains_readable_with_original_citation(research):
    current = finish(research)["summary"]
    data, case_id = research["data"], research["case"]["id"]
    prior = rows(research, "model_runs")[0]
    legacy = json.loads(rows(research, "summaries")[0]["result_json"])
    for key in ("sources", "warnings", "effort"):
        legacy.pop(key)
    for key in ("passages", "supplied_chars", "warnings"):
        legacy["source"].pop(key)
    for item in [legacy["reasoning"], *legacy["sentences"]]:
        item.pop("passage_id")
        item.pop("ai_comment")
    legacy.update(model="gpt-5.6-luna", prompt_version="subscription-summary-2")
    snapshot = json.loads(prior["snapshot_json"])
    snapshot.pop("retrieval")
    snapshot.pop("selected_document_ids")
    with closing(db.connect(data)) as connection, connection:
        run_id = connection.execute("INSERT INTO model_runs(case_id,task_type,request_key,request_json,source_json,"
            "snapshot_json,status,detail,created_at) VALUES (?,'summary','synthetic-legacy','{}',?,?,'completed',?,?)",
            (case_id, json.dumps(legacy["source"]), json.dumps(snapshot), "Synthetic legacy record.", prior["created_at"])).lastrowid
        identity = connection.execute("INSERT INTO summaries(case_id,run_id,created_at,result_json) VALUES (?,?,?,?)",
            (case_id, run_id, prior["created_at"], json.dumps(legacy))).lastrowid
        cases._setting(connection, f"summary_current_{case_id}", identity)
    stored = rows(research, "summaries")
    old = cases.summary_status(data, case_id)["summary"]
    assert old["id"] == identity and old["model"] == "gpt-5.6-luna" and old["stale"]
    assert cases.read_summary_evidence(data, identity, 0) == cases.read_summary_evidence(data, current["id"], 0)
    assert rows(research, "summaries") == stored and len(research["calls"]) == 1


def test_cancel_queued_request_sends_nothing_and_does_not_restart(research):
    cases.generate_summary(research["data"], research["case"]["id"], research["document"]["id"])
    cases.cancel_summary(research["data"], research["case"]["id"])
    function, arguments = research["queued"].pop()
    function(*arguments)
    assert rows(research, "model_runs") == []
    assert "Cancelled before" in cases.summary_status(research["data"], research["case"]["id"])["detail"]
    assert not research["calls"] and not research["queued"]
    assert rows(research, "summaries") == []


def test_cancel_after_submission_retains_unknown_usage_and_no_success(research, monkeypatch):
    def interrupted(_data, request, cancel_event, progress):
        research["calls"].append(request)
        progress("Synthetic provider accepted request.", submitted=True)
        cases.cancel_summary(research["data"], research["case"]["id"])
        assert cancel_event.is_set()
        return {**research["response"], "status": "cancelled", "response_text": None,
                "usage": None, "usage_uncertain": True, "error": "Synthetic cancellation."}
    monkeypatch.setattr(model, "generate", interrupted)
    finish(research)
    run, = rows(research, "model_runs")
    assert run["status"] == "cancelled" and run["usage_uncertain"]
    assert run["usage_json"] is None
    assert run["submitted_at"] is not None
    assert len(research["calls"]) == 1 and not research["queued"]
    assert rows(research, "summaries") == []


@pytest.mark.parametrize("finished", [True, False])
def test_closing_cancels_active_summary_and_bounds_its_wait(research, monkeypatch, finished):
    cases.generate_summary(research["data"], research["case"]["id"], research["document"]["id"])
    key = (str(research["data"].resolve()), research["case"]["id"])
    job = cases._summary_jobs[key]
    waits = []
    def bounded_wait(timeout):
        assert job["cancel"].is_set()
        assert 0 < timeout <= 60
        waits.append(timeout)
        return finished
    monkeypatch.setitem(job, "finished", SimpleNamespace(wait=bounded_wait, set=lambda: None))
    assert cases.cancel_summaries_on_close(research["data"]) is finished
    assert waits == [constants.MODEL_CANCEL_SECONDS + 8]
    function, arguments = research["queued"].pop()
    function(*arguments)
    assert not research["calls"] and not job["active"]


def test_restart_recovers_submitted_run_as_interrupted_without_retry(research, monkeypatch):
    def process_stopped(_data, request, _cancel_event, progress):
        research["calls"].append(request)
        progress("Synthetic provider accepted request.", submitted=True)
        raise KeyboardInterrupt("Synthetic process termination; no actual process is interrupted.")
    monkeypatch.setattr(model, "generate", process_stopped)
    cases.generate_summary(research["data"], research["case"]["id"], research["document"]["id"])
    function, arguments = research["queued"].pop()
    with pytest.raises(KeyboardInterrupt, match="Synthetic process termination"):
        function(*arguments)
    key = (str(research["data"].resolve()), research["case"]["id"])
    assert cases._summary_jobs[key]["finished"].is_set()
    assert rows(research, "model_runs")[0]["status"] == "submitted"
    cases.recover_model_runs(research["data"])
    run, = rows(research, "model_runs")
    assert run["status"] == "interrupted" and run["usage_uncertain"]
    assert run["usage_json"] is None
    assert len(research["calls"]) == 1 and not research["queued"]
    assert cases.summary_status(research["data"], research["case"]["id"])["summary"] is None


def test_migration_seven_upgrade_preserves_records_and_creates_restorable_backup(tmp_path):
    data = tmp_path / "isolated-prior-version"
    db.initialize(data, target_version=7)
    case = cases.create_case(data, "Synthetic old case", "Synthetic saved owner note")
    with closing(db.connect(data)) as connection, connection:
        connection.execute("INSERT INTO settings VALUES ('synthetic_preserved', 'original value')")
    db.initialize(data, target_version=8)
    with closing(db.connect(data)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        assert connection.execute("SELECT value FROM settings WHERE key = 'synthetic_preserved'").fetchone()[0] == "original value"
        assert connection.execute("SELECT question FROM cases WHERE id = ?", (case["id"],)).fetchone()[0] == case["question"]
        assert connection.execute("SELECT count(*) FROM model_runs").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM summaries").fetchone()[0] == 0
    snapshot, = (data / "backups").glob("pre-migration-*.db")
    with closing(sqlite3.connect(snapshot)) as previous:
        assert previous.execute("PRAGMA user_version").fetchone()[0] == 7
        assert previous.execute("SELECT question FROM cases").fetchone()[0] == case["question"]
