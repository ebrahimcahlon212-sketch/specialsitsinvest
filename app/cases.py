"""Manual case records, immutable calculated scenarios and decisions."""

import json
import hashlib
import logging
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock

from app import calc
from app.db import DATA_LOCK, connect

_summary_lock = RLock()
_summary_jobs = {}
_fact_jobs = {}
_connection_jobs = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_case(connection, case_id: int):
    row = connection.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        raise ValueError("That case no longer exists.")
    return row


def list_cases(data_dir: Path) -> list[dict]:
    with closing(connect(data_dir)) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM cases ORDER BY COALESCE(updated_at, created_at) DESC, id DESC"
        )]


def create_case(data_dir: Path, title: str, question: str = "") -> dict:
    if not title.strip():
        raise ValueError("Enter a case name.")
    with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
        stamp = _now()
        cursor = connection.execute(
            "INSERT INTO cases(title, question, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (title.strip(), question, stamp, stamp),
        )
        return dict(_require_case(connection, cursor.lastrowid))


def update_case(data_dir: Path, case_id: int, title: str, question: str, status: str) -> dict:
    if not title.strip():
        raise ValueError("Enter a case name.")
    if status not in ("research", "watching", "closed"):
        raise ValueError("Choose research, watching or closed.")
    with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
        _require_case(connection, case_id)
        connection.execute(
            "UPDATE cases SET title = ?, question = ?, status = ?, updated_at = ? WHERE id = ?",
            (title.strip(), question, status, _now(), case_id),
        )
        return dict(_require_case(connection, case_id))


def _json_quantities(value):
    if isinstance(value, calc.Quantity):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json_quantities(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_quantities(item) for item in value]
    return value


def _display_outputs(outputs: dict[str, calc.Quantity]) -> dict[str, str]:
    rendered = {}
    for key, quantity in outputs.items():
        if quantity.value is None:
            text = "unknown"
        elif quantity.unit == "unitless":
            text = calc.format_percentage(quantity, 2)
        elif quantity.currency == "GBP" and quantity.unit == "currency_units":
            text = f"GBP {calc.format_gbp(quantity)}"
        elif quantity.unit == "currency_units_per_share":
            text = f"{quantity.currency} {calc.format_price(quantity, 2)} per share"
        elif quantity.unit == "million_currency_units":
            text = f"{quantity.value} million {quantity.currency}"
        elif quantity.unit == "currency_units":
            text = f"{quantity.value} {quantity.currency}"
        else:
            text = f"{quantity.value} {quantity.unit}"
        rendered[key] = text
    return rendered


def _require_decimal_text(value):
    if isinstance(value, dict):
        if "value" in value and value["value"] is not None and not isinstance(value["value"], str):
            raise ValueError("Decimal inputs must be text, never JavaScript numbers.")
        for item in value.values():
            _require_decimal_text(item)
    elif isinstance(value, list):
        for item in value:
            _require_decimal_text(item)


def calculate_scenario(kind: str, inputs: dict) -> dict:
    _require_decimal_text(inputs)
    warning = None
    if kind == "spinoff":
        validated = calc.SpinoffInputs.model_validate(inputs)
        outputs = calc.spinoff_valuation(validated)
        display = {name: _display_outputs(values) for name, values in outputs.items()}
        normalized = validated.model_dump(mode="json")
    elif kind == "tender":
        scenarios = inputs.get("scenarios")
        if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 10:
            raise ValueError("Enter between one and ten tender scenarios.")
        outputs, display, normalized_rows, weighted = {}, {}, [], []
        for index, scenario in enumerate(scenarios):
            if not isinstance(scenario, dict):
                raise ValueError("Each tender scenario must have its own inputs.")
            validated = calc.TenderInputs.model_validate(scenario.get("inputs"))
            values = calc.tender_scenario(validated)
            key = str(index)
            outputs[key], display[key] = values, _display_outputs(values)
            duration = scenario.get("duration_days")
            if duration is not None and (
                not isinstance(duration, str) or not duration.isascii()
                or not duration.isdigit() or int(duration) <= 0
            ):
                raise ValueError("Duration must be positive whole days or unknown.")
            probability = scenario.get("probability")
            probability = calc.Quantity.model_validate(probability) if probability is not None else None
            weighted.append((probability, values["scenario_profit"]))
            normalized_rows.append({
                "name": scenario.get("name", ""), "inputs": validated.model_dump(mode="json"),
                "probability": probability.model_dump(mode="json") if probability else None,
                "duration_days": duration, "withholding_basis": scenario.get("withholding_basis", ""),
                "broker_confirmation": scenario.get("broker_confirmation", ""),
            })
        try:
            expected = calc.expected_profit(weighted)
            outputs["expected"] = {"expected_profit": expected}
            display["expected"] = _display_outputs(outputs["expected"])
        except ValueError as error:
            warning = f"Expected profit unavailable: {error}. Individual scenarios are shown."
        normalized = {"scenarios": normalized_rows}
    else:
        raise ValueError("Choose the spinoff or fixed-price tender calculator.")
    return {"inputs": normalized, "outputs": _json_quantities(outputs),
            "display": display, "warning": warning}


def _scenario_row(row) -> dict:
    value = dict(row)
    for key in ("inputs", "outputs", "display"):
        value[key] = json.loads(value.pop(f"{key}_json"))
    return value


def list_scenarios(data_dir: Path, case_id: int) -> list[dict]:
    with closing(connect(data_dir)) as connection:
        _require_case(connection, case_id)
        return [_scenario_row(row) for row in connection.execute(
            "SELECT * FROM scenarios WHERE case_id = ? ORDER BY id DESC", (case_id,)
        )]


