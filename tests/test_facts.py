"""Protected fact checks use saved Sandisk HTML and labelled synthetic proposals.

Research lives in isolated temporary copies and model calls are always replaced.
These tests verify persistence/evidence handling, not investment interpretations.
"""

import copy
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app import cases, constants, db, documents, model, prompts, worker


FACT_KEYS = {
    "parent_name", "spinco_name", "distribution_ratio", "record_date", "distribution_date",
    "listing_exchange", "expected_ticker", "when_issued_trading", "shares_outstanding_after",
    "debt_at_separation", "cash_at_separation", "cash_payment_to_parent",
    "pension_and_other_liabilities", "pro_forma_revenue", "pro_forma_operating_income",
    "pro_forma_ebitda", "conditions_to_distribution", "tax_free_condition", "management_equity_awards",
}


@pytest.fixture(scope="module")
def saved_filing(tmp_path_factory):
    data = tmp_path_factory.mktemp("facts-base")
    db.initialize(data)
    case = cases.create_case(data, "Sandisk saved-fixture fact check", "Synthetic owner note to preserve.")
    fixture = Path(__file__).parent / "fixtures" / "sandisk_20241125_d835366dex991.htm"
    document = documents.import_local(data, case["id"], fixture)
    return data, case, document


def rows(data, table):
    with closing(db.connect(data)) as connection:
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]


def unknown_proposal(key):
    return {"key": key, "value": None, "unit": None, "currency": None, "entity": None,
            "period": None, "basis": "unknown", "kind": "published", "finding": "not_found",
            "reason": "Not found in this deliberately bounded test selection.",
            "qualifications": None, "evidence": []}


def value_proposal(key, value, quote, **metadata):
    return {**unknown_proposal(key), "value": value, "basis": "not_applicable", "finding": "value",
            "reason": "Synthetic proposal for protected checks; not an accuracy judgement.",
            "evidence": [{"passage_id": 1, "quote": quote, "fields": ["value"]}], **metadata}


@pytest.fixture
def research(saved_filing, tmp_path, monkeypatch):
    template, case, document = saved_filing
    data = tmp_path / "research"
    shutil.copytree(template, data)
    state = {"data": data, "case": case, "document": document, "queued": [], "calls": [],
             "context": {"version": "synthetic-runtime", "config_hash": "a" * 64},
             "proposals": {}, "response_edit": None}
    quote = "Dear Western Digital Corporation Stockholder:"
    state["proposals"]["parent_name"] = value_proposal("parent_name", "Western Digital Corporation", quote)
    text = documents.read_document(data, document["id"])["canonical_text"]
    end = text.index("the record date for the distribution") + len("the record date for the distribution")
    state["proposals"]["record_date"] = {
        **unknown_proposal("record_date"), "finding": "blank_placeholder",
        "reason": "The selected preliminary date is a blank placeholder.",
        "evidence": [{"passage_id": 1, "quote": text[end - 250:end], "fields": ["value"]}],
    }

    def retrieve(_data, _case, document_id, queries):
        value = documents.read_document(data, document_id)
        text = value["canonical_text"][:8000]
        source = {key: value[key] for key in
                  ("name", "cleaner_version", "text_hash", "original_sha256", "filing_date")}
        with closing(db.connect(data)) as connection:
            source["accession_number"] = connection.execute("SELECT accession_number FROM documents WHERE id=?", (document_id,)).fetchone()[0]
        source.update(document_id=document_id, total_chars=len(value["canonical_text"]))
        keys = list(queries)
        return {"source": source, "passages": [{"id": 1, "document_id": document_id,
                "start_offset": 0, "end_offset": len(text), "text": text, "heading": "Test-selected source",
                "partial": len(text) < source["total_chars"]}],
                "key_passages": {key: [1] for key in keys},
                "searches": {key: list(queries[key]) for key in keys}, "warnings": []}

    def generate(_data, request, cancel_event, progress):
        state["calls"].append(copy.deepcopy(request))
        progress("Synthetic provider accepted request.", submitted=True)
        payload = json.loads(request["input_text"])
        response = {"facts": [copy.deepcopy(state["proposals"].get(key, unknown_proposal(key)))
                              for key in payload["keys"]]}
        if state["response_edit"]:
            state["response_edit"](response)
        return {"status": "completed", "response_text": json.dumps(response), "submitted": True,
                "usage": {"inputTokens": 120, "outputTokens": 30, "totalTokens": 150},
                "metadata": {}, "retries": [], "error": None}

    monkeypatch.setattr(documents, "retrieve_fact_passages", retrieve)
    monkeypatch.setattr(model, "runtime_context", lambda: copy.deepcopy(state["context"]))
    monkeypatch.setattr(model, "generate", generate)
    monkeypatch.setattr(worker, "submit", lambda function, *args: state["queued"].append((function, args)))
    return state


