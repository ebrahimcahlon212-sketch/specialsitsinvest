"""Deterministic event assembly and independent saved model-review reconciliation."""
import csv
import hashlib
import json
from pathlib import Path
from .quality import require, source_excerpt, primary_path

FIELDS = ['candidate_id', 'decision', 'event_json', 'reason']
IMMUTABLE = ('event_id', 'candidate_id', 'event_type', 'application_number', 'action_date',
             'action_evidence', 'announced_at', 'announcement_evidence', 'source', 'locator')


def draft(candidates):
    events = []
    for c in candidates:
        event = dict(event_id=c['candidate_id'], candidate_id=c['candidate_id'],
                     company=c.get('company'), event_type=c.get('event_type'),
                     application_number=c.get('application'), action_date=c.get('action_date'),
                     action_evidence=c.get('action_evidence'),
                     announced_at=c.get('acceptanceDateTime'),
                     announcement_evidence=c.get('announcement_evidence'),
                     source=c.get('source'), locator=c.get('locator'))
        app = c.get('application', '')
        event.update(application=app[:3] if app else None, original=c.get('original'))
        events.append(event)
    return events


def prepare(collections, output):
    from .pipeline import assemble
    snapshot = assemble({'events': []}, collections)
    snapshot['event_drafts'] = draft(snapshot['candidates'])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'candidates.json').write_text(json.dumps(snapshot, indent=2) + '\n')
    for model in ('claude', 'codex'):
        (output / f'{model}-review.md').write_text(
            'Independently review every candidate in ' + str((output / 'candidates.json').resolve()) +
            '. Read its primary sources. Return CSV with columns ' + ','.join(FIELDS) +
            '. decision is include, exclude or unresolved. event_json is a JSON object with sourced event fields. '
            'Retain the code-assembled identity and FDA date. Link FDA candidates to a company 8-K using '
            'announcement_evidence (source, JSON pointer, index) and its acceptanceDateTime. '
            'Do not accept dates from prose. Flag contradictory press releases in reason and use unresolved. '
            'Supply ticker, drug, listing/applicant/share evidence, inventory_sources and independent tags. '
            'Every inclusion or exclusion needs review_evidence with a primary source and line range. '
            'Set press_release_conflict to true if prose contradicts structured timing, otherwise false. Use unresolved for missing evidence. Do not read the other review. Put CSV between <<<BEGIN OUTPUT>>> and <<<END OUTPUT>>>.\n')
    return snapshot


def substantive(value):
    """Compare assertions, keeping provenance differences in the audit record."""
    if isinstance(value, list):
        items = [substantive(v) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True))
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if (key in {'source', 'locator', 'line_start', 'line_end', 'tagger', 'agreed',
                    'review_observations', 'event_review'} or key.endswith(('_evidence', '_source', '_sources'))):
            continue
        if key in {'company', 'drug'} and isinstance(item, str):
            item = ' '.join(__import__('re').findall(r'\w+', item.casefold()))
        result[key] = substantive(item)
    return result