def save_scenario(data_dir: Path, case_id: int, name: str, kind: str, inputs: dict) -> dict:
    if not name.strip():
        raise ValueError("Name the scenario before saving it.")
    calculated = calculate_scenario(kind, inputs)
    with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
        _require_case(connection, case_id)
        stamp = _now()
        cursor = connection.execute(
            "INSERT INTO scenarios(case_id, name, kind, inputs_json, outputs_json, display_json, warning, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, name.strip(), kind,
             json.dumps(calculated["inputs"], ensure_ascii=False),
             json.dumps(calculated["outputs"], ensure_ascii=False),
             json.dumps(calculated["display"], ensure_ascii=False), calculated["warning"], stamp),
        )
        return _scenario_row(connection.execute(
            "SELECT * FROM scenarios WHERE id = ?", (cursor.lastrowid,)
        ).fetchone())


def list_decisions(data_dir: Path, case_id: int) -> list[dict]:
    with closing(connect(data_dir)) as connection:
        _require_case(connection, case_id)
        values = []
        for row in connection.execute("SELECT * FROM decisions WHERE case_id = ? ORDER BY id DESC", (case_id,)):
            value = dict(row)
            for field in ("document_ids", "scenario_ids", "evidence"):
                value[field] = json.loads(value.pop(f"{field}_json"))
            values.append(value)
        return values


def save_decision(data_dir: Path, case_id: int, decision: str, reason: str,
                  document_ids: list[int], scenario_ids: list[int], evidence: list[dict]) -> dict:
    from app.documents import read_document

    if not decision.strip() or not reason.strip():
        raise ValueError("Enter both a decision and its reason.")
    with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
        _require_case(connection, case_id)
        for table, identities in (("documents", document_ids), ("scenarios", scenario_ids)):
            for identity in identities:
                if connection.execute(
                    f"SELECT 1 FROM {table} WHERE id = ? AND case_id = ?", (identity, case_id)
                ).fetchone() is None:
                    raise ValueError("A referenced document or scenario does not belong to this case.")
        checked_evidence = []
        for citation in evidence:
            if citation["document_id"] not in document_ids:
                raise ValueError("Include each cited document in the decision's document references.")
            # Re-match in Python; never trust offsets supplied by the UI.
            result = read_document(data_dir, citation["document_id"],
                                   block_id=citation.get("block_id"), quote=citation["quote"])
            checked_evidence.append(result["citation"])
        cursor = connection.execute(
            "INSERT INTO decisions(case_id, decision, reason, document_ids_json, scenario_ids_json, evidence_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (case_id, decision.strip(), reason, json.dumps(sorted(set(document_ids))),
             json.dumps(sorted(set(scenario_ids))), json.dumps(checked_evidence, ensure_ascii=False), _now()),
        )
        identity = cursor.lastrowid
    return next(item for item in list_decisions(data_dir, case_id) if item["id"] == identity)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _setting(connection, key, value):
    connection.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, str(value)))


def _source(connection, case_id, document_id=None):
    from app.constants import SUMMARY_MAX_CHARS

    _require_case(connection, case_id)
    if document_id is None:
        saved = connection.execute("SELECT value FROM settings WHERE key=?", (f"summary_document_{case_id}",)).fetchone()
        if saved:
            document_id = int(saved[0])
        else:
            for filing in connection.execute("SELECT * FROM sec_imports WHERE case_id=? ORDER BY id DESC", (case_id,)):
                selected = next((item for item in json.loads(filing['items_json'])
                                 if item['url'] == filing['selected_document_url'] and item.get('document_id')), None)
                if selected:
                    document_id = selected['document_id']
                    break
        if document_id is None:
            usable = connection.execute("SELECT id FROM documents d WHERE case_id=? AND canonical_text IS NOT NULL "
                "AND length(canonical_text)>0 AND id=(SELECT MAX(id) FROM documents v WHERE v.logical_document_id=d.logical_document_id)",
                (case_id,)).fetchall()
            if len(usable) != 1:
                return None, None
            document_id = usable[0][0]
        # A cleaner/source revision is a new immutable version of the selected document.
        latest = connection.execute("SELECT MAX(id) FROM documents WHERE logical_document_id="
            "(SELECT logical_document_id FROM documents WHERE id=? AND case_id=?)", (document_id, case_id)).fetchone()[0]
        document_id = latest or document_id
    row = connection.execute("SELECT * FROM documents WHERE id=? AND case_id=?", (document_id, case_id)).fetchone()
    if row is None or not row['canonical_text'] or row['processing_error']:
        raise ValueError("Select a saved information statement with usable searchable text.")
    text = row['canonical_text']
    if hashlib.sha256(text.encode('utf-8')).hexdigest() != row['text_hash']:
        raise ValueError("The saved source text failed its hash check.")
    end = min(len(text), SUMMARY_MAX_CHARS)
    if end < len(text):
        boundary = text.rfind('\n', int(end * .8), end)
        if boundary > 0:
            end = boundary
    source = {key: row[key] for key in ('name','cleaner_version','text_hash','original_sha256')}
    source.update(document_id=row['id'], start_offset=0, end_offset=end, total_chars=len(text))
    return source, text


def _snapshot(connection, case_id, source):
    case = _require_case(connection, case_id)
    documents = [dict(row) for row in connection.execute(
        "SELECT id,logical_document_id,text_hash FROM documents WHERE case_id=? ORDER BY id", (case_id,))]
    snapshot = {'document_id': source['document_id'] if source else None, 'documents': documents,
                'question': case['question'], 'title': case['title']}
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='facts'").fetchone():
        corrected = [_fact_record(row) for row in connection.execute(
            "SELECT * FROM facts f WHERE case_id=? AND origin='human' AND id=(SELECT MAX(id) FROM facts v "
            "WHERE v.case_id=f.case_id AND v.fact_key=f.fact_key AND v.origin='human') ORDER BY fact_key", (case_id,))]
        if corrected:
            snapshot['owner_facts'] = corrected
    return snapshot


