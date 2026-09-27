"""Real saved source text; deliberately synthetic replies test mechanics, not accuracy."""

import copy
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import Event

import pytest

from app import cases, constants, db, documents, model, prompts, research, worker

SECTIONS = ('company', 'event', 'conditions', 'dates', 'financials', 'risks', 'opportunity', 'unknowns')


def reply(request):
    payload = json.loads(request['input_text'])
    passages = payload.get('passages', payload.get('original_evidence', []))
    item = {'section': 'company', 'text': 'Synthetic claim for quotation mechanics only.',
            'status': 'unresolved', 'passage_id': None, 'quote': None, 'ai_comment': None}
    if passages:
        passage = passages[0]
        # A long exact source fragment avoids choosing an ambiguous repeated name.
        quote = passage['text'][200:500] if len(passage['text']) > 550 else passage['text']
        item.update(status='sourced', passage_id=passage['id'], quote=quote)
    items = [item]
    if 'original_evidence' in payload:
        items += [{'section': section, 'text': 'Synthetic unresolved section.', 'status': 'unresolved',
                   'passage_id': None, 'quote': None, 'ai_comment': None} for section in SECTIONS[1:]]
    return json.dumps({'items': items, 'limitations': ['Synthetic response; semantic interpretation is not tested.']})


@pytest.fixture
def trial(tmp_path, monkeypatch):
    db.initialize(tmp_path)
    case = cases.create_case(tmp_path, 'Real filing with synthetic model results')
    original = (Path(__file__).parent / 'fixtures' / 'sandisk_20241125_d835366dex991.htm').read_bytes()
    doc = documents.store_document(tmp_path, case['id'], original, 'Saved real Sandisk fixture', 'text/html')
    queue, calls = [], []
    monkeypatch.setattr(model, 'runtime_context', lambda *args: {'runtime': 'synthetic status fixture'})
    monkeypatch.setattr(worker, 'submit', lambda function, *args: queue.append((function, args)))
    def generate(data_dir, request, event, progress):
        calls.append(copy.deepcopy(request))
        progress('Synthetic submission.', submitted=True)
        return {'status': 'completed', 'submitted': True, 'response_text': reply(request),
                'usage': {'total': {'inputTokens': 100, 'outputTokens': 50}}, 'retries': []}
    monkeypatch.setattr(model, 'generate', generate)
    return {'data': tmp_path, 'case': case['id'], 'doc': doc['id'], 'queue': queue, 'calls': calls}


def run(trial):
    plan = research.prepare(trial['data'], trial['case'], [trial['doc']])
    research.start(trial['data'], trial['case'], [trial['doc']], plan['plan_key'])
    function, args = trial['queue'].pop()
    function(*args)
    return research.status(trial['data'], trial['case'])


def test_all_real_canonical_text_is_planned_once_with_bounded_extra_context(trial):
    result = documents.plan_review_passages(trial['data'], trial['case'], trial['doc'])
    position = 0
    for batch in result['batches']:
        assert batch['start_offset'] == position
        assert batch['end_offset'] > position
        primary = batch['passages'][0]
        assert primary['start_offset'] <= position < primary['end_offset']
        assert len(primary['text']) <= constants.REVIEW_BATCH_CHARS + constants.REVIEW_OVERLAP_CHARS
        assert sum(len(value['text']) for value in batch['passages']) <= constants.REVIEW_BATCH_CHARS + constants.REVIEW_OVERLAP_CHARS + constants.REVIEW_TABLE_CONTEXT_CHARS
        position = batch['end_offset']
    assert position == result['source']['total_chars']
    assert any(value['warnings'] for value in result['batches'])  # Real large filing tables.


