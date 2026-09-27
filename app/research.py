"""Manual source collection and bounded review through the existing worker."""

import hashlib
import json
import logging
import re
from contextlib import closing
from datetime import datetime, timezone
from threading import Event, RLock
from time import monotonic

from app import cases, constants, db, documents, model, prompts, worker

_lock = RLock()
_jobs = {}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _key(data_dir, case_id):
    return str(data_dir.resolve()), case_id


def _get(connection, name, default=None):
    row = connection.execute('SELECT value FROM settings WHERE key=?', (name,)).fetchone()
    return json.loads(row[0]) if row else default


def _save(data_dir, name, value):
    with db.DATA_LOCK, closing(db.connect(data_dir)) as connection, connection:
        cases._setting(connection, name, _json(value))


def _context(data_dir, case_id):
    with closing(db.connect(data_dir)) as connection:
        snapshot = cases._snapshot(connection, case_id, None)
        snapshot['saved_scenarios'] = [dict(row) for row in connection.execute(
            'SELECT id,name,kind,inputs_json,outputs_json,warning,created_at FROM scenarios WHERE case_id=? ORDER BY id',
            (case_id,))]
        collection = _get(connection, f'research_collection_{case_id}')
    snapshot['collection_gaps'] = collection.get('gaps', []) if collection else [
        'No source collection has been recorded. Selected documents alone do not establish a complete or current public record.']
    return snapshot


def _request(phase, payload, snapshot, runtime):
    return {'model': constants.SUMMARY_MODEL_NAME, 'effort': constants.SUMMARY_MODEL_EFFORT,
        'prompt': prompts.REVIEW_PROMPT if phase == 'batch' else prompts.REVIEW_SYNTHESIS_PROMPT,
        'prompt_version': prompts.REVIEW_PROMPT_VERSION if phase == 'batch' else prompts.REVIEW_SYNTHESIS_VERSION,
        'output_schema': (prompts.ReviewBatchOutput if phase == 'batch' else prompts.ReviewReportOutput).model_json_schema(),
        'input_text': _json(payload), 'runtime_context': runtime, 'source_snapshot': snapshot}