def prepare_summary(data_dir, case_id, document_id):
    from app import model, prompts
    from app.constants import SUMMARY_MAX_NOTES_CHARS, SUMMARY_MAX_OWNER_FACTS_CHARS

    with closing(connect(data_dir)) as connection:
        source, text = _source(connection, case_id, document_id)
        snapshot = _snapshot(connection, case_id, source)
    if len(snapshot['question']) > SUMMARY_MAX_NOTES_CHARS:
        raise ValueError(f"The case notes exceed the {SUMMARY_MAX_NOTES_CHARS:,}-character summary input limit.")
    payload = {'source': source, 'filing_excerpt': text[:source['end_offset']],
               'owner_notes_not_verified_facts': snapshot['question']}
    if snapshot.get('owner_facts'):
        if len(_json(snapshot['owner_facts']))>SUMMARY_MAX_OWNER_FACTS_CHARS:
            raise ValueError('Owner fact context exceeds the bounded summary input limit; no request was sent and nothing was truncated.')
        payload['owner_checked_or_corrected_facts'] = snapshot['owner_facts']
    request = {'model': model.MODEL_NAME, 'effort': 'low', 'prompt': prompts.SUMMARY_PROMPT,
               'prompt_version': prompts.SUMMARY_PROMPT_VERSION, 'input_text': _json(payload),
               'output_schema': prompts.SummaryOutput.model_json_schema(), 'runtime_context': model.runtime_context(),
               'source_snapshot': snapshot}
    if snapshot.get('owner_facts'):
        request['prompt_version'] += '+owner-facts-1'
        request['prompt'] += '\nOwner-checked or corrected facts are supplied separately. Preserve them; flag any conflict with the excerpt as unresolved. Do not claim they came from this excerpt or invent an excerpt citation for them.\n'
    return request, source, snapshot


def _checked_statement(item, source, text):
    from app.documents import match_quote

    result = dict(item)
    result.update(citation=None, detail=None)
    if item['status'] == 'assumption':
        result['detail'] = 'Model assumption; not a verified fact.'
    elif not item['quote']:
        result.update(status='unresolved', detail='No supporting quote was supplied.')
    else:
        try:
            start, end = match_quote(text, item['quote'], source['start_offset'], source['end_offset'])
            result['citation'] = {'document_id': source['document_id'], 'document_hash': source['original_sha256'],
                'text_version_id': source['document_id'], 'start_offset': start, 'end_offset': end,
                'quote': text[start:end], 'status': 'quote matched'}
            if item['status'] == 'sourced':
                result['status'] = 'quote matched'
            else:
                result['detail'] = 'Quote matched, but the model marked this statement unresolved.'
        except ValueError as error:
            result.update(status='unresolved', detail=str(error))
    return result


def _summary_record(connection, row, source, snapshot):
    from app import prompts

    value = json.loads(row['result_json'])
    run = connection.execute("SELECT * FROM model_runs WHERE id=?", (row['run_id'],)).fetchone()
    old_snapshot = json.loads(run['snapshot_json'])
    reasons = []
    if source is None or source['document_id'] != value['source']['document_id']:
        reasons.append('The selected source document/version has changed.')
    if old_snapshot['documents'] != snapshot['documents']:
        reasons.append('The case has new or changed document versions; they were not included in this summary.')
    if any(old_snapshot[key] != snapshot[key] for key in ('question','title')):
        reasons.append('The case name or owner notes have changed.')
    if old_snapshot.get('owner_facts',[]) != snapshot.get('owner_facts',[]):
        reasons.append('Owner-checked or corrected facts have changed.')
    expected_prompt = prompts.SUMMARY_PROMPT_VERSION + ('+owner-facts-1' if snapshot.get('owner_facts') else '')
    if value['prompt_version'] != expected_prompt:
        reasons.append('The summary instructions have changed.')
    return {**value, 'id': row['id'], 'run_id': row['run_id'], 'created_at': row['created_at'],
            'stale': bool(reasons), 'stale_reasons': reasons,
            'usage': json.loads(run['usage_json']) if run['usage_json'] else None}


def summary_status(data_dir, case_id):
    with closing(connect(data_dir)) as connection:
        source_error = None
        try:
            source, _ = _source(connection, case_id)
        except ValueError as error:
            source, source_error = None, str(error)
        snapshot = _snapshot(connection, case_id, source)
        selected = connection.execute("SELECT value FROM settings WHERE key=?", (f"summary_current_{case_id}",)).fetchone()
        row = connection.execute("SELECT * FROM summaries WHERE case_id=? "
            "ORDER BY (id=?) DESC,id DESC LIMIT 1", (case_id, int(selected[0]) if selected else -1)).fetchone()
        summary = _summary_record(connection, row, source, snapshot) if row else None
        runs = []
        for run in connection.execute("SELECT * FROM model_runs WHERE case_id=? AND task_type='summary' ORDER BY id DESC LIMIT 10", (case_id,)):
            runs.append({key:run[key] for key in ('id','status','detail','created_at','completed_at','retry_count')})
            runs[-1].update(usage=json.loads(run['usage_json']) if run['usage_json'] else None,
                            usage_uncertain=bool(run['usage_uncertain']))
    with _summary_lock:
        job = dict(_summary_jobs.get((str(data_dir.resolve()), case_id), {}))
    return {'selected_document_id': source['document_id'] if source else None, 'source': source,
            'summary': summary, 'runs': runs, 'active': job.get('active', False),
            'detail': job.get('detail'), 'error': job.get('error') or source_error}


def set_summary_source(data_dir, case_id, document_id):
    with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
        _source(connection, case_id, document_id)
        _setting(connection, f"summary_document_{case_id}", document_id)
    return summary_status(data_dir, case_id)


def generate_summary(data_dir, case_id, document_id):
    from app import worker

    key = (str(data_dir.resolve()), case_id)
    with _summary_lock:
        if _summary_jobs.get(key, {}).get('active'):
            raise ValueError('A summary is already running for this case.')
        event = Event()
        _summary_jobs[key] = {'active': True, 'detail': 'Preparing the selected document portion…',
                              'error': None, 'cancel': event, 'finished': Event()}
    try:
        set_summary_source(data_dir, case_id, document_id)
        worker.submit(_run_summary, data_dir, case_id, document_id, event)
    except Exception:
        with _summary_lock:
            _summary_jobs[key]['active'] = False
            _summary_jobs[key]['finished'].set()
        raise
    return summary_status(data_dir, case_id)