def finish(research):
    cases.extract_facts(research["data"], research["case"]["id"], research["document"]["id"])
    function, arguments = research["queued"].pop()
    function(*arguments)
    return cases.facts_status(research["data"], research["case"]["id"])


def fact(state, key):
    return next(row for row in state["rows"] if row["key"] == key)


def test_saved_real_luna_facts_validate_unchanged_answers_and_full_source_quotes(tmp_path):
    from bs4 import BeautifulSoup

    fixtures = Path(__file__).parent / "fixtures"
    fixture_path = fixtures / "sandisk_20241220_luna_facts.json"
    original_fixture = fixture_path.read_bytes()
    saved = json.loads(original_fixture)
    runs = {run["id"]: run for run in saved["runs"]}
    data = tmp_path / "real-response"
    db.initialize(data)
    case = cases.create_case(data, "Saved real December Sandisk response acceptance")
    document = documents.import_local(data, case["id"], fixtures / "sandisk_20241220_d835366dex991.htm")
    actual = documents.read_document(data, document["id"])
    for key in ("original_sha256", "text_hash", "cleaner_version"):
        assert actual[key] == saved["source"][key]
    assert len(actual["canonical_text"]) == saved["source"]["total_chars"]
    checked, proposals = {}, {}
    for run_id in (7, 8, 9):
        run = runs[run_id]
        request = json.loads(run["request_json"])
        assert request["prompt_version"] == "subscription-facts-2"
        source = json.loads(run["source_json"])
        source["document_id"] = document["id"]
        payload = json.loads(request["input_text"])
        payload["source"]["document_id"] = document["id"]
        for passage in payload["passages"]:
            passage["document_id"] = document["id"]
        request["input_text"] = json.dumps(payload)
        proposals.update({item["key"]: item for item in json.loads(run["response_text"])["facts"]})
        checked.update({item["key"]: item for item in cases._checked_facts(data, request, source, run["response_text"])})
    assert set(checked) == FACT_KEYS
    ratio = checked["distribution_ratio"]
    assert ratio["status"] == "extracted" and ratio["value"] == "one-third (1/3) of one share"
    assert ratio["unit"] == "Spinco shares received per parent share"
    revenue = checked["pro_forma_revenue"]
    assert revenue["status"] == "extracted" and revenue["value"] == "$ 1,883"
    assert (revenue["unit"], revenue["currency"], revenue["basis"]) == ("millions", "$", "pro_forma")
    assert revenue["entity"] == "The Flash Business of Western Digital Corporation"
    assert revenue["period"] == "For the three months ended September 27, 2024"
    for key in ("distribution_ratio", "pro_forma_revenue"):
        citation, = [entry["citation"] for entry in checked[key]["citations"]]
        opened = documents.read_citation(data, citation)
        marked = "".join(mark.get_text() for mark in BeautifulSoup(opened["html"], "html.parser").find_all("mark"))
        # Canonical text inserts table-cell separators that are not literal text nodes in marks.
        assert "".join(marked.split()) == "".join(citation["quote"].split())
        assert " ".join(citation["quote"].split()) == " ".join(proposals[key]["evidence"][0]["quote"].split())
        assert citation["document_id"] == document["id"] == citation["text_version_id"]
        assert citation["quote"] == actual["canonical_text"][citation["start_offset"]:citation["end_offset"]]
    assert checked["parent_name"]["status"] == "unknown" and checked["parent_name"]["value"] is None
    assert "Quote was not found" in checked["parent_name"]["reason"]
    tax = checked["tax_free_condition"]
    assert tax["status"] == "unknown" and tax["value"] is None
    assert "later prohibited actions" in tax["reason"]
    assert "actions prohibited by these covenants" in proposals["tax_free_condition"]["value"]
    local = runs[10]
    metadata = json.loads(local["metadata_json"])
    assert metadata["origin"] == "local_validation" and metadata["source_run_id"] == 8
    assert metadata["submitted"] is False and local["submitted_at"] is None and local["usage_json"] is None
    assert local["response_text"] == runs[8]["response_text"]
    original_tax = next(row for row in saved["current_facts"] if row["fact_key"] == "tax_free_condition" and row["run_id"] == 8)
    local_tax = next(row for row in saved["current_facts"] if row["fact_key"] == "tax_free_condition" and row["run_id"] == 10)
    assert json.loads(original_tax["value_json"])["value"] == proposals["tax_free_condition"]["value"]
    assert local_tax["status"] == "unknown" and json.loads(local_tax["value_json"])["value"] is None
    assert fixture_path.read_bytes() == original_fixture