def _prepare(data_dir, case_id, document_ids):
    if (not isinstance(document_ids, list) or not 1 <= len(document_ids) <= constants.REVIEW_MAX_DOCUMENTS
            or any(type(value) is not int or value <= 0 for value in document_ids)
            or len(set(document_ids)) != len(document_ids)):
        raise ValueError(f'Select between 1 and {constants.REVIEW_MAX_DOCUMENTS} distinct saved document versions.')
    context = _context(data_dir, case_id)
    runtime = model.runtime_context(constants.SUMMARY_MODEL_NAME, constants.SUMMARY_MODEL_EFFORT)
    sources, batches, warnings, logical = [], [], [], set()
    passage_id = 1
    for identity in sorted(document_ids):
        planned = documents.plan_review_passages(data_dir, case_id, identity)
        source = planned['source']
        if source['logical_document_id'] in logical:
            raise ValueError('Select only one version of each document. Conflicting versions must not be silently combined.')
        logical.add(source['logical_document_id'])
        sources.append(source)
        warnings.extend(f"Document {identity}: {value}" for value in planned['warnings'])
        for value in planned['batches']:
            for passage in value['passages']:
                passage['id'] = passage_id
                passage_id += 1
            batches.append({**value, 'document_id': identity, 'index': len(batches)})
    included = set(document_ids)
    with closing(db.connect(data_dir)) as connection:
        latest = connection.execute('SELECT id,processing_error FROM documents d WHERE case_id=? AND '
            'id=(SELECT MAX(id) FROM documents v WHERE v.logical_document_id=d.logical_document_id)', (case_id,)).fetchall()
    warnings.extend(f"Document version {row['id']} is not selected and will not be reviewed."
                    + (' Text processing failed.' if row['processing_error'] else '')
                    for row in latest if row['id'] not in included)
    warnings.extend(context['collection_gaps'])
    warnings.append('Coverage counts extracted text supplied to successful review calls. It does not verify interpretation, images, current prices or completeness of public documents.')
    blockers = []
    if len(batches) > constants.REVIEW_MAX_BATCHES:
        blockers.append(f'This selection needs {len(batches)} batches; the limit is {constants.REVIEW_MAX_BATCHES}. Select fewer documents. Nothing is silently omitted.')
    if len(_json(context)) > constants.REVIEW_CONTEXT_CHARS:
        blockers.append(f'Owner notes, facts and saved scenarios exceed the {constants.REVIEW_CONTEXT_CHARS:,}-character context limit. Nothing was truncated.')
    requests = []
    for batch in batches:
        source = next(value for value in sources if value['document_id'] == batch['document_id'])
        payload = {'source': source, 'passages': batch['passages'], 'warnings': batch['warnings'],
                   'owner_context_not_source_evidence': context}
        snapshot = {'phase': 'batch', 'planner_version': constants.REVIEW_PLANNER_VERSION,
                    'sources': [source], 'passages': batch['passages'], 'context': context,
                    'coverage': {name: batch[name] for name in ('document_id', 'start_offset', 'end_offset')}}
        requests.append(_request('batch', payload, snapshot, runtime))
    plan_key = _hash({'requests': [_hash(value) for value in requests], 'context': context,
                     'synthesis_prompt': prompts.REVIEW_SYNTHESIS_PROMPT,
                     'synthesis_version': prompts.REVIEW_SYNTHESIS_VERSION,
                     'verification_version': constants.REVIEW_VERIFICATION_VERSION,
                     'verification_queries': constants.REVIEW_VERIFICATION_QUERIES,
                     'verification_weights': constants.REVIEW_VERIFICATION_WEIGHTS,
                     'verification_characters': constants.REVIEW_VERIFICATION_CHARS,
                     'synthesis_schema': prompts.ReviewReportOutput.model_json_schema()})
    preview = []
    with closing(db.connect(data_dir)) as connection:
        for batch, request in zip(batches, requests):
            cached = _cached(connection, case_id, _hash(request), 'batch')
            last = connection.execute('SELECT status FROM model_runs WHERE case_id=? AND request_key=? ORDER BY id DESC LIMIT 1',
                                      (case_id, _hash(request))).fetchone()
            preview.append({name: batch[name] for name in ('index','document_id','start_offset','end_offset')}
                           | {'characters': sum(len(value['text']) for value in batch['passages']),
                              'cached': cached is not None, 'status': 'completed' if cached else last['status'] if last else 'unreviewed'})
    cached_count = sum(value['cached'] for value in preview)
    plan = {'plan_key': plan_key, 'document_ids': sorted(document_ids), 'sources': sources,
            'batches': preview, 'batch_count': len(batches), 'cached_batches': cached_count,
            'max_new_requests': len(batches) - cached_count + 1, 'total_chars': sum(value['total_chars'] for value in sources),
            'allowed': not blockers, 'warnings': list(dict.fromkeys(warnings)), 'blockers': blockers,
            'model': constants.SUMMARY_MODEL_NAME, 'effort': constants.SUMMARY_MODEL_EFFORT,
            'deadline_seconds': constants.SUMMARY_DEADLINE_SECONDS}
    return plan, requests, context, runtime


def prepare(data_dir, case_id, document_ids):
    """Preview all planned requests without submitting a model call."""
    return _prepare(data_dir, case_id, document_ids)[0]


def _cached(connection, case_id, request_key, phase):
    return connection.execute('SELECT v.*,r.usage_json,r.usage_uncertain FROM review_results v '
        'JOIN model_runs r ON r.id=v.run_id WHERE v.case_id=? AND r.request_key=? AND r.status=\'completed\' '
        'AND v.phase=? ORDER BY v.id DESC LIMIT 1', (case_id, request_key, phase)).fetchone()