def cancel_summary(data_dir, case_id):
    key = (str(data_dir.resolve()), case_id)
    with _summary_lock:
        job = _summary_jobs.get(key)
        if job and job.get('active'):
            job['cancel'].set()
            job['detail'] = 'Cancellation requested. Waiting for the isolated client to stop…'
    return summary_status(data_dir, case_id)


def cancel_summaries_on_close(data_dir):
    from app.constants import MODEL_CANCEL_SECONDS

    with _summary_lock:
        jobs = [job for key, job in (*_summary_jobs.items(), *_fact_jobs.items())
                if key[0] == str(data_dir.resolve()) and job.get('active')]
        for job in jobs:
            job['cancel'].set()
            job['detail'] = 'Stopping the model request before closing. Final usage may be unknown.'
    return all(job['finished'].wait(MODEL_CANCEL_SECONDS + 8) for job in jobs)


def _run_summary(data_dir, case_id, document_id, cancel, task_type='summary', prepared=None):
    from app import model, prompts

    key = (str(data_dir.resolve()), case_id)
    jobs = _summary_jobs if task_type == 'summary' else _fact_jobs
    run_id = None
    def progress(message, submitted=False, usage=None):
        with _summary_lock:
            jobs[key]['detail'] = message
        if run_id is not None:
            with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
                connection.execute("UPDATE model_runs SET detail=?,status=CASE WHEN ? THEN 'submitted' ELSE status END, "
                    "submitted_at=CASE WHEN ? THEN COALESCE(submitted_at,?) ELSE submitted_at END, "
                    "usage_json=COALESCE(?,usage_json) WHERE id=?",
                    (message,int(submitted),int(submitted),_now(),_json(usage) if usage is not None else None,run_id))
    try:
        if cancel.is_set():
            progress('Cancelled before a model request was submitted.')
            return
        request, source, snapshot = prepared or prepare_summary(data_dir, case_id, document_id)
        request_key = hashlib.sha256(_json(request).encode('utf-8')).hexdigest()
        with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
            table = 'summaries' if task_type == 'summary' else 'facts'
            cached = connection.execute(f"SELECT s.id,r.id AS run_id FROM {table} s JOIN model_runs r ON r.id=s.run_id "
                "WHERE r.case_id=? AND r.request_key=? AND r.status='completed' ORDER BY s.id DESC LIMIT 1",
                (case_id,request_key)).fetchone()
            if cached:
                if task_type == 'summary':
                    _setting(connection, f"summary_current_{case_id}", cached['id'])
                else:
                    _select_fact_run(connection, case_id, cached['run_id'])
            else:
                cursor = connection.execute("INSERT INTO model_runs(case_id,task_type,request_key,request_json,source_json,"
                    "snapshot_json,status,detail,created_at) VALUES (?,?,?,?,?,?,'connecting',?,?)",
                    (case_id,task_type,request_key,_json(request),_json(source),_json(snapshot),'Checking subscription connection…',_now()))
                run_id = cursor.lastrowid
        if cached:
            progress(f'Saved {"summary" if task_type == "summary" else "fact batch"} reused. No new model request or subscription usage.')
            return {'status':'completed','run_id':cached['run_id'],'cached':True}
        outcome = model.generate(data_dir, request, cancel, progress)
        status = outcome['status']
        usage = outcome.get('usage')
        submitted = outcome.get('submitted', False)
        raw = outcome.get('response_text')
        result = None
        detail = outcome.get('error') or f"{task_type.capitalize()} request {status}."
        if cancel.is_set():
            status, detail = 'cancelled', 'Cancelled. The request will not restart automatically.'
        if status == 'completed' and task_type == 'facts':
            try:
                result = _checked_facts(data_dir, request, source, raw)
                detail = f"Saved fact batch: {sum(item['status']=='extracted' for item in result)} extracted; remaining values unknown."
            except (ValueError, TypeError):
                status, detail = 'failed', 'The fact response failed structural validation. Original response retained; no automatic retry.'
        elif status == 'completed':
            try:
                output = prompts.SummaryOutput.model_validate_json(raw).model_dump()
                with closing(connect(data_dir)) as connection:
                    _, text = _source(connection, case_id, document_id)
                result = {'model':request['model'], 'prompt_version':request['prompt_version'], 'source':source,
                    'is_spinoff':output['is_spinoff'], 'reasoning':_checked_statement(output['reasoning'],source,text),
                    'sentences':[_checked_statement(item,source,text) for item in output['sentences']]}
                unresolved = sum(item['status'] != 'quote matched' for item in [result['reasoning'], *result['sentences']])
                detail = f"AI summary saved. {unresolved} statement(s) are assumptions or unresolved. Only the stated opening portion was supplied."
            except (ValueError, TypeError) as error:
                from pydantic import ValidationError
                status = 'failed'
                detail = ('The returned summary did not match the required structure. No automatic retry.'
                          if isinstance(error, ValidationError) else f'Summary validation failed: {error}')
        with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
            saved = connection.execute("SELECT submitted_at,usage_json FROM model_runs WHERE id=?", (run_id,)).fetchone()
            submitted = submitted or saved['submitted_at'] is not None
            if usage is None and saved['usage_json']:
                usage = json.loads(saved['usage_json'])
            uncertain = bool(submitted and (status != 'completed' or usage is None))
            if uncertain:
                detail += ' Final usage is uncertain; any reported usage may be partial.'
            connection.execute("UPDATE model_runs SET status=?,detail=?,completed_at=?,response_text=?,usage_json=?,"
                "usage_uncertain=?,metadata_json=?,retry_count=? WHERE id=?",
                (status,detail,_now(),raw,_json(usage) if usage is not None else None,int(uncertain),
                 _json({**outcome.get('metadata',{}), 'retries':outcome.get('retries',[]),
                        'tool_activity':outcome.get('tool_activity',[])}),len(outcome.get('retries',[])),run_id))
            if result is not None and status == 'completed' and task_type == 'facts':
                for fact in result:
                    _insert_fact(connection,case_id,document_id,run_id,None,'model',fact)
                _select_fact_run(connection,case_id,run_id)
            elif result is not None and status == 'completed':
                cursor = connection.execute("INSERT INTO summaries(case_id,run_id,created_at,result_json) VALUES (?,?,?,?)",
                    (case_id,run_id,_now(),_json(result)))
                _setting(connection, f"summary_current_{case_id}", cursor.lastrowid)
        progress(detail)
        if status == 'failed':
            with _summary_lock:
                jobs[key]['error'] = detail
        return {'status':status,'run_id':run_id,'submitted':submitted,'detail':detail}
    except Exception as error:
        logging.getLogger(__name__).exception('%s operation failed.',task_type)
        detail = f'{task_type.capitalize()} failed: {error}. Existing research has been retained; no automatic retry.'
        if run_id is not None:
            with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
                connection.execute("UPDATE model_runs SET status='failed',detail=?,completed_at=?,"
                    "usage_uncertain=(submitted_at IS NOT NULL) WHERE id=?", (detail,_now(),run_id))
        with _summary_lock:
            jobs[key].update(detail=detail,error=detail)
        return {'status':'failed','run_id':run_id,'detail':detail}
    finally:
        if task_type == 'summary':
            with _summary_lock:
                jobs[key]['active'] = False
                jobs[key]['finished'].set()


