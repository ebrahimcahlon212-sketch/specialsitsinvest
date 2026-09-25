"""Saved real filing text with explicitly synthetic answers and provider envelopes.

All research is temporary. These checks never call a model or another live service.
"""

import copy
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app import cases, constants, db, documents, model, prompts, worker
from app.bridge import Bridge


QUESTION = 'Who is this information statement addressed to?'
QUOTE = 'Dear Western Digital Corporation Stockholder:'
FIXTURE = Path(__file__).parent / 'fixtures' / 'sandisk_20241220_d835366dex991.htm'


@pytest.fixture(scope='module')
def saved_question_filing(tmp_path_factory):
    data = tmp_path_factory.mktemp('question-base')
    db.initialize(data)
    case = cases.create_case(data, 'Saved filing question checks', 'Synthetic owner note; preserve it.')
    document = documents.import_local(data, case['id'], FIXTURE)
    return data, case, document


@pytest.fixture
def research(saved_question_filing, tmp_path, monkeypatch):
    template, case, document = saved_question_filing
    data = tmp_path / 'research'
    shutil.copytree(template, data)
    state = {'data': data, 'case': case, 'document': document, 'queued': [], 'calls': [],
             'context': {'version': 'synthetic-runtime', 'fingerprint': 'synthetic-config-a'},
             'runtime_calls': 0, 'no_evidence': False, 'response_edit': None, 'raw': None,
             'on_generate': None, 'retrieval_shift': 0}

    def retrieve(_data, case_id, document_id, question):
        # Deliberately selected real opening, not a claim that this is FTS retrieval.
        with closing(db.connect(data)) as connection:
            row = connection.execute('SELECT * FROM documents WHERE id=? AND case_id=?',
                                     (document_id, case_id)).fetchone()
        source = {key: row[key] for key in ('name', 'cleaner_version', 'text_hash',
                                           'original_sha256', 'filing_date', 'accession_number')}
        source.update(document_id=document_id, total_chars=len(row['canonical_text']))
        start, end = state['retrieval_shift'], 8000
        passages = [] if state['no_evidence'] else [{'id': 1, 'document_id': document_id,
            'start_offset': start, 'end_offset': end, 'text': row['canonical_text'][start:end],
            'heading': 'Synthetic selection of saved real opening', 'partial': True}]
        return {'source': source, 'passages': passages, 'searches': [question],
                'warnings': ['Synthetic bounded selection; not whole-filing analysis.']}

    def runtime():
        state['runtime_calls'] += 1
        return copy.deepcopy(state['context'])

    def generate(_data, request, cancel_event, progress):
        state['calls'].append(copy.deepcopy(request))
        progress('Synthetic submission notification.', submitted=True)
        if state['on_generate']:
            return state['on_generate'](request, cancel_event, progress)
        response = {'sentences': [{'text': 'Synthetic answer: the salutation addresses Western Digital stockholders.',
            'status': 'sourced', 'passage_id': 1, 'quote': QUOTE}],
            'limitations': ['Synthetic answer for evidence and persistence checks only.']}
        if state['response_edit']:
            state['response_edit'](response)
        state['raw'] = json.dumps(response)
        return {'status': 'completed', 'response_text': state['raw'], 'submitted': True,
                'usage': {'inputTokens': 100, 'outputTokens': 20, 'totalTokens': 120},
                'metadata': {'origin': 'synthetic-test'}, 'retries': [], 'tool_activity': [], 'error': None}

    monkeypatch.setattr(documents, 'retrieve_question_passages', retrieve)
    monkeypatch.setattr(model, 'runtime_context', runtime)
    monkeypatch.setattr(model, 'generate', generate)
    monkeypatch.setattr(worker, 'submit', lambda function, *args: state['queued'].append((function, args)))
    yield state
    cases._question_jobs.pop((str(data.resolve()), case['id']), None)