def reconcile(prepared, reviews, output, resolutions=None):
    require(len(reviews) == 2 and Path(reviews[0]).resolve() != Path(reviews[1]).resolve(),
            'Two independent review files are required.')
    source = json.loads(Path(prepared).read_text())
    drafts = {e['candidate_id']: e for e in source['event_drafts']}
    results = []
    for path in reviews:
        with Path(path).open(newline='') as f:
            rows = list(csv.DictReader(f))
        require(len(rows) == len({r['candidate_id'] for r in rows}), 'Duplicate candidate review.')
        indexed = {r['candidate_id']: r for r in rows}
        require(set(indexed) == set(drafts), 'Each review must cover the complete candidate list.')
        results.append(indexed)
    resolved = {}
    if resolutions is not None:
        with Path(resolutions).open(newline='') as f:
            for row in csv.DictReader(f):
                require(row['candidate_id'] not in resolved, 'Duplicate human resolution.')
                require(row['candidate_id'] in drafts and row.get('reason', '').strip(),
                        'Human resolution needs a known candidate and a reason.')
                resolved[row['candidate_id']] = row
    agreed, disputes = [], []
    for key, original in drafts.items():
        a, b = (rows[key] for rows in results)
        ea, eb = json.loads(a['event_json']), json.loads(b['event_json'])
        for event in (ea, eb):
            for field in IMMUTABLE:
                if original.get(field) is not None:
                    require(event.get(field) == original[field], 'Review changed a structured candidate field. ' + field)
        decision = a['decision']
        resolution = resolved.get(key)
        if resolution:
            ea = json.loads(resolution['event_json'])
            decision = resolution['decision']
            require(decision in ('include', 'exclude'), 'Human decision must include or exclude.')
            for field in IMMUTABLE:
                if original.get(field) is not None:
                    require(ea.get(field) == original[field], 'Resolution changed a structured field. ' + field)
            require(ea.get('press_release_conflict') is False,
                    'Resolve the structured timing conflict before publishing.')
            ea['event_resolution'] = dict(resolved_by='Ebrahim', reason=resolution['reason'],
                source_file=str(Path(resolutions).resolve()),
                feature_values={t['feature']: t['value'] for t in ea.get('tags', [])})
            ea['tags'] = [dict(t, tagger='Ebrahim') for t in ea.get('tags', [])]
        elif (decision != b['decision'] or substantive(ea) != substantive(eb)
                or decision not in ('include', 'exclude')
                or ea.get('press_release_conflict') is not False):
            disputes.append(dict(candidate_id=key, review_one=json.dumps(a), review_two=json.dumps(b)))
            continue
        else:
            ea['tags'] = [dict(t, tagger=model) for model, event in (('claude', ea), ('codex', eb))
                          for t in event.get('tags', [])]
        # Keep both independent readings, including differing source ranges.
        ea['review_observations'] = [dict(reviewer=model, decision=r['decision'],
                                         reason=r['reason'], event=json.loads(r['event_json']))
                                     for model, r in (('claude', a), ('codex', b))]
        from .engine import reconcile_tags
        ea = reconcile_tags(ea)
        seal(ea, decision, [str(Path(p).resolve()) for p in reviews])
        agreed.append(ea)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    with (output / 'events.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS); writer.writeheader()
        for e in agreed:
            writer.writerow(dict(candidate_id=e['candidate_id'], decision=e['event_review']['decision'],
                                 event_json=json.dumps(e, sort_keys=True), reason=e.get('event_resolution', {}).get('reason', 'Both reviews agree on substantive fields')))
    with (output / 'disagreements.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['candidate_id', 'review_one', 'review_two'])
        writer.writeheader(); writer.writerows(disputes)
    source['gaps'] = [g for g in source.get('gaps', []) if 'collected candidates still need event review' not in g]
    source.update(as_of=__import__('datetime').date.today().isoformat(), events=agreed, gaps=source.get('gaps', []) +
                  ([f'{len(disputes)} disagreements require Ebrahim in disagreements.csv.'] if disputes else []))
    (output / 'reviewed.json').write_text(json.dumps(source, indent=2) + '\n')
    return len(disputes)


def primary_hashes(value):
    paths = set()
    def visit(v):
        if isinstance(v, dict):
            if v.get('source'):
                paths.add(primary_path(v['source']))
            for key, child in v.items():
                if key != 'event_review':
                    visit(child)
        elif isinstance(v, list):
            for child in v:
                visit(child)
    visit(value)
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def seal(event, decision, reviewers):
    """Called only after reconciliation, hashing primary evidence at review time."""
    source_excerpt(event['review_evidence'])
    for observation in event.get('review_observations', []):
        if observation['decision'] != 'unresolved' or observation['event'].get('review_evidence'):
            source_excerpt(observation['event']['review_evidence'])
    event['event_review'] = dict(decision=decision, reviewers=reviewers,
        primary_hashes=primary_hashes(event),
        digest=hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest())


def verify_event_review(event):
    review = event['event_review']
    require(len(set(review['reviewers'])) == 2, 'Independent event reviews required.')
    payload = {k: v for k, v in event.items() if k != 'event_review'}
    require(hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() == review['digest'],
            'Reviewed event changed. Repeat independent review.')
    require(primary_hashes(payload) == review['primary_hashes'],
            'Reviewed primary source changed. Repeat independent review.')
    source_excerpt(event['review_evidence'])