def _checked_items(data_dir, raw, snapshot, phase):
    schema = prompts.ReviewBatchOutput if phase == 'batch' else prompts.ReviewReportOutput
    output = schema.model_validate_json(raw).model_dump()
    if phase == 'report' and {item['section'] for item in output['items']} != {
            'company', 'event', 'conditions', 'dates', 'financials', 'risks', 'opportunity', 'unknowns'}:
        raise ValueError('The report omitted a required section; missing evidence must be shown explicitly.')
    sources = {value['document_id']: value for value in snapshot['sources']}
    passages = {value['id']: value for value in snapshot['passages']}
    texts = {}
    with closing(db.connect(data_dir)) as connection:
        for identity, source in sources.items():
            row = connection.execute('SELECT canonical_text,text_hash,original_sha256 FROM documents WHERE id=?', (identity,)).fetchone()
            if (row is None or row['text_hash'] != source['text_hash'] or row['original_sha256'] != source['original_sha256']
                    or hashlib.sha256(row['canonical_text'].encode('utf-8')).hexdigest() != source['text_hash']):
                raise ValueError('A supplied source version failed verification during review.')
            texts[identity] = row['canonical_text']
    checked = []
    for item in output['items']:
        result = {**item, 'citation': None, 'detail': None}
        passage = passages.get(item['passage_id'])
        if item['status'] == 'assumption':
            result['detail'] = 'Model assumption, not a verified document fact.'
        elif not item['quote'] or passage is None:
            result.update(status='unresolved', detail='No supporting quotation from a supplied passage.')
        else:
            source, text = sources[passage['document_id']], texts[passage['document_id']]
            if text[passage['start_offset']:passage['end_offset']] != passage['text']:
                raise ValueError('A supplied passage disagrees with its canonical text.')
            try:
                start, end = documents.match_quote(text, item['quote'], passage['start_offset'], passage['end_offset'])
                if source['cleaner_version'].startswith('pdf-') and any(
                        value.start() < end and value.end() > start
                        for value in re.finditer(r'(?m)^Page \d+$|\[Extraction notice:[^\]]*\]', text)):
                    raise ValueError('Application page labels and extraction notices are not issuer evidence.')
                result['citation'] = {'document_id': source['document_id'], 'document_hash': source['original_sha256'],
                    'text_version_id': source['document_id'], 'start_offset': start, 'end_offset': end,
                    'quote': text[start:end], 'status': 'quote matched'}
                result['status'] = 'quote matched' if item['status'] == 'sourced' else 'unresolved'
                if result['status'] == 'unresolved':
                    result['detail'] = 'The quotation matched, but the model left this proposal unresolved.'
            except ValueError as error:
                result.update(status='unresolved', detail=str(error))
        if result['citation'] is None:
            result['ai_comment'] = None
        checked.append(result)
    return {'items': checked, 'warnings': output['limitations']}


def _progress(data_dir, case_id, detail):
    with _lock:
        job = _jobs.get(_key(data_dir, case_id))
        if job:
            job['detail'] = detail