def rows(state, table):
    assert table in ('qa', 'model_runs')
    with closing(db.connect(state['data'])) as connection:
        return [dict(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY id')]


def drain(state):
    function, arguments = state['queued'].pop(0)
    function(*arguments)
    return cases.question_status(state['data'], state['case']['id'])


def finish(state, question=QUESTION, document_id=None):
    cases.ask_question(state['data'], state['case']['id'], document_id or state['document']['id'], question)
    return drain(state)


def test_answer_persists_reopens_exact_version_and_older_cache_selection(research):
    state = finish(research)
    answer = state['answers'][0]
    sentence, = answer['sentences']
    assert sentence['status'] == 'quote matched' and not answer['stale']
    assert answer['question'] == QUESTION and answer['source']['document_id'] == research['document']['id']
    opened = cases.read_question_evidence(research['data'], answer['id'], 0)
    citation = sentence['citation']
    assert citation['quote'] == opened['canonical_text'][citation['start_offset']:citation['end_offset']]
    assert citation['text_version_id'] == research['document']['id']
    assert '<mark>' + QUOTE + '</mark>' in opened['html']
    run, = rows(research, 'model_runs')
    assert run['response_text'] == research['raw'] and not run['usage_uncertain']
    assert json.loads(run['usage_json'])['totalTokens'] == 120
    later = finish(research, 'Which stockholders receive this statement?')['answers'][0]
    assert later['id'] != answer['id'] and len(research['calls']) == 2
    reused = finish(research)
    assert reused['answers'][0]['id'] == answer['id']
    assert len(reused['answers']) == 2 and len(rows(research, 'model_runs')) == 2
    assert len(research['calls']) == 2 and 'reused' in reused['detail']
    cases._question_jobs.pop((str(research['data'].resolve()), research['case']['id']))
    assert cases.question_status(research['data'], research['case']['id'])['answers'][0]['id'] == answer['id']
    with closing(db.connect(research['data'])) as connection:
        assert connection.execute('SELECT question FROM cases').fetchone()[0] == research['case']['question']
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            connection.execute("UPDATE qa SET question='Synthetic replacement'")


def test_question_bridge_serializes_state_and_opens_saved_evidence(research):
    bridge = Bridge(research['data'])
    pending = bridge.ask_question({'case_id': research['case']['id'],
        'document_id': research['document']['id'], 'question': QUESTION})
    assert pending['error'] is None and pending['active']
    drain(research)
    state = bridge.question_status({'case_id': research['case']['id']})
    assert state['error'] is None and not state['active']
    answer = state['answers'][0]
    assert answer['question'] == QUESTION and answer['source']['document_id'] == research['document']['id']
    opened = bridge.read_question_evidence({'qa_id': answer['id'], 'index': 0})
    assert opened['error'] is None and opened['document']['citation']['text_version_id'] == research['document']['id']
    assert '<mark>' + QUOTE + '</mark>' in opened['document']['html']
    assert json.loads(json.dumps(state)) == state and json.loads(json.dumps(opened)) == opened
    assert bridge.read_question_evidence({'qa_id': answer['id'], 'index': 7})['error']
    assert bridge.ask_question({'case_id': research['case']['id'], 'document_id': research['document']['id'],
        'question': QUESTION, 'path': 'synthetic-arbitrary-path'})['error']
    assert not research['queued']


@pytest.mark.parametrize('changed', ['question', 'prompt', 'prompt_version', 'retrieval_version',
                                    'retrieved_text', 'runtime', 'document_version'])
def test_complete_effective_question_request_changes_miss_cache(research, monkeypatch, changed):
    original = finish(research)['answers'][0]
    question, document_id = QUESTION, research['document']['id']
    if changed == 'question':
        question += ' Please explain.'
    elif changed == 'prompt':
        monkeypatch.setattr(prompts, 'QUESTION_PROMPT', prompts.QUESTION_PROMPT + '\nSynthetic instruction revision.')
    elif changed == 'prompt_version':
        monkeypatch.setattr(prompts, 'QUESTION_PROMPT_VERSION', 'synthetic-question-next')
    elif changed == 'retrieval_version':
        monkeypatch.setattr(constants, 'QUESTION_RETRIEVAL_VERSION', 'synthetic-retrieval-next')
    elif changed == 'retrieved_text':
        research['retrieval_shift'] = 1
    elif changed == 'runtime':
        research['context']['fingerprint'] = 'synthetic-config-b'
    else:
        newer = documents.import_local(research['data'], research['case']['id'], FIXTURE,
                                       cleaner_version='synthetic-cleaner-next')
        document_id = newer['id']
    status = finish(research, question, document_id)
    assert len(research['calls']) == 2 and len(rows(research, 'qa')) == 2
    assert status['answers'][0]['id'] != original['id']
    previous = next(answer for answer in status['answers'] if answer['id'] == original['id'])
    if changed in ('prompt_version', 'retrieval_version', 'document_version'):
        assert previous['stale'] and previous['stale_reason']
    opened = cases.read_question_evidence(research['data'], original['id'], 0)
    assert opened['citation']['document_id'] == research['document']['id']


@pytest.mark.parametrize('bad_evidence', ['missing_quote', 'unprovided_passage', 'outside_passage'])
def test_bad_evidence_stays_unresolved_and_original_response_is_retained(research, bad_evidence):
    def edit(response):
        sentence = response['sentences'][0]
        if bad_evidence == 'missing_quote':
            sentence['quote'] = 'Synthetic sentence absent from the filing.'
        elif bad_evidence == 'unprovided_passage':
            sentence['passage_id'] = 999
        else:
            with closing(db.connect(research['data'])) as connection:
                text = connection.execute('SELECT canonical_text FROM documents WHERE id=?',
                                          (research['document']['id'],)).fetchone()[0]
            sentence['quote'] = text[9000:9150]
    research['response_edit'] = edit
    answer = finish(research)['answers'][0]
    assert answer['sentences'][0]['status'] == 'unresolved'
    assert answer['sentences'][0]['citation'] is None and answer['sentences'][0]['detail']
    assert rows(research, 'model_runs')[0]['response_text'] == research['raw']
    with pytest.raises(ValueError, match='no matched'):
        cases.read_question_evidence(research['data'], answer['id'], 0)


def test_no_retrieved_evidence_saves_local_limitation_without_runtime_or_model(research):
    research['no_evidence'] = True
    answer = finish(research, 'Zyzzyvaquux?')['answers'][0]
    assert answer['passages'] == [] and answer['sentences'][0]['status'] == 'unresolved'
    assert 'No relevant evidence' in answer['sentences'][0]['text']
    assert 'No model request was sent' in ' '.join(answer['limitations'])
    assert research['runtime_calls'] == 0 and not research['calls']
    run, = rows(research, 'model_runs')
    assert run['status'] == 'completed' and run['submitted_at'] is None
    assert run['usage_json'] is None and not run['usage_uncertain']
    assert json.loads(run['metadata_json'])['origin'] == 'local_retrieval'
    assert finish(research, 'Zyzzyvaquux?')['answers'][0]['id'] == answer['id']
    assert len(rows(research, 'qa')) == 1 and not research['calls']


def test_cancel_before_submission_never_calls_runtime_or_model(research):
    cases.ask_question(research['data'], research['case']['id'], research['document']['id'], QUESTION)
    cases.cancel_question(research['data'], research['case']['id'])
    status = drain(research)
    assert not status['active'] and 'Cancelled before' in status['detail']
    assert not research['calls'] and not research['runtime_calls'] and not research['queued']
    assert rows(research, 'qa') == [] and rows(research, 'model_runs') == []


def test_cancel_after_submission_retains_unknown_usage_and_no_answer(research):
    def cancelled(request, cancel_event, progress):
        cases.cancel_question(research['data'], research['case']['id'])
        assert cancel_event.is_set()
        return {'status': 'cancelled', 'submitted': True, 'response_text': None, 'usage': None,
                'metadata': {}, 'error': 'Synthetic cancellation.'}
    research['on_generate'] = cancelled
    status = finish(research)
    run, = rows(research, 'model_runs')
    assert run['status'] == 'cancelled' and run['submitted_at'] and run['usage_uncertain']
    assert run['usage_json'] is None and status['answers'] == []
    assert len(research['calls']) == 1 and not research['queued']


def test_restart_recovers_interrupted_question_without_automatic_replay(research):
    def interrupted(request, cancel_event, progress):
        raise KeyboardInterrupt('Synthetic process interruption.')
    research['on_generate'] = interrupted
    cases.ask_question(research['data'], research['case']['id'], research['document']['id'], QUESTION)
    with pytest.raises(KeyboardInterrupt, match='Synthetic process'):
        drain(research)
    assert rows(research, 'model_runs')[0]['status'] == 'submitted'
    cases.recover_model_runs(research['data'])
    run, = rows(research, 'model_runs')
    assert run['status'] == 'interrupted' and run['usage_uncertain'] and run['usage_json'] is None
    assert not cases.question_status(research['data'], research['case']['id'])['active']
    assert rows(research, 'qa') == [] and len(research['calls']) == 1 and not research['queued']


@pytest.mark.parametrize('problem', ['invalid_json', 'retrieval_error', 'wrong_case', 'blank_question'])
def test_question_errors_preserve_saved_answers(research, monkeypatch, problem):
    answer = finish(research)['answers'][0]
    saved_rows = rows(research, 'qa')
    if problem == 'invalid_json':
        research['on_generate'] = lambda *_: {'status': 'completed', 'submitted': True,
            'response_text': 'Synthetic malformed JSON', 'usage': None, 'metadata': {}}
        status = finish(research, QUESTION + ' Again?')
        assert status['error'] and rows(research, 'model_runs')[-1]['status'] == 'failed'
        assert rows(research, 'model_runs')[-1]['response_text'] == 'Synthetic malformed JSON'
    elif problem == 'retrieval_error':
        def unavailable(*_):
            raise ValueError('Synthetic incomplete index; no workaround.')
        monkeypatch.setattr(documents, 'retrieve_question_passages', unavailable)
        status = finish(research, QUESTION + ' Again?')
        assert 'Synthetic incomplete index' in status['error']
    elif problem == 'wrong_case':
        other = cases.create_case(research['data'], 'Synthetic other case')
        with pytest.raises(ValueError, match='usable searchable text'):
            cases.ask_question(research['data'], other['id'], research['document']['id'], QUESTION)
    else:
        with pytest.raises(ValueError, match='Enter a question'):
            cases.ask_question(research['data'], research['case']['id'], research['document']['id'], '  ')
    assert rows(research, 'qa') == saved_rows
    assert cases.read_question_evidence(research['data'], answer['id'], 0)['citation']['quote'] == QUOTE
    assert not research['queued']


def test_only_actual_unusable_documents_produce_missing_text_warning(research):
    request, _, _ = cases.prepare_question(research['data'], research['case']['id'], research['document']['id'], QUESTION)
    assert not any('lack usable text' in note for note in json.loads(request['input_text'])['warnings'])
    documents.store_document(research['data'], research['case']['id'], b'<script>Synthetic unusable document</script>',
                             'Synthetic unusable', 'text/html')
    request, _, _ = cases.prepare_question(research['data'], research['case']['id'], research['document']['id'], QUESTION)
    assert any('1 saved document' in note and 'lack usable text' in note
               for note in json.loads(request['input_text'])['warnings'])