def read_summary_evidence(data_dir, summary_id, index):
    from app.documents import read_citation

    with closing(connect(data_dir)) as connection:
        row = connection.execute("SELECT result_json FROM summaries WHERE id=?", (summary_id,)).fetchone()
    if row is None:
        raise ValueError('That saved summary does not exist.')
    value = json.loads(row[0])
    statements = [value['reasoning'], *value['sentences']]
    if not 0 <= index < len(statements) or statements[index]['citation'] is None:
        raise ValueError('This statement has no verified supporting quote.')
    return read_citation(data_dir, statements[index]['citation'])


def recover_model_runs(data_dir):
    with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
        connection.execute("UPDATE model_runs SET status='interrupted',completed_at=?,"
            "usage_uncertain=(submitted_at IS NOT NULL),detail=CASE WHEN submitted_at IS NULL THEN "
            "'Interrupted before submission. No automatic restart.' ELSE "
            "'Interrupted after submission. Final usage is uncertain; no automatic restart.' END "
            "WHERE status IN ('queued','connecting','submitted')", (_now(),))


def subscription_state(data_dir):
    from app import model

    with closing(connect(data_dir)) as connection:
        row = connection.execute("SELECT value FROM settings WHERE key='subscription_status'").fetchone()
    value = json.loads(row[0]) if row else {'checked_at':None,'auth_type':None,'plan_type':None,
        'available':None,'model':model.MODEL_NAME,'usage':None,'error':None}
    with _summary_lock:
        job = dict(_connection_jobs.get(str(data_dir.resolve()), {}))
    return {**value, 'active':job.get('active',False),'detail':job.get('detail')}


def check_subscription(data_dir):
    from app import worker

    key = str(data_dir.resolve())
    with _summary_lock:
        if _connection_jobs.get(key,{}).get('active'):
            return subscription_state(data_dir)
        _connection_jobs[key] = {'active':True,'detail':'Checking existing ChatGPT subscription…'}
        try:
            worker.submit(_check_subscription, data_dir)
        except Exception:
            _connection_jobs[key]['active'] = False
            raise
    return subscription_state(data_dir)


def _check_subscription(data_dir):
    from app import model

    key = str(data_dir.resolve())
    try:
        checked = model.subscription_status(data_dir)
        value = {'checked_at':checked.get('checked_at'), 'auth_type':checked.get('auth_type'),
            'plan_type':checked.get('plan'), 'available':checked.get('model_available'),
            'model':model.MODEL_NAME, 'usage':checked.get('allowance'), 'error':checked.get('error')}
        with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
            _setting(connection,'subscription_status',_json(value))
    except Exception as error:
        value = {'checked_at':_now(),'auth_type':None,'plan_type':None,'available':None,
                 'model':model.MODEL_NAME,'usage':None,'error':str(error)}
        with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
            _setting(connection,'subscription_status',_json(value))
    finally:
        with _summary_lock:
            _connection_jobs[key] = {'active':False,'detail':'Subscription status check finished.'}


def _fact_source(connection, case_id, document_id=None):
    if document_id is None:
        selected = connection.execute('SELECT value FROM settings WHERE key=?', (f'facts_document_{case_id}',)).fetchone()
        document_id = int(selected[0]) if selected else None
    source, _ = _source(connection, case_id, document_id)
    if source is None:
        return None
    row = connection.execute('SELECT filing_date,accession_number FROM documents WHERE id=?',
                             (source['document_id'],)).fetchone()
    return {key: value for key, value in {**source, **dict(row)}.items() if key not in ('start_offset','end_offset')}


def _fact_record(row):
    return {**json.loads(row['value_json']), 'id':row['id'], 'key':row['fact_key'],
            'status':row['status'], 'origin':row['origin'], 'document_id':row['document_id'],
            'run_id':row['run_id'], 'previous_id':row['previous_id'], 'created_at':row['created_at'],
            'citations':json.loads(row['evidence_json'])}


def _insert_fact(connection, case_id, document_id, run_id, previous_id, origin, fact):
    value = {key:item for key,item in fact.items() if key not in ('key','status','citations')}
    return connection.execute('INSERT INTO facts(case_id,fact_key,document_id,run_id,previous_id,origin,status,'
        'created_at,value_json,evidence_json) VALUES (?,?,?,?,?,?,?,?,?,?)',
        (case_id,fact['key'],document_id,run_id,previous_id,origin,fact['status'],_now(),
         _json(value),_json(fact['citations']))).lastrowid


def _select_fact_run(connection, case_id, run_id):
    for row in connection.execute('SELECT id,fact_key FROM facts WHERE case_id=? AND run_id=?', (case_id,run_id)):
        _setting(connection,f"facts_current_{case_id}_{row['fact_key']}",row['id'])