def test_completed_report_exact_evidence_cache_and_owner_history(trial):
    from app.bridge import Bridge
    research._save(trial['data'], f"research_error_{trial['case']}", 'Synthetic previous failure')
    with closing(db.connect(trial['data'])) as connection, connection:
        connection.execute("INSERT INTO facts(case_id,fact_key,origin,status,created_at,value_json,evidence_json) VALUES (?,'parent_name','human','checked','fixture',?,'[]')",
            (trial['case'], json.dumps({'value': 'Synthetic owner correction', 'reason': 'Preserve this test history', 'kind': 'assumption'})))
        original_facts = [dict(value) for value in connection.execute('SELECT * FROM facts')]
    state = run(trial)
    assert state['error'] is None
    report = state['report']
    assert report and not report['stale'] and len(report['items']) == 8
    assert report['coverage'][0]['reviewed_chars'] == report['coverage'][0]['total_chars']
    assert len(trial['calls']) == state['plan']['batch_count'] + 1
    citation = report['items'][0]['citation']
    assert citation is not None
    opened = research.read_evidence(trial['data'], report['id'], 0)
    assert opened['citation'] == citation and '<mark>' in opened['html']
    count = len(trial['calls'])
    again = run(trial)
    assert again['report']['id'] == report['id'] and len(trial['calls']) == count
    with closing(db.connect(trial['data'])) as connection:
        assert connection.execute('SELECT count(*) FROM summaries').fetchone()[0] == 0
        assert [dict(value) for value in connection.execute('SELECT * FROM facts')] == original_facts
        assert connection.execute('SELECT count(*) FROM scenarios').fetchone()[0] == 0
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    assert all(value['usage'] is not None for value in report['usage'])
    assert all('Synthetic owner correction' in value['input_text'] for value in trial['calls'])
    bridge = Bridge(trial['data'])
    selected = {'case_id': trial['case'], 'document_ids': [trial['doc']]}
    preview = bridge.prepare_research(selected)
    assert preview['error'] is None and preview['plan']['cached_batches'] == state['plan']['batch_count']
    saved_state = bridge.research_status({'case_id': trial['case']})
    assert saved_state['state_valid'] and saved_state['report']['id'] == report['id']
    opened = bridge.read_research_evidence({'report_id': report['id'], 'index': 0})
    assert opened['error'] is None and opened['document']['citation'] == citation
    refused = bridge.start_research(selected)
    assert refused['error'] is not None and not refused['state_valid'] and not trial['queue']
    assert bridge.research_status({'case_id': trial['case']})['report']['id'] == report['id']
    json.dumps(bridge.research_status({'case_id': trial['case']}))


def test_preview_rejects_changed_owner_notes_and_oversize_selection(trial, monkeypatch):
    plan = research.prepare(trial['data'], trial['case'], [trial['doc']])
    with closing(db.connect(trial['data'])) as connection, connection:
        connection.execute('UPDATE cases SET question=? WHERE id=?', ('Owner correction must survive.', trial['case']))
    with pytest.raises(ValueError, match='Preview'):
        research.start(trial['data'], trial['case'], [trial['doc']], plan['plan_key'])
    monkeypatch.setattr(constants, 'REVIEW_MAX_BATCHES', 1)
    plan = research.prepare(trial['data'], trial['case'], [trial['doc']])
    assert not plan['allowed'] and plan['blockers']
    with pytest.raises(ValueError, match='limit'):
        research.start(trial['data'], trial['case'], [trial['doc']], plan['plan_key'])
    assert not trial['calls']


def test_failed_quote_stays_unknown_and_raw_response_preserved(trial, monkeypatch):
    def bad(data_dir, request, event, progress):
        progress('Synthetic submission.', submitted=True)
        value = json.loads(reply(request))
        value['items'][0].update(quote='This deliberately synthetic quotation is absent from the saved filing.',
                                  ai_comment='This interpretation must be hidden.')
        return {'status': 'completed', 'submitted': True, 'response_text': json.dumps(value)}
    monkeypatch.setattr(model, 'generate', bad)
    state = run(trial)
    assert state['report']['items'][0]['citation'] is None
    assert state['report']['items'][0]['status'] == 'unresolved'
    assert state['report']['items'][0]['ai_comment'] is None
    with closing(db.connect(trial['data'])) as connection:
        rows = connection.execute('SELECT response_text,usage_uncertain FROM model_runs').fetchall()
    assert all('deliberately synthetic' in value['response_text'] for value in rows)
    assert all(value['usage_uncertain'] == 1 for value in rows)