def test_saved_real_v3_facts_preserve_valid_quotes_unknowns_and_timed_out_batch(saved_december_fact_passages):
    data, document, runs = saved_december_fact_passages
    fixture_path = Path(__file__).parent / "fixtures" / "sandisk_20241220_luna_facts.json"
    original_fixture = fixture_path.read_bytes()
    actual = documents.read_document(data, document["id"])
    checked, proposals = {}, {}
    for run_id in (11, 12):
        run = runs[run_id]
        assert run["status"] == "completed" and run["response_text"]
        request, source = json.loads(run["request_json"]), json.loads(run["source_json"])
        assert request["prompt_version"] == "subscription-facts-3"
        assert source["text_hash"] == actual["text_hash"]
        assert source["original_sha256"] == actual["original_sha256"]
        source["document_id"] = document["id"]
        payload = json.loads(request["input_text"])
        assert payload["retrieval_version"] == "fts-context-3"
        payload["source"]["document_id"] = document["id"]
        for passage in payload["passages"]:
            passage["document_id"] = document["id"]
        request["input_text"] = json.dumps(payload)
        proposals.update({item["key"]: item for item in json.loads(run["response_text"])["facts"]})
        checked.update({item["key"]: item for item in cases._checked_facts(data, request, source, run["response_text"])})
    assert len(checked) == 16 and set(checked) == set(constants.FACT_BATCHES[0] + constants.FACT_BATCHES[1])
    spinco, ratio, tax = (checked[key] for key in ("spinco_name", "distribution_ratio", "tax_free_condition"))
    assert spinco["status"] == "extracted" and spinco["value"] == "Sandisk Corporation"
    assert ratio["status"] == "extracted" and ratio["value"] == "one-third (1/3) of one share"
    assert ratio["unit"] == "Spinco shares received per parent share"
    assert ratio["qualifications"] == "Cash will be distributed in lieu of fractional shares"
    assert any("qualifications" in entry["fields"] and ratio["qualifications"] in " ".join(entry["citation"]["quote"].split())
               for entry in ratio["citations"])
    assert tax["status"] == "extracted" and tax["value"] == "WDC receives the Tax Opinion from its tax counsel, Skadden"
    assert "This condition may be waived by WDC in its sole discretion." in tax["qualifications"]
    assert "It is a condition to the completion of the distribution" in " ".join(tax["citations"][0]["citation"]["quote"].split())
    for key in ("record_date", "distribution_date"):
        assert checked[key]["status"] == "unknown" and checked[key]["value"] is None
        assert checked[key]["finding"] == "blank_placeholder"
    for key in ("parent_name", "shares_outstanding_after", "pension_and_other_liabilities",
                "cash_at_separation", "cash_payment_to_parent", "conditions_to_distribution", "management_equity_awards"):
        assert checked[key]["status"] == "unknown" and checked[key]["value"] is None
        assert proposals[key]["value"] is not None and "Validation:" in checked[key]["reason"]
    for record in checked.values():
        for entry in record["citations"]:
            citation = entry["citation"]
            assert citation["document_id"] == document["id"] == citation["text_version_id"]
            assert citation["document_hash"] == actual["original_sha256"]
            assert citation["quote"] == actual["canonical_text"][citation["start_offset"]:citation["end_offset"]]
            opened = documents.read_citation(data, citation)
            assert opened["citation"] == citation and "<mark>" in opened["html"]
    timeout = runs[13]
    assert timeout["status"] == "timed_out" and timeout["usage_uncertain"] == 1
    assert timeout["response_text"] is None and timeout["usage_json"] is None
    metadata = json.loads(timeout["metadata_json"])
    assert metadata["runtime_context"]["deadline_seconds"] == 60
    assert metadata["interrupt_requested"] is True and metadata["cancellation_confirmed"] is True
    assert metadata["turn_status"] == "interrupted"
    for run_id in (11, 12, 13):
        metadata = json.loads(runs[run_id]["metadata_json"])
        assert runs[run_id]["retry_count"] == 0 and metadata["retries"] == [] and metadata["tool_activity"] == []
        assert metadata["runtime_context"]["application_retries"] == 0
        assert metadata["auth"]["type"] == "chatgpt" and metadata["thread_settings"]["model"] == "gpt-5.6-luna"
    assert not any(row["run_id"] == 13 for row in json.loads(original_fixture)["current_facts"])
    assert fixture_path.read_bytes() == original_fixture


@pytest.fixture(scope="module")
def saved_december_fact_passages(tmp_path_factory):
    """Actual filing/passages, used for explicitly constructed structural proposals below."""
    data = tmp_path_factory.mktemp("constructed-facts")
    db.initialize(data)
    case = cases.create_case(data, "Constructed proposal checks against real saved passages")
    fixtures = Path(__file__).parent / "fixtures"
    document = documents.import_local(data, case["id"], fixtures / "sandisk_20241220_d835366dex991.htm")
    saved = json.loads((fixtures / "sandisk_20241220_luna_facts.json").read_bytes())
    return data, document, {run["id"]: run for run in saved["runs"]}