def facts_status(data_dir, case_id):
    from app.constants import FACT_KEYS, FACT_RETRIEVAL_VERSION
    from app.prompts import FACT_PROMPT_VERSION

    with closing(connect(data_dir)) as connection:
        _require_case(connection,case_id)
        error = None
        try:
            source = _fact_source(connection,case_id)
        except ValueError as problem:
            source, error = None, str(problem)
        records = [_fact_record(row) for row in connection.execute(
            'SELECT * FROM facts WHERE case_id=? ORDER BY id DESC', (case_id,))]
        rows, run_ids, warnings = [], set(), ['Fixed searches cover selected passages, not the whole filing. Quote matched confirms words, not interpretation.']
        for key,label in FACT_KEYS.items():
            history = [item for item in records if item['key']==key]
            selected = connection.execute('SELECT value FROM settings WHERE key=?',
                                          (f'facts_current_{case_id}_{key}',)).fetchone()
            proposals = [item for item in history if item['origin']=='model' and source
                         and item['document_id']==source['document_id']]
            proposal = next((item for item in proposals if selected and item['id']==int(selected[0])),
                            proposals[0] if proposals else None)
            human = next((item for item in history if item['origin']=='human'),None)
            effective = human or proposal
            fields = ('value','unit','currency','entity','period','basis','kind','qualifications','document_id')
            conflict = bool(human and proposal and any(human[field]!=proposal[field] for field in fields))
            if human and source and human['document_id'] != source['document_id']:
                warnings.append(f'{label}: the owner record belongs to a different document version (or is an assumption); it has been preserved.')
            rows.append({'key':key,'label':label,'effective':effective,'proposal':proposal,
                         'conflict':conflict,'history':history})
            if proposal:
                run_ids.add(proposal['run_id'])
        runs, coverage = [], []
        for run in connection.execute("SELECT * FROM model_runs WHERE case_id=? AND task_type='facts' ORDER BY id DESC", (case_id,)):
            if len(runs)<12:
                runs.append({**{key:run[key] for key in ('id','status','detail','created_at','completed_at','retry_count')},
                    'usage':json.loads(run['usage_json']) if run['usage_json'] else None,
                    'usage_uncertain':bool(run['usage_uncertain'])})
            if run['id'] in run_ids:
                request = json.loads(run['request_json'])
                payload = json.loads(request['input_text'])
                coverage.append({**{key:payload[key] for key in ('source','passages','searches','key_passages')},
                                 'run_id':run['id'],'prompt_version':request['prompt_version']})
                if request['prompt_version'] != FACT_PROMPT_VERSION or payload.get('retrieval_version') != FACT_RETRIEVAL_VERSION:
                    warnings.insert(0,'Saved deal terms use earlier extraction rules. They have been preserved; the revised extraction has not produced a new result yet.')
                warnings.extend(payload.get('warnings',[]))
    with _summary_lock:
        job = dict(_fact_jobs.get((str(data_dir.resolve()),case_id),{}))
    return {'selected_document_id':source['document_id'] if source else None,'source':source,'rows':rows,
            'active':job.get('active',False),'detail':job.get('detail'),'error':job.get('error') or error,
            'warnings':list(dict.fromkeys(warnings)),'runs':runs,'coverage':coverage}


def set_facts_source(data_dir, case_id, document_id):
    with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
        _fact_source(connection,case_id,document_id)
        _setting(connection,f'facts_document_{case_id}',document_id)
    return facts_status(data_dir,case_id)


def extract_facts(data_dir, case_id, document_id):
    from app import worker

    key = (str(data_dir.resolve()),case_id)
    with _summary_lock:
        if _fact_jobs.get(key,{}).get('active'):
            raise ValueError('Deal term extraction is already running for this case.')
        cancel = Event()
        _fact_jobs[key] = {'active':True,'detail':'Searching the selected information statement…',
                           'error':None,'cancel':cancel,'finished':Event()}
    try:
        set_facts_source(data_dir,case_id,document_id)
        worker.submit(_run_facts,data_dir,case_id,document_id,cancel)
    except Exception:
        with _summary_lock:
            _fact_jobs[key]['active'] = False
            _fact_jobs[key]['finished'].set()
        raise
    return facts_status(data_dir,case_id)


def cancel_facts(data_dir, case_id):
    with _summary_lock:
        job = _fact_jobs.get((str(data_dir.resolve()),case_id),{})
        if job.get('active'):
            job['cancel'].set()
            job['detail'] = 'Cancelling extraction. Completed batches are retained; requests will not restart.'
    return facts_status(data_dir,case_id)