def test_cancel_preserves_completed_batch_then_manual_continue_reuses_it(trial, monkeypatch):
    normal = model.generate
    def cancel_second(data_dir, request, event, progress):
        if len(trial['calls']) == 1:
            progress('Synthetic second submission.', submitted=True)
            event.set()
            return {'status': 'cancelled', 'submitted': True}
        return normal(data_dir, request, event, progress)
    monkeypatch.setattr(model, 'generate', cancel_second)
    state = run(trial)
    assert state['report'] is None
    assert state['plan']['batches'][0]['status'] == 'completed'
    assert state['plan']['batches'][1]['status'] == 'cancelled'
    assert any(value['usage_uncertain'] for value in state['runs'])
    monkeypatch.setattr(model, 'generate', normal)
    state = run(trial)
    assert state['report'] and state['plan']['batches'][0]['cached']


def test_same_document_versions_cannot_be_combined_and_source_change_marks_stale(trial):
    first = run(trial)['report']
    with closing(db.connect(trial['data'])) as connection:
        logical = connection.execute('SELECT logical_document_id FROM documents WHERE id=?', (trial['doc'],)).fetchone()[0]
    replacement = documents.store_document(trial['data'], trial['case'], b'Synthetic later amendment. New unknown terms.',
                                          'Synthetic amendment', 'text/plain', logical_document_id=logical)
    with pytest.raises(ValueError, match='one version'):
        research.prepare(trial['data'], trial['case'], [trial['doc'], replacement['id']])
    state = research.status(trial['data'], trial['case'])
    assert state['report']['id'] == first['id'] and state['report']['stale']
    assert documents.read_citation(trial['data'], first['items'][0]['citation'])['citation'] == first['items'][0]['citation']


def test_synthesis_does_not_silently_discard_findings(trial, monkeypatch):
    monkeypatch.setattr(constants, 'REVIEW_SYNTHESIS_CHARS', 100)
    state = run(trial)
    assert state['report'] is None and 'no findings were silently discarded' in state['error']
    assert len(trial['calls']) == state['plan']['batch_count']
    assert all(value['status'] == 'completed' for value in state['plan']['batches'])
    monkeypatch.setattr(research, '_jobs', {})
    reopened = research.status(trial['data'], trial['case'])
    assert reopened['error'] == state['error'] and reopened['detail'] == state['error']


def test_failed_originals_not_selected_collection_stays_visible(trial, monkeypatch):
    from app import sources
    result = {'url': 'https://example.test/public', 'documents': [
        {'document_id': trial['doc'], 'status': 'searchable', 'name': 'Real saved source'},
        {'document_id': 9999, 'status': 'processing failed', 'name': 'Synthetic failed original'}],
        'gaps': ['Synthetic failed processing remains visible.'], 'cancelled': False, 'checked_at': 'fixture', 'request_count': 0}
    monkeypatch.setattr(sources, 'collect_sources', lambda *args: result)
    research.collect(trial['data'], trial['case'], result['url'])
    function, args = trial['queue'].pop()
    function(*args)
    state = research.status(trial['data'], trial['case'])
    assert state['selected_document_ids'] == [trial['doc']]
    assert state['collection']['documents'][1]['status'] == 'processing failed'
    assert not trial['calls']


def test_refused_busy_start_preserves_saved_plan_and_selection(trial, monkeypatch):
    research._save(trial['data'], f"research_plan_{trial['case']}", {'sentinel': 'old plan'})
    research._save(trial['data'], f"research_selection_{trial['case']}", [])
    research._save(trial['data'], f"research_error_{trial['case']}", 'Keep previous failure')
    plan = research.prepare(trial['data'], trial['case'], [trial['doc']])
    def busy(*args):
        raise ValueError('Background worker is busy.')
    monkeypatch.setattr(worker, 'submit', busy)
    with pytest.raises(ValueError, match='busy'):
        research.start(trial['data'], trial['case'], [trial['doc']], plan['plan_key'])
    state = research.status(trial['data'], trial['case'])
    assert state['plan'] == {'sentinel': 'old plan'} and state['selected_document_ids'] == []
    assert state['error'] == 'Keep previous failure'
    assert not trial['calls']