def test_saved_run14_financial_response_keeps_verified_revenue_and_unsupported_values_unknown(saved_december_fact_passages):
    data, document, runs = saved_december_fact_passages
    fixture = Path(__file__).parent / "fixtures" / "sandisk_20241220_luna_facts.json"
    original_fixture = fixture.read_bytes()
    run = runs[14]
    assert run["status"] == "completed" and run["response_text"]
    request, source = json.loads(run["request_json"]), json.loads(run["source_json"])
    payload = json.loads(request["input_text"])
    actual = documents.read_document(data, document["id"])
    assert source["document_id"] == payload["source"]["document_id"] == 5
    assert source["text_hash"] == actual["text_hash"]
    assert source["original_sha256"] == actual["original_sha256"]
    assert request["prompt_version"] == "subscription-facts-3"
    assert payload["retrieval_version"] == "fts-context-3"
    source["document_id"] = payload["source"]["document_id"] = document["id"]
    for passage in payload["passages"]:
        assert passage["document_id"] == 5
        passage["document_id"] = document["id"]
    request["input_text"] = json.dumps(payload)
    checked = {item["key"]: item for item in cases._checked_facts(data, request, source, run["response_text"])}
    assert set(checked) == {"pro_forma_revenue", "pro_forma_operating_income", "pro_forma_ebitda"}
    revenue = checked["pro_forma_revenue"]
    assert revenue["status"] == "extracted" and revenue["value"] == "1,883"
    assert (revenue["unit"], revenue["currency"], revenue["basis"]) == ("in millions", "$", "pro_forma")
    assert revenue["period"] == "For the three months ended September 27, 2024"
    assert revenue["entity"] == "The Flash Business of Western Digital Corporation"
    operating, ebitda = checked["pro_forma_operating_income"], checked["pro_forma_ebitda"]
    assert operating["status"] == ebitda["status"] == "unknown"
    assert operating["value"] is None and ebitda["value"] is None
    assert "Financial currency" in operating["reason"]
    assert all(term in ebitda["reason"] for term in ("qualifications", "Financial entity", "Financial period"))
    proposals = {item["key"]: item for item in json.loads(run["response_text"])["facts"]}
    assert proposals["pro_forma_operating_income"]["value"] == "283"
    assert proposals["pro_forma_ebitda"]["value"] == "400"
    for record in checked.values():
        for evidence in record["citations"]:
            citation = evidence["citation"]
            assert citation["document_id"] == citation["text_version_id"] == document["id"]
            assert citation["quote"] == actual["canonical_text"][citation["start_offset"]:citation["end_offset"]]
            assert documents.read_citation(data, citation)["citation"] == citation
    assert fixture.read_bytes() == original_fixture


def check_constructed_proposal(saved_december_fact_passages, run_id, proposal):
    data, document, runs = saved_december_fact_passages
    request = json.loads(runs[run_id]["request_json"])
    source = json.loads(runs[run_id]["source_json"])
    source["document_id"] = document["id"]
    payload = json.loads(request["input_text"])
    payload["keys"] = [proposal["key"]]
    payload["source"]["document_id"] = document["id"]
    for passage in payload["passages"]:
        passage["document_id"] = document["id"]
    request["input_text"] = json.dumps(payload)
    record, = cases._checked_facts(data, request, source, json.dumps({"facts": [proposal]}))
    return record


@pytest.mark.parametrize("problem", [None, "missing_line", "reordered_words"])
def test_constructed_multiline_qualifications_require_each_exact_supported_line(saved_december_fact_passages, problem):
    _, _, runs = saved_december_fact_passages
    proposal = next(item for item in json.loads(runs[7]["response_text"])["facts"] if item["key"] == "distribution_ratio")
    proposal["reason"] = "Constructed structural proposal using real passages; not a saved Luna answer."
    payload = json.loads(json.loads(runs[7]["request_json"])["input_text"])
    passage = next(item for item in payload["passages"] if item["id"] == 8)
    cash = "Cash will be distributed in lieu of fractional shares"
    timing = passage["text"][passage["text"].index("Please note that if you sell"):passage["text"].index(" Distributed Securities")]
    proposal["qualifications"] = cash + "\n" + timing
    proposal["evidence"].append({"passage_id": 8, "quote": cash, "fields": ["qualifications"]})
    if problem != "missing_line":
        proposal["evidence"].append({"passage_id": 8, "quote": timing, "fields": ["qualifications"]})
    if problem == "reordered_words":
        proposal["qualifications"] = "fractional shares will be distributed in lieu of Cash\n" + timing
    record = check_constructed_proposal(saved_december_fact_passages, 7, proposal)
    if problem:
        assert record["status"] == "unknown" and record["value"] is None
        assert "qualifications" in record["reason"]
    else:
        assert record["status"] == "extracted" and record["value"] == proposal["value"]
        assert record["qualifications"] == cash + "\n" + timing
        assert len([item for item in record["citations"] if item["fields"] == ["qualifications"]]) == 2