def _run_facts(data_dir, case_id, document_id, cancel):
    from app import documents, model, prompts
    from app.constants import FACT_QUERIES, FACT_BATCHES, FACT_BATCH_MAX_CHARS, FACT_RETRIEVAL_VERSION

    job_key = (str(data_dir.resolve()),case_id)
    completed, reused = 0, 0
    try:
        retrieval = documents.retrieve_fact_passages(data_dir,case_id,document_id,FACT_QUERIES)
        context = model.runtime_context()
        by_id = {passage['id']:passage for passage in retrieval['passages']}
        for batch_index, keys in enumerate(FACT_BATCHES):
            if cancel.is_set():
                break
            # Round-robin by key keeps a long financial hit from excluding all other terms.
            candidates = list(dict.fromkeys(identity for index in range(max(
                (len(retrieval['key_passages'][key]) for key in keys),default=0))
                for key in keys for identity in retrieval['key_passages'][key][index:index+1]))
            selected, used = [], 0
            for identity in candidates:
                passage = by_id[identity]
                if used+len(passage['text']) <= FACT_BATCH_MAX_CHARS:
                    selected.append(identity)
                    used += len(passage['text'])
            payload = {'keys':list(keys),'source':retrieval['source'],
                'passages':[{**by_id[identity],'text':' '.join(by_id[identity]['text'].split())} for identity in selected],
                'key_passages':{key:[identity for identity in retrieval['key_passages'][key] if identity in selected] for key in keys},
                'searches':{key:retrieval['searches'][key] for key in keys},
                'warnings':list(retrieval['warnings']),'retrieval_version':FACT_RETRIEVAL_VERSION,
                'passage_character_limit':FACT_BATCH_MAX_CHARS}
            if len(selected)<len(candidates):
                payload['warnings'].append(f'Batch {batch_index+1}: some retrieved context was omitted to keep the {FACT_BATCH_MAX_CHARS:,}-character limit.')
            request = {'model':model.MODEL_NAME,'effort':'low','prompt':prompts.FACT_PROMPT,
                'prompt_version':prompts.FACT_PROMPT_VERSION,'input_text':_json(payload),
                'output_schema':prompts.FactsOutput.model_json_schema(),'runtime_context':context}
            with _summary_lock:
                _fact_jobs[job_key]['detail'] = f'Extracting batch {batch_index+1} of {len(FACT_BATCHES)}…'
            outcome = _run_summary(data_dir,case_id,document_id,cancel,'facts',
                                   (request,retrieval['source'],{'retrieval':payload}))
            if outcome and outcome['status']=='completed':
                completed += 1
                reused += int(outcome.get('cached',False))
            elif not outcome or outcome['status'] in ('cancelled','interrupted') or not outcome.get('submitted'):
                break
        with _summary_lock:
            _fact_jobs[job_key]['detail'] = (f'{completed} of {len(FACT_BATCHES)} batches saved; {reused} reused from cache. '
                + ('Cancelled; no automatic restart. Final usage may be uncertain.' if cancel.is_set()
                   else 'Unknown terms and failed checks remain visible.'))
    except Exception as error:
        logging.getLogger(__name__).exception('Fact extraction failed.')
        with _summary_lock:
            _fact_jobs[job_key].update(error=str(error),detail='Extraction stopped; existing research was preserved.')
    finally:
        with _summary_lock:
            _fact_jobs[job_key]['active'] = False
            _fact_jobs[job_key]['finished'].set()


def _checked_facts(data_dir, request, source, raw):
    import re
    from decimal import Decimal, InvalidOperation
    from app import documents, prompts
    from app.constants import FACT_FINANCIAL_KEYS

    output = prompts.FactsOutput.model_validate_json(raw).model_dump()
    payload = json.loads(request['input_text'])
    if len(output['facts'])!=len(payload['keys']) or {item['key'] for item in output['facts']}!=set(payload['keys']):
        raise ValueError('The response must contain each requested fact exactly once.')
    with closing(connect(data_dir)) as connection:
        row = connection.execute('SELECT canonical_text,text_hash FROM documents WHERE id=?', (source['document_id'],)).fetchone()
    text = row['canonical_text']
    if row['text_hash']!=source['text_hash'] or hashlib.sha256(text.encode('utf-8')).hexdigest()!=source['text_hash']:
        raise ValueError('The selected text version failed its hash check.')
    passages = {item['id']:item for item in payload['passages']}
    normalized = lambda value: ' '.join(value.split()).casefold()
    contains = lambda value, quote: bool(re.search(r'(?<![\w.,/])'+re.escape(normalized(value))+r'(?![\w/]|[.,]\d)',quote))
    results = []
    for item in output['facts']:
        result = {key:value for key,value in item.items() if key!='evidence'}
        result.update(status='unknown',citations=[])
        failures = []
        supported = {}
        for evidence in item['evidence']:
            try:
                if evidence['passage_id'] not in passages:
                    raise ValueError('Evidence refers to a passage not supplied in this batch.')
                passage = passages[evidence['passage_id']]
                if passage['document_id']!=source['document_id'] or normalized(text[passage['start_offset']:passage['end_offset']])!=normalized(passage['text']):
                    raise ValueError('Evidence belongs to a different document version or changed passage.')
                start,end = documents.match_quote(text,evidence['quote'],passage['start_offset'],passage['end_offset'])
                citation = {'document_id':source['document_id'],'text_version_id':source['document_id'],
                    'document_hash':source['original_sha256'],'start_offset':start,'end_offset':end,
                    'quote':text[start:end],'status':'quote matched'}
                result['citations'].append({'citation':citation,'fields':evidence['fields']})
                for field in evidence['fields']:
                    supported.setdefault(field,[]).append(normalized(text[start:end]))
            except ValueError as error:
                failures.append(str(error))
        value = item['value']
        if item['finding']=='value':
            if not value or not any(contains(value,quote) for quote in supported.get('value',[])):
                failures.append('The proposed value does not appear in a matched value quote.')
            if value and re.fullmatch(r'\s*(?:\[\s*(?:●|•)?\s*\]|_{2,})\s*',value):
                failures.append('A printed placeholder is unknown, not an extracted value.')
                result['finding'] = 'blank_placeholder'
            if item['qualifications'] and (not item['qualifications'].strip() or not all(
                    any(contains(part,quote) for quote in supported.get('qualifications',[]))
                    for part in item['qualifications'].splitlines() if part.strip())):
                failures.append('The proposed qualifications lack their own matched supporting wording.')
            if item['key']=='distribution_ratio' and item['unit']!='Spinco shares received per parent share':
                failures.append('The ratio direction must be Spinco shares received per parent share.')
            if item['key']=='tax_free_condition' and value and not re.search(r'opinion|ruling|condition|require',value,re.I):
                failures.append('Mentioning tax-free status alone does not establish a distribution condition.')
            if item['key']=='tax_free_condition' and value and re.search(r'actions prohibited by these covenants',value,re.I):
                failures.append('A covenant about later prohibited actions is not the tax condition required before distribution.')
            financial = item['key'] in FACT_FINANCIAL_KEYS and (item['key'] not in
                ('pension_and_other_liabilities','management_equity_awards') or bool(value and re.search(r'[$£€%]|\d[\d,.]*\s+(?:million|billion)',value,re.I)))
            if financial and value:
                # Decimal validates numerical tokens without doing a calculation or changing printed text.
                for number in re.findall(r'(?<!\w)-?\d[\d,]*(?:\.\d+)?',value):
                    try:
                        if not Decimal(number.replace(',','')).is_finite():
                            raise InvalidOperation
                    except InvalidOperation:
                        failures.append('A financial quantity is not a finite decimal.')
                metadata = ('unit','entity','period') if item['key']=='shares_outstanding_after' else ('unit','currency','entity','period')
                for field in metadata:
                    parts = item[field].splitlines() if field=='period' and item[field] else [item[field]]
                    quotes = supported.get(field,[])
                    if field=='unit' and item['key']=='shares_outstanding_after':
                        # A possessive does not change the unit; keep the original quote and amount intact.
                        strip_possessive = lambda value: re.sub(r'\bshares of (?:its|our|their) common stock\b',
                                                               'shares of common stock',value)
                        parts = [strip_possessive(normalized(part)) if part else part for part in parts]
                        quotes = [strip_possessive(quote) for quote in quotes]
                    if not item[field] or not item[field].strip() or not all(part and any(contains(part,quote) for quote in quotes)
                                                  for part in parts if part is None or part.strip()):
                        failures.append(f'Financial {field} is missing or lacks matched context.')
                if item['basis']=='unknown':
                    failures.append('The financial basis is unknown.')
            if item['key'].startswith('pro_forma_') and (item['basis']!='pro_forma'
                    or not any('pro forma' in quote for quote in supported.get('basis',[]))):
                failures.append('A historical figure cannot fill this pro forma field; explicit pro forma context is required.')
            if item['key'] in ('record_date','distribution_date') and value and re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
                try:
                    datetime.strptime(value,'%Y-%m-%d')
                except ValueError:
                    failures.append('The proposed calendar date is invalid.')
            if not failures:
                result['status'] = 'extracted'
        elif value is not None:
            failures.append('An unresolved finding cannot contain a known value.')
        elif item['finding']=='blank_placeholder' and not any(re.search(r'\[\s*(?:●|•)?\s*\]|_{2,}',quote)
                for quote in supported.get('value',[])):
            failures.append('The claimed placeholder has no recognisable blank marker in its matched passage.')
        elif item['finding']=='conflicting' and len(result['citations'])<2:
            failures.append('The claimed conflict lacks two matched supporting passages.')
        if result['status']=='unknown':
            result['value'] = None
        if failures:
            result['reason'] += ' Validation: '+ ' '.join(dict.fromkeys(failures)) + ' Original proposal retained in the run record.'
        results.append(result)
    return results