def test_final_sections_and_nonblank_fields_are_enforced_without_repair(trial):
    plan, requests, context, runtime = research._prepare(trial['data'], trial['case'], [trial['doc']])
    with pytest.raises(ValueError, match='required section'):
        research._checked_items(trial['data'], reply(requests[0]), requests[0]['source_snapshot'], 'report')
    item = json.loads(reply(requests[0]))['items'][0]
    for key in ('text', 'quote'):
        with pytest.raises(ValueError, match='non-whitespace'):
            prompts.ReviewItem.model_validate({**item, key: '   '})
    # The raw counterpart is retained but is not a separate omitted logical source.
    assert not any('is not selected' in value for value in plan['warnings'])


def test_populated_migration_preserves_all_parent_and_child_ids_and_recovery(tmp_path):
    db.initialize(tmp_path, 10)
    with closing(db.connect(tmp_path)) as connection, connection:
        connection.execute("INSERT INTO cases(id,title,created_at) VALUES (1,'Synthetic migration case','fixture')")
        for identity, kind in ((1,'summary'), (2,'facts'), (3,'qa')):
            connection.execute("INSERT INTO model_runs(id,case_id,task_type,request_key,request_json,source_json,snapshot_json,status,detail,created_at) VALUES (?,1,?,'fixture','{}','{}','{}','completed','fixture','fixture')", (identity,kind))
        connection.execute("INSERT INTO summaries VALUES (5,1,1,'fixture','{}')")
        connection.execute("INSERT INTO facts(id,case_id,fact_key,run_id,origin,status,created_at,value_json,evidence_json) VALUES (6,1,'parent_name',2,'model','unknown','fixture','{}','[]')")
        connection.execute("INSERT INTO facts(id,case_id,fact_key,previous_id,origin,status,created_at,value_json,evidence_json) VALUES (7,1,'parent_name',6,'human','checked','fixture','{}','[]')")
        connection.execute("INSERT INTO qa VALUES (8,1,3,'fixture','question','{}')")
    db.initialize(tmp_path)
    assert list((tmp_path/'backups').glob('pre-migration-*-v10.db'))
    with closing(db.connect(tmp_path)) as connection, connection:
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
        assert connection.execute('SELECT previous_id FROM facts WHERE id=7').fetchone()[0] == 6
        assert connection.execute('SELECT run_id FROM summaries WHERE id=5').fetchone()[0] == 1
        assert connection.execute('SELECT run_id FROM qa WHERE id=8').fetchone()[0] == 3
        connection.execute("INSERT INTO model_runs(id,case_id,task_type,request_key,request_json,source_json,snapshot_json,status,detail,created_at,submitted_at) VALUES (4,1,'review','fixture','{}','{}','{}','submitted','fixture','fixture','fixture')")
    cases.recover_model_runs(tmp_path)
    with closing(db.connect(tmp_path)) as connection:
        row = connection.execute('SELECT status,usage_uncertain FROM model_runs WHERE id=4').fetchone()
        assert tuple(row) == ('interrupted', 1)
        for table in ('summaries', 'facts', 'qa'):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(f'DELETE FROM {table}')


def test_close_cancellation_returns_boolean_and_keeps_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(research, '_jobs', {})
    assert research.cancel_on_close(tmp_path) is True
    cancelled, finished = Event(), Event()
    job = {'active': True, 'cancel': cancelled, 'finished': finished}
    research._jobs[(str(tmp_path.resolve()), 1)] = job
    times = iter((0, 8))
    monkeypatch.setattr(research, 'monotonic', lambda: next(times))
    assert research.cancel_on_close(tmp_path) is False
    assert cancelled.is_set()
    finished.set()
    times = iter((0, 0))
    assert research.cancel_on_close(tmp_path) is True