@pytest.mark.parametrize("problem", [None, "split_period", "value", "unit", "currency", "period", "wrong_date"])
def test_constructed_revenue_keeps_exact_table_header_and_separate_currency(saved_december_fact_passages, problem):
    _, _, runs = saved_december_fact_passages
    proposal = next(item for item in json.loads(runs[9]["response_text"])["facts"] if item["key"] == "pro_forma_revenue")
    proposal["reason"] = "Constructed structural proposal using real table/header; not a saved Luna answer."
    complete = proposal["evidence"][0]["quote"]
    header, amount = complete.split(" Revenue, net ", 1)
    proposal["value"] = "1,883"
    proposal["evidence"] = [
        {"passage_id": 26, "quote": header, "fields": ["unit", "entity", "period", "basis"]},
        {"passage_id": 26, "quote": "Revenue, net " + amount, "fields": ["value", "currency"]},
    ]
    if problem in ("split_period", "wrong_date"):
        proposal["period"] = "For the three months ended\nSeptember " + ("27" if problem == "split_period" else "26") + ", 2024"
    elif problem:
        proposal[problem] = {"value": "1,88", "unit": "billions", "currency": "EUR",
                             "period": "September 27, 2024 For the three months ended"}[problem]
    record = check_constructed_proposal(saved_december_fact_passages, 9, proposal)
    if problem and problem != "split_period":
        assert record["status"] == "unknown" and record["value"] is None
        assert "Validation:" in record["reason"]
    else:
        assert record["status"] == "extracted" and record["value"] == "1,883"
        assert (record["unit"], record["currency"], record["basis"]) == ("millions", "$", "pro_forma")
        assert record["entity"] == "The Flash Business of Western Digital Corporation"
        assert record["period"] == ("For the three months ended\nSeptember 27, 2024" if problem == "split_period"
                                    else "For the three months ended September 27, 2024")
        assert len(record["citations"]) == 2


@pytest.mark.parametrize("unit", ["shares of common stock", "shares of preferred stock", "millions"])
def test_constructed_share_unit_omits_possessive_only_for_common_stock(saved_december_fact_passages, unit):
    _, _, runs = saved_december_fact_passages
    proposal = next(item for item in json.loads(runs[7]["response_text"])["facts"] if item["key"] == "shares_outstanding_after")
    proposal["reason"] = "Constructed unit variant over a real quotation; not an unmodified Luna answer."
    proposal["unit"] = unit
    exact_quote = proposal["evidence"][0]["quote"]
    assert "shares of its common stock" in exact_quote
    record = check_constructed_proposal(saved_december_fact_passages, 7, proposal)
    if unit == "shares of common stock":
        assert record["status"] == "extracted" and record["value"] == "approximately 144 million"
        assert "shares of its common stock" in record["citations"][0]["citation"]["quote"]
    else:
        assert record["status"] == "unknown" and record["value"] is None
        assert "Financial unit" in record["reason"]


def test_all_nineteen_keys_blank_and_not_found_are_distinct_and_evidence_reopens(research):
    state = finish(research)
    assert {row["key"] for row in state["rows"]} == FACT_KEYS
    parent = fact(state, "parent_name")["effective"]
    assert parent["value"] == "Western Digital Corporation" and parent["status"] == "extracted"
    assert parent["origin"] == "model"
    opened = cases.read_fact_evidence(research["data"], parent["id"], 0)
    assert "<mark>" in opened["html"]
    assert opened["citation"]["document_id"] == research["document"]["id"]
    assert documents.read_citation(research["data"], opened["citation"]) == opened
    blank = fact(state, "record_date")["effective"]
    absent = fact(state, "debt_at_separation")["effective"]
    assert blank["value"] is None and blank["finding"] == "blank_placeholder" and blank["status"] == "unknown"
    assert absent["value"] is None and absent["finding"] == "not_found" and absent["status"] == "unknown"
    assert blank["reason"] and absent["reason"]
    assert cases.list_cases(research["data"])[0]["question"] == research["case"]["question"]