def _run_request(data_dir, case_id, plan_key, phase, request, cancel_event, report_metadata=None):
    request_key = _hash(request)
    with db.DATA_LOCK, closing(db.connect(data_dir)) as connection, connection:
        cached = _cached(connection, case_id, request_key, phase)
        if cached:
            return {'status': 'completed', 'run_id': cached['run_id'], 'id': cached['id'],
                    'result': json.loads(cached['result_json']), 'cached': True}
        if cancel_event.is_set():
            return {'status': 'cancelled'}
        cursor = connection.execute('INSERT INTO model_runs(case_id,task_type,request_key,request_json,source_json,snapshot_json,status,detail,created_at) '
            'VALUES (?,\'review\',?,?,?,?,\'connecting\',?,?)',
            (case_id, request_key, _json(request), _json(request['source_snapshot']['sources']),
             _json(request['source_snapshot']), 'Checking subscription connection.', _now()))
        run_id = cursor.lastrowid
    def progress(detail, submitted=False, usage=None):
        _progress(data_dir, case_id, detail)
        with db.DATA_LOCK, closing(db.connect(data_dir)) as connection, connection:
            connection.execute('UPDATE model_runs SET detail=?,status=CASE WHEN ? THEN \'submitted\' ELSE status END,'
                'submitted_at=CASE WHEN ? THEN COALESCE(submitted_at,?) ELSE submitted_at END,usage_json=COALESCE(?,usage_json) WHERE id=?',
                (detail, int(submitted), int(submitted), _now(), _json(usage) if usage is not None else None, run_id))
    outcome = {}
    result = None
    try:
        outcome = model.generate(data_dir, request, cancel_event, progress)
        state = outcome['status']
        detail = outcome.get('error') or f'Review {phase} {state}.'
        if cancel_event.is_set():
            state, detail = 'cancelled', 'Cancelled; no automatic restart.'
        if state == 'completed':
            result = _checked_items(data_dir, outcome.get('response_text'), request['source_snapshot'], phase)
            result.update(report_metadata or {})
            detail = f'Review {phase} saved. Quote matches do not verify interpretation.'
    except Exception as error:
        logging.getLogger(__name__).exception('Review request or validation failed.')
        state, detail = 'failed', f'Review failed: {error}. Original response retained; no automatic retry.'
    with db.DATA_LOCK, closing(db.connect(data_dir)) as connection, connection:
        current = connection.execute('SELECT submitted_at,usage_json FROM model_runs WHERE id=?', (run_id,)).fetchone()
        usage = outcome.get('usage')
        if usage is None and current['usage_json']:
            usage = json.loads(current['usage_json'])
        submitted = bool(outcome.get('submitted') or current['submitted_at'])
        uncertain = submitted and (state != 'completed' or usage is None)
        if uncertain:
            detail += ' Final usage is uncertain; any reported usage may be partial.'
        connection.execute('UPDATE model_runs SET status=?,detail=?,completed_at=?,response_text=?,usage_json=?,usage_uncertain=?,metadata_json=?,retry_count=? WHERE id=?',
            (state, detail, _now(), outcome.get('response_text'), _json(usage) if usage is not None else None,
             int(uncertain), _json({**outcome.get('metadata', {}), 'retries': outcome.get('retries', []),
             'tool_activity': outcome.get('tool_activity', [])}), len(outcome.get('retries', [])), run_id))
        identity = None
        if result is not None and state == 'completed':
            cursor = connection.execute('INSERT INTO review_results(case_id,run_id,plan_key,phase,created_at,result_json) VALUES (?,?,?,?,?,?)',
                (case_id, run_id, plan_key, phase, _now(), _json(result)))
            identity = cursor.lastrowid
    return {'status': state, 'run_id': run_id, 'id': identity, 'result': result, 'detail': detail, 'cached': False}