def test_synthesis_dedup_retains_all_findings_unmatched_quotes_and_batch_keys(trial, monkeypatch):
    monkeypatch.setattr(documents, 'retrieve_review_verification', lambda *args:
        {'passages': [], 'searches': {}, 'warnings': [], 'key_passages': {}})
    plan, requests, context, runtime = research._prepare(trial['data'], trial['case'], [trial['doc']])
    batch_keys = [research._hash(value) for value in requests]
    checked = research._checked_items(trial['data'], reply(requests[0]), requests[0]['source_snapshot'], 'batch')
    matched = checked['items'][0]
    assert matched['citation'] is not None
    unmatched = {**matched, 'quote': 'Synthetic absent quotation, retained as proposed.',
                 'citation': None, 'status': 'unresolved', 'detail': 'Quote did not match.', 'ai_comment': None}
    completed = [{'run_id': 101, 'result': {'items': [matched, unmatched], 'warnings': ['Synthetic limitation']}},
                 {'run_id': 102, 'result': {'items': [copy.deepcopy(matched)], 'warnings': []}}]
    original = copy.deepcopy(completed)
    request = research._synthesis(trial['data'], plan, requests, completed, context, runtime)
    payload = json.loads(request['input_text'])
    findings = payload['batch_findings_not_source_evidence']
    assert [len(value['items']) for value in findings] == [2, 1]
    assert findings[0]['items'][1] == unmatched
    citation = matched['citation']
    expected = {'id': 1, 'document_id': citation['document_id'], 'start_offset': citation['start_offset'],
                'end_offset': citation['end_offset'], 'text': citation['quote'],
                'heading': 'Verified quotation from a reviewed batch', 'partial': False}
    assert payload['original_evidence'] == [expected]
    assert request['source_snapshot']['passages'] == [expected]
    for index in (0, 1):
        item = findings[index]['items'][0]
        assert item['synthesis_passage_id'] == 1 and 'quote' not in item and 'citation' not in item
        assert all(item[key] == value for key, value in matched.items() if key not in ('quote', 'citation'))
    assert completed == original
    assert [research._hash(value) for value in requests] == batch_keys
    again = research._prepare(trial['data'], trial['case'], [trial['doc']])
    assert again[0]['plan_key'] == plan['plan_key']
    assert [research._hash(value) for value in again[1]] == batch_keys


def test_real_time_verification_includes_target_financials_and_deadline_note(tmp_path):
    db.initialize(tmp_path)
    case = cases.create_case(tmp_path, 'Time Finance saved public source check')
    saved = []
    for name in ('time_finance_20260902_scheme_publication.pdf', 'time_finance_20260817_acquisition_announcement.pdf'):
        original = (Path(__file__).parent/'fixtures'/name).read_bytes()
        saved.append(documents.store_document(tmp_path, case['id'], original, name, 'application/pdf'))
    checks = [documents.retrieve_review_verification(tmp_path, row['id'], constants.REVIEW_VERIFICATION_CHARS//2) for row in saved]
    assert sum(len(value['text']) for check in checks for value in check['passages']) <= constants.REVIEW_VERIFICATION_CHARS
    financial = [' '.join(value['text'].split()) for value in checks[1]['passages']]
    assert any('8.4m' in value and '31 May 2026' in value for value in financial)
    assert any('218 million' in value and '30 June 2026' in value for value in financial)
    assert any('(9)' in value['text'] and 'agree in writing' in value['text'] and 'Court may approve' in value['text']
               for value in checks[0]['passages'])
    source = documents.plan_review_passages(tmp_path, case['id'], saved[1]['id'])['source']
    text = documents.read_document(tmp_path, saved[1]['id'])['canonical_text']
    left = text.index('become a business that generated')
    right = text.index('year ended 31 May 2025.', left) + len('year ended 31 May 2025.')
    passage = {'id': 1, 'document_id': saved[1]['id'], 'start_offset': left, 'end_offset': right, 'text': text[left:right]}
    assert 'Page 4' in passage['text']
    raw = json.dumps({'items': [{'section': 'financials', 'text': 'Synthetic claim to test the page-marker guard.',
        'status': 'sourced', 'passage_id': 1, 'quote': passage['text'], 'ai_comment': None}], 'limitations': []})
    checked = research._checked_items(tmp_path, raw, {'sources': [source], 'passages': [passage]}, 'batch')
    assert checked['items'][0]['citation'] is None and 'page labels' in checked['items'][0]['detail']