@pytest.mark.parametrize("problem", ["missing_quote", "ambiguous_quote", "value_outside_quote", "wrong_passage"])
def test_unverified_or_incomplete_evidence_keeps_display_unknown_and_raw_proposal(research, problem):
    proposal = research["proposals"]["parent_name"]
    if problem == "missing_quote":
        proposal["evidence"][0]["quote"] = "Synthetic words absent from the real filing."
    elif problem == "ambiguous_quote":
        proposal["evidence"][0]["quote"] = "Western Digital Corporation"
    elif problem == "value_outside_quote":
        proposal["value"] = "Synthetic unsupported proposed parent"
    else:
        proposal["evidence"][0]["passage_id"] = 9999
    state = finish(research)
    record = fact(state, "parent_name")["effective"]
    assert record["status"] == "unknown" and record["value"] is None
    assert record["reason"]
    raw = [json.loads(run["response_text"]) for run in rows(research["data"], "model_runs") if run["response_text"]]
    proposed = next(item for response in raw for item in response["facts"] if item["key"] == "parent_name")
    assert proposed == proposal


@pytest.mark.parametrize("change", ["retrieval", "runtime", "prompt"])
def test_unchanged_batches_reuse_cache_but_effective_changes_make_new_requests(research, monkeypatch, change):
    first = finish(research)
    prior_calls = len(research["calls"])
    assert prior_calls == 3
    cached = finish(research)
    assert len(research["calls"]) == prior_calls
    assert fact(cached, "parent_name")["effective"]["id"] == fact(first, "parent_name")["effective"]["id"]
    original_facts, original_runs = rows(research["data"], "facts"), rows(research["data"], "model_runs")
    if change == "retrieval":
        monkeypatch.setattr(constants, "FACT_RETRIEVAL_VERSION", "synthetic-next-retrieval")
    elif change == "runtime":
        research["context"]["config_hash"] = "b" * 64
    else:
        monkeypatch.setattr(prompts, "FACT_PROMPT_VERSION", "synthetic-next-fact-prompt")
    preserved = cases.facts_status(research["data"], research["case"]["id"])
    if change in ("retrieval", "prompt"):
        assert any("earlier extraction rules" in warning for warning in preserved["warnings"])
    assert rows(research["data"], "facts") == original_facts
    assert rows(research["data"], "model_runs") == original_runs and len(research["calls"]) == prior_calls
    finish(research)
    assert len(research["calls"]) > prior_calls
    assert research["calls"][0] != research["calls"][prior_calls]


@pytest.mark.parametrize("problem", ["model_checked", "missing_key", "extra_key"])
def test_invalid_batch_structure_cannot_create_checked_or_successful_proposals(research, problem):
    def edit(response):
        if problem == "model_checked":
            response["facts"][0]["status"] = "checked"
        elif problem == "missing_key":
            response["facts"].pop()
        else:
            response["facts"].append({**unknown_proposal("invented_future_key")})
    research["response_edit"] = edit
    finish(research)
    assert rows(research["data"], "facts") == []
    runs = rows(research["data"], "model_runs")
    assert runs and all(run["status"] == "failed" for run in runs)
    assert not research["queued"]


def synthetic_financial_source(research, tmp_path, printed_value="125.50"):
    source = tmp_path / "synthetic-metadata.txt"
    quote = f"Synthetic Spinco pro forma revenue for FY2024 is {printed_value} million USD."
    date_quote = "The hypothetical record date is 2024-11-25."
    source.write_text("Synthetic structural fixture, not a real filing.\n" + quote + "\n" + date_quote, encoding="utf-8")
    research["document"] = documents.import_local(research["data"], research["case"]["id"], source)
    proposal = value_proposal("pro_forma_revenue", printed_value, quote, unit="million", currency="USD",
                             entity="Synthetic Spinco", period="FY2024", basis="pro_forma")
    proposal["evidence"][0]["fields"] = ["value", "unit", "currency", "entity", "period", "basis"]
    research["proposals"]["pro_forma_revenue"] = proposal
    research["proposals"]["record_date"] = value_proposal("record_date", "2024-11-25", date_quote)
    return proposal


def test_financial_units_currency_entity_period_basis_and_date_survive_storage(research, tmp_path):
    proposal = synthetic_financial_source(research, tmp_path)
    state = finish(research)
    record = fact(state, "pro_forma_revenue")["effective"]
    assert record["status"] == "extracted"
    for field in ("value", "unit", "currency", "entity", "period", "basis", "kind"):
        assert record[field] == proposal[field]
    assert isinstance(record["value"], str)
    date = fact(state, "record_date")["effective"]
    assert date["value"] == "2024-11-25" and date["status"] == "extracted"
    reopened = cases.facts_status(research["data"], research["case"]["id"])
    assert fact(reopened, "pro_forma_revenue")["effective"] == record