def read_fact_evidence(data_dir, fact_id, index):
    from app.documents import read_citation

    with closing(connect(data_dir)) as connection:
        row = connection.execute('SELECT * FROM facts WHERE id=?', (fact_id,)).fetchone()
    if row is None:
        raise ValueError('That saved fact does not exist.')
    citations = json.loads(row['evidence_json'])
    if not 0<=index<len(citations):
        raise ValueError('That fact has no matching evidence link.')
    return read_citation(data_dir,citations[index]['citation'])


def check_fact(data_dir, case_id, fact_id, reason):
    if not reason.strip():
        raise ValueError('Record a reason for checking this fact.')
    with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
        row = connection.execute('SELECT * FROM facts WHERE id=? AND case_id=?', (fact_id,case_id)).fetchone()
        if row is None or row['origin']!='model' or row['status']!='extracted':
            raise ValueError('Only an extracted proposal can be marked checked.')
        record = _fact_record(row)
        for evidence in record['citations']:
            from app.documents import read_citation
            read_citation(data_dir,evidence['citation'])
        fact = {key:value for key,value in record.items() if key not in
                ('id','origin','document_id','run_id','previous_id','created_at')}
        fact.update(status='checked',reason=reason.strip())
        _insert_fact(connection,case_id,row['document_id'],None,fact_id,'human',fact)
    return facts_status(data_dir,case_id)


def correct_fact(data_dir, *, case_id, key, previous_id, value, unit, currency, entity, period,
                 basis, kind, qualifications, reason, document_id, quote):
    import re
    from app import documents, prompts
    from app.constants import FACT_KEYS

    if key not in FACT_KEYS or not reason.strip():
        raise ValueError('Choose a fact and record the reason for the correction.')
    value = value.strip() if value else None
    fact = prompts.FactProposal(key=key,value=value,unit=unit,currency=currency,entity=entity,period=period,
        basis=basis,kind=kind,finding='value' if value else 'not_found',reason=reason,
        qualifications=qualifications,evidence=[]).model_dump()
    del fact['evidence']
    fact.update(status='checked' if value else 'unknown',citations=[])
    from app.constants import FACT_FINANCIAL_KEYS
    if value and key in FACT_FINANCIAL_KEYS and re.search(r'\d',value):
        if not all((unit,entity,period)) or (key!='shares_outstanding_after' and not currency):
            raise ValueError('A financial correction needs its unit, company/entity, period and applicable currency.')
    with DATA_LOCK, closing(connect(data_dir)) as connection, connection:
        current = next(item for item in facts_status(data_dir,case_id)['rows'] if item['key']==key)['effective']
        if previous_id!=(current['id'] if current else None):
            raise ValueError('This fact changed while the correction was open. Reopen it before saving.')
        if document_id is not None:
            _fact_source(connection,case_id,document_id)
        if quote:
            if document_id is None:
                raise ValueError('Select the document version for this quotation.')
            previous = next((item['citation'] for item in (current['citations'] if current else [])
                             if item['citation']['document_id']==document_id and item['citation']['quote']==quote),None)
            opened = documents.read_citation(data_dir,previous) if previous else documents.read_document(data_dir,document_id,quote=quote)
            if value and ' '.join(value.split()).casefold() not in ' '.join(opened['citation']['quote'].split()).casefold():
                raise ValueError('The corrected value must appear in its supporting quote. Use an explicit assumption if it has no source.')
            fact['citations'] = [{'citation':opened['citation'],'fields':['value']}]
        elif value is not None and kind!='assumption':
            raise ValueError('A published or forecast correction needs a supporting quote; an unsourced value must be an assumption.')
        _insert_fact(connection,case_id,document_id,None,previous_id,'human',fact)
    return facts_status(data_dir,case_id)