def _synthesis(data_dir, plan, requests, completed, context, runtime):
    findings, evidence, seen = [], [], {}
    for outcome in completed:
        items = [dict(item) for item in outcome['result']['items']]
        findings.append({'run_id': outcome['run_id'], 'items': items,
                         'limitations': outcome['result']['warnings']})
        for item in items:
            citation = item['citation']
            if citation is None:
                continue
            identity = citation['document_id'], citation['start_offset'], citation['end_offset']
            if identity not in seen:
                seen[identity] = len(evidence) + 1
                evidence.append({'id': len(evidence) + 1, 'document_id': identity[0], 'start_offset': identity[1],
                    'end_offset': identity[2], 'text': citation['quote'], 'heading': 'Verified quotation from a reviewed batch', 'partial': False})
            item['synthesis_passage_id'] = seen[identity]
            # Original evidence holds the exact quote and its immutable range.
            # Unmatched proposals keep their unverified quotation unchanged.
            del item['quote'], item['citation']
    verification = []
    for source in plan['sources']:
        checked = documents.retrieve_review_verification(data_dir, source['document_id'],
            constants.REVIEW_VERIFICATION_CHARS // len(plan['sources']))
        mapping = {}
        for passage in checked['passages']:
            identity = passage['document_id'], passage['start_offset'], passage['end_offset']
            if identity not in seen:
                seen[identity] = len(evidence) + 1
                evidence.append({**passage, 'id': seen[identity]})
            mapping[passage['id']] = seen[identity]
        verification.append({'document_id': source['document_id'], 'version': constants.REVIEW_VERIFICATION_VERSION,
            'searches': checked['searches'],
            'warnings': [f"Additional report source check (document {source['document_id']}): {value}" for value in checked['warnings']],
            'key_passages': {key: [mapping[value] for value in ids] for key, ids in checked['key_passages'].items()}})
    payload = {'sources': plan['sources'], 'batch_findings_not_source_evidence': findings,
               'original_evidence': evidence, 'owner_context_not_source_evidence': context,
               'direct_source_verification': verification,
               'coverage_warnings': plan['warnings']}
    if len(_json(payload)) > constants.REVIEW_SYNTHESIS_CHARS:
        raise ValueError(f'All saved findings exceed the {constants.REVIEW_SYNTHESIS_CHARS:,}-character report allowance. Batches remain saved; no findings were silently discarded and no report request was sent.')
    snapshot = {'phase': 'report', 'sources': plan['sources'], 'passages': evidence,
                'context': context, 'batch_run_ids': [value['run_id'] for value in completed],
                'direct_source_verification': verification}
    return _request('report', payload, snapshot, runtime)


def _begin(data_dir, case_id, phase, function, *args):
    key = _key(data_dir, case_id)
    with _lock:
        if _jobs.get(key, {}).get('active'):
            raise ValueError('A research operation is already running for this case.')
        event = Event()
        _jobs[key] = {'active': True, 'phase': phase, 'detail': 'Queued.', 'error': None,
                      'cancel': event, 'finished': Event()}
    try:
        worker.submit(function, data_dir, case_id, *args, event)
    except Exception:
        with _lock:
            _jobs[key]['active'] = False
            _jobs[key]['finished'].set()
        raise


def collect(data_dir, case_id, url):
    _context(data_dir, case_id)
    _begin(data_dir, case_id, 'collecting', _collect, url)
    return status(data_dir, case_id)


def _collect(data_dir, case_id, url, event):
    from app import sources
    try:
        _save(data_dir, f'research_error_{case_id}', None)
        result = sources.collect_sources(data_dir, case_id, url, event,
            lambda detail: _progress(data_dir, case_id, detail))
        identities = list(dict.fromkeys(value['document_id'] for value in result['documents']
                          if value.get('document_id') and value.get('status') == 'searchable'))
        if len(identities) > constants.REVIEW_MAX_DOCUMENTS:
            result['gaps'].append(f'Only the first {constants.REVIEW_MAX_DOCUMENTS} searchable documents were selected. Review the complete import list and change the selection if needed.')
        _save(data_dir, f'research_collection_{case_id}', result)
        _save(data_dir, f'research_selection_{case_id}', identities[:constants.REVIEW_MAX_DOCUMENTS])
        _progress(data_dir, case_id, 'Source collection stopped.' if event.is_set() else 'Source collection saved. Select documents and preview the review; no model request has been sent.')
    except Exception as error:
        _failed(data_dir, case_id, str(error))
    finally:
        _finish(data_dir, case_id)


def start(data_dir, case_id, document_ids, plan_key=None):
    plan, requests, context, runtime = _prepare(data_dir, case_id, document_ids)
    if plan_key is None or plan['plan_key'] != plan_key:
        raise ValueError('Preview this selection again: the effective request must match the plan you approved.')
    if not plan['allowed']:
        raise ValueError(' '.join(plan['blockers']))
    _begin(data_dir, case_id, 'reviewing', _review, plan, requests, context, runtime)
    return status(data_dir, case_id)


def _review(data_dir, case_id, plan, requests, context, runtime, event):
    completed = []
    try:
        _save(data_dir, f'research_error_{case_id}', None)
        _save(data_dir, f'research_plan_{case_id}', plan)
        _save(data_dir, f'research_selection_{case_id}', plan['document_ids'])
        for index, request in enumerate(requests):
            if event.is_set():
                _progress(data_dir, case_id, 'Cancelled. Completed batches remain saved; nothing restarts automatically.')
                return
            _progress(data_dir, case_id, f'Reviewing batch {index + 1} of {len(requests)}.')
            outcome = _run_request(data_dir, case_id, plan['plan_key'], 'batch', request, event)
            plan['batches'][index]['status'] = outcome['status']
            plan['batches'][index]['cached'] = bool(outcome.get('cached'))
            _save(data_dir, f'research_plan_{case_id}', plan)
            if outcome['status'] != 'completed':
                _failed(data_dir, case_id, outcome.get('detail') or 'Review stopped. Completed batches are preserved; no automatic retry.')
                return
            completed.append(outcome)
        if event.is_set():
            _progress(data_dir, case_id, 'Cancelled before the final report. Completed batches remain saved.')
            return
        request = _synthesis(data_dir, plan, requests, completed, context, runtime)
        coverage = [{**{key: value[key] for key in ('document_id', 'name', 'total_chars')},
                     'reviewed_chars': value['total_chars'], 'status': 'reviewed'} for value in plan['sources']]
        metadata = {'model': constants.SUMMARY_MODEL_NAME, 'effort': constants.SUMMARY_MODEL_EFFORT,
                    'prompt_version': prompts.REVIEW_SYNTHESIS_VERSION, 'batch_prompt_version': prompts.REVIEW_PROMPT_VERSION,
                    'planner_version': constants.REVIEW_PLANNER_VERSION, 'sources': plan['sources'], 'coverage': coverage,
                    'coverage_warnings': plan['warnings'] + [warning
                        for check in request['source_snapshot']['direct_source_verification'] for warning in check['warnings']], 'context': context,
                    'batch_run_ids': [value['run_id'] for value in completed], 'plan_key': plan['plan_key']}
        _progress(data_dir, case_id, 'Preparing the final report from saved findings and original quotations.')
        outcome = _run_request(data_dir, case_id, plan['plan_key'], 'report', request, event, metadata)
        if outcome['status'] != 'completed':
            _failed(data_dir, case_id, outcome.get('detail') or 'Final report not completed; batches remain saved.')
            return
        _save(data_dir, f'research_current_{case_id}', outcome['id'])
        _progress(data_dir, case_id, 'Saved report reused without a generation request.' if outcome.get('cached') else
                  'Research report saved. Review its evidence and remaining gaps before making a decision.')
    except Exception as error:
        logging.getLogger(__name__).exception('Deep review stopped.')
        _failed(data_dir, case_id, str(error))
    finally:
        _finish(data_dir, case_id)


def _failed(data_dir, case_id, message):
    with _lock:
        _jobs[_key(data_dir, case_id)].update(error=message, detail=message)
    _save(data_dir, f'research_error_{case_id}', message)


def _finish(data_dir, case_id):
    with _lock:
        job = _jobs[_key(data_dir, case_id)]
        job['active'] = False
        job['finished'].set()


def cancel(data_dir, case_id):
    with _lock:
        job = _jobs.get(_key(data_dir, case_id))
        if job and job['active']:
            job['cancel'].set()
            job['detail'] = 'Cancellation requested. No further batch will start.'
    return status(data_dir, case_id)


def cancel_on_close(data_dir):
    with _lock:
        jobs = [value for key, value in _jobs.items() if key[0] == str(data_dir.resolve()) and value['active']]
        for job in jobs:
            job['cancel'].set()
    deadline = monotonic() + 7
    for job in jobs:
        job['finished'].wait(max(0, deadline - monotonic()))
    return all(job['finished'].is_set() for job in jobs)


def status(data_dir, case_id):
    context = _context(data_dir, case_id)
    with closing(db.connect(data_dir)) as connection:
        plan = _get(connection, f'research_plan_{case_id}')
        selected = _get(connection, f'research_selection_{case_id}', [])
        collection = _get(connection, f'research_collection_{case_id}')
        saved_error = _get(connection, f'research_error_{case_id}')
        identity = _get(connection, f'research_current_{case_id}')
        row = connection.execute('SELECT * FROM review_results WHERE case_id=? AND phase=\'report\' '
            'ORDER BY (id=?) DESC,id DESC LIMIT 1', (case_id, identity or -1)).fetchone()
        runs = []
        for run in connection.execute('SELECT * FROM model_runs WHERE case_id=? AND task_type=\'review\' ORDER BY id DESC LIMIT 100', (case_id,)):
            runs.append({key: run[key] for key in ('id','status','detail','created_at','completed_at','retry_count')}
                | {'usage': json.loads(run['usage_json']) if run['usage_json'] else None, 'usage_uncertain': bool(run['usage_uncertain'])})
        report = None
        if row:
            report = json.loads(row['result_json'])
            reasons = []
            if report['context'] != context:
                reasons.append('Case documents, notes, human corrections, source checks or scenarios have changed.')
            if selected and selected != sorted(value['document_id'] for value in report['sources']):
                reasons.append('The selected document versions have changed.')
            if (report['prompt_version'] != prompts.REVIEW_SYNTHESIS_VERSION
                    or report['batch_prompt_version'] != prompts.REVIEW_PROMPT_VERSION
                    or report['planner_version'] != constants.REVIEW_PLANNER_VERSION
                    or (report['model'], report['effort']) != (constants.SUMMARY_MODEL_NAME, constants.SUMMARY_MODEL_EFFORT)):
                reasons.append('Review instructions, source planning or model settings have changed.')
            run_ids = [*report['batch_run_ids'], row['run_id']]
            usage = []
            for run_id in run_ids:
                value = connection.execute('SELECT usage_json,usage_uncertain FROM model_runs WHERE id=?', (run_id,)).fetchone()
                usage.append({'run_id': run_id, 'usage': json.loads(value['usage_json']) if value['usage_json'] else None,
                              'usage_uncertain': bool(value['usage_uncertain'])})
            report.update(id=row['id'], created_at=row['created_at'], run_id=row['run_id'],
                          stale=bool(reasons), stale_reasons=reasons, usage=usage,
                          warnings=list(dict.fromkeys(report['warnings'] + report['coverage_warnings'])))
            report.pop('context')
    with _lock:
        job = dict(_jobs.get(_key(data_dir, case_id), {}))
    return {'active': job.get('active', False), 'phase': job.get('phase'), 'detail': job.get('detail') or saved_error,
            'error': job.get('error') or saved_error, 'collection': collection, 'plan': plan, 'report': report,
            'runs': runs, 'selected_document_ids': selected}


def read_evidence(data_dir, report_id, index):
    with closing(db.connect(data_dir)) as connection:
        row = connection.execute('SELECT result_json FROM review_results WHERE id=? AND phase=\'report\'', (report_id,)).fetchone()
    if row is None:
        raise ValueError('That saved research report does not exist.')
    items = json.loads(row['result_json'])['items']
    if type(index) is not int or not 0 <= index < len(items) or items[index]['citation'] is None:
        raise ValueError('That report item has no matched source quotation.')
    return documents.read_citation(data_dir, items[index]['citation'])