@pytest.mark.parametrize("field", ["unit", "currency", "entity", "period", "basis"])
def test_missing_or_unsupported_financial_metadata_cannot_become_usable_value(research, tmp_path, field):
    proposal = synthetic_financial_source(research, tmp_path)
    proposal[field] = "historical" if field == "basis" else None
    state = finish(research)
    record = fact(state, "pro_forma_revenue")["effective"]
    assert record["value"] is None and record["status"] == "unknown"
    assert record["reason"]


def test_false_blank_claim_requires_an_actual_placeholder_in_its_quote(research):
    proposal = research["proposals"]["record_date"]
    proposal["reason"] = "Synthetic erroneous blanket claim."
    proposal["evidence"] = copy.deepcopy(research["proposals"]["parent_name"]["evidence"])
    record = fact(finish(research), "record_date")["effective"]
    assert record["value"] is None and record["status"] == "unknown"
    assert "Validation:" in record["reason"] and "placeholder" in record["reason"]


def test_literal_placeholder_proposed_as_a_value_remains_unknown(research, tmp_path):
    quote = "Synthetic record date: [●]."
    path = tmp_path / "synthetic-placeholder.txt"
    path.write_text("Synthetic structural fixture, not a real filing.\n" + quote, encoding="utf-8")
    research["document"] = documents.import_local(research["data"], research["case"]["id"], path)
    research["proposals"]["record_date"] = value_proposal("record_date", "[●]", quote)
    record = fact(finish(research), "record_date")["effective"]
    assert record["value"] is None and record["status"] == "unknown"
    assert record["finding"] == "blank_placeholder" and "placeholder" in record["reason"]


@pytest.mark.parametrize("printed_value", ["125.50", "125,000"])
def test_numeric_prefix_is_not_accepted_as_the_whole_quoted_amount(research, tmp_path, printed_value):
    proposal = synthetic_financial_source(research, tmp_path, printed_value)
    proposal["value"] = "125"
    record = fact(finish(research), "pro_forma_revenue")["effective"]
    assert record["value"] is None and record["status"] == "unknown"
    assert "proposed value does not appear" in record["reason"]


@pytest.mark.parametrize("unit", ["Spinco shares received per parent share", "Parent shares per Spinco share"])
def test_distribution_ratio_direction_is_explicit_and_reversed_direction_is_rejected(research, tmp_path, unit):
    quote = "Synthetic ratio: one-third (1/3) Spinco shares are received for each parent share."
    path = tmp_path / "synthetic-ratio.txt"
    path.write_text("Hypothetical structural fixture, not a real filing.\n" + quote, encoding="utf-8")
    research["document"] = documents.import_local(research["data"], research["case"]["id"], path)
    research["proposals"]["distribution_ratio"] = value_proposal("distribution_ratio", "one-third (1/3)", quote, unit=unit)
    record = fact(finish(research), "distribution_ratio")["effective"]
    if unit == "Spinco shares received per parent share":
        assert record["status"] == "extracted" and record["value"] == "one-third (1/3)"
    else:
        assert record["status"] == "unknown" and record["value"] is None
        assert "direction" in record["reason"]


def test_unsupported_qualification_does_not_make_a_known_value_usable(research):
    research["proposals"]["parent_name"]["qualifications"] = "Synthetic qualification absent from supplied evidence."
    record = fact(finish(research), "parent_name")["effective"]
    assert record["status"] == "unknown" and record["value"] is None
    assert "Validation:" in record["reason"]


def test_human_check_and_correction_append_history_surviving_cache_and_conflicting_run(research):
    first = fact(finish(research), "parent_name")["effective"]
    with pytest.raises(ValueError):
        cases.check_fact(research["data"], research["case"]["id"], first["id"], "")
    checked_state = cases.check_fact(research["data"], research["case"]["id"], first["id"], "Synthetic owner source check.")
    checked = fact(checked_state, "parent_name")["effective"]
    assert checked["status"] == "checked" and checked["origin"] == "human" and checked["previous_id"] == first["id"]
    corrected_state = cases.correct_fact(research["data"], case_id=research["case"]["id"], key="parent_name",
        previous_id=checked["id"], value="Synthetic owner assumption", unit=None, currency=None, entity=None,
        period=None, basis="not_applicable", kind="assumption", qualifications=None,
        reason="Synthetic owner correction reason; keep it.", document_id=first["document_id"], quote=None)
    corrected = fact(corrected_state, "parent_name")["effective"]
    assert corrected["id"] != checked["id"] and corrected["previous_id"] == checked["id"]
    count = len(research["calls"])
    cached = fact(finish(research), "parent_name")
    assert len(research["calls"]) == count
    assert cached["effective"]["id"] == corrected["id"]
    research["context"]["config_hash"] = "c" * 64
    later = fact(finish(research), "parent_name")
    assert len(research["calls"]) > count and later["conflict"]
    assert later["effective"]["id"] == corrected["id"]
    assert later["effective"]["reason"] == "Synthetic owner correction reason; keep it."
    history = {item["id"]: item for item in later["history"]}
    assert {first["id"], checked["id"], corrected["id"]} <= history.keys()
    assert history[first["id"]]["value"] == first["value"]


def test_new_source_version_keeps_distinct_proposals_and_original_evidence(research):
    old_document = research["document"]
    first = fact(finish(research), "parent_name")["effective"]
    evidence = cases.read_fact_evidence(research["data"], first["id"], 0)
    content = b'Synthetic replacement-version fixture, not a real filing. Dear Synthetic Parent Stockholder:'
    research["document"] = documents.store_document(research["data"], research["case"]["id"], content,
        "synthetic-version.txt", "text/plain", logical_document_id=old_document["logical_document_id"])
    research["proposals"]["parent_name"] = value_proposal("parent_name", "Synthetic Parent", "Dear Synthetic Parent Stockholder:")
    later = fact(finish(research), "parent_name")
    assert later["effective"]["value"] == "Synthetic Parent"
    assert {old_document["id"], research["document"]["id"]} <= {item["document_id"] for item in later["history"]}
    assert cases.read_fact_evidence(research["data"], first["id"], 0) == evidence
    assert documents.original_path(research["data"], old_document["id"]).read_bytes() != content


@pytest.mark.parametrize("interrupted", [False, True])
def test_partial_batches_preserve_completed_facts_and_never_restart_after_cancel_or_interruption(research, monkeypatch, interrupted):
    ordinary = model.generate
    def stop_second(data, request, cancel_event, progress):
        if len(research["calls"]) == 1:
            research["calls"].append(copy.deepcopy(request))
            progress("Synthetic second request accepted.", submitted=True)
            if interrupted:
                raise KeyboardInterrupt("Synthetic process interruption.")
            cases.cancel_facts(data, research["case"]["id"])
            assert cancel_event.is_set()
            return {"status": "cancelled", "response_text": None, "submitted": True, "usage": None,
                    "metadata": {}, "retries": [], "error": "Synthetic cancellation."}
        return ordinary(data, request, cancel_event, progress)
    monkeypatch.setattr(model, "generate", stop_second)
    if interrupted:
        with pytest.raises(KeyboardInterrupt, match="Synthetic process interruption"):
            finish(research)
        cases.recover_model_runs(research["data"])
    else:
        finish(research)
    state = cases.facts_status(research["data"], research["case"]["id"])
    assert len(research["calls"]) == 2 and not research["queued"]
    assert fact(state, "parent_name")["effective"]["status"] == "extracted"
    assert fact(state, "pro_forma_ebitda")["effective"] is None
    runs = rows(research["data"], "model_runs")
    assert [run["status"] for run in runs] == ["completed", "interrupted" if interrupted else "cancelled"]
    assert runs[-1]["usage_uncertain"] and runs[-1]["usage_json"] is None


def test_migration_nine_preserves_prior_run_ids_summary_links_and_backup(tmp_path):
    data = tmp_path / "prior"
    db.initialize(data, target_version=8)
    case = cases.create_case(data, "Synthetic migration case", "Synthetic owner note")
    with closing(db.connect(data)) as connection, connection:
        connection.execute("INSERT INTO settings VALUES ('synthetic_preserved', 'original value')")
        connection.execute("INSERT INTO model_runs(id,case_id,task_type,request_key,request_json,source_json,"
                           "snapshot_json,status,detail,created_at,response_text) VALUES "
                           "(41,?,'summary','synthetic-key','{}','{}','{}','completed',"
                           "'Synthetic saved result','synthetic-date','synthetic-response')", (case["id"],))
        connection.execute("INSERT INTO summaries(id,case_id,run_id,created_at,result_json) "
                           "VALUES (12,?,41,'synthetic-date','{}')", (case["id"],))
    original_runs, original_summaries = rows(data, "model_runs"), rows(data, "summaries")
    db.initialize(data, target_version=9)
    assert rows(data, "model_runs") == original_runs
    assert rows(data, "summaries") == original_summaries
    with closing(db.connect(data)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT value FROM settings WHERE key='synthetic_preserved'").fetchone()[0] == "original value"
        assert connection.execute("SELECT question FROM cases WHERE id=?", (case["id"],)).fetchone()[0] == case["question"]
    snapshot, = (data / "backups").glob("pre-migration-*.db")
    with closing(sqlite3.connect(snapshot)) as previous:
        assert previous.execute("PRAGMA user_version").fetchone()[0] == 8
        assert previous.execute("SELECT run_id FROM summaries WHERE id=12").fetchone()[0] == 41
        assert previous.execute("SELECT response_text FROM model_runs WHERE id=41").fetchone()[0] == "synthetic-response"
