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


def reconcile(prepared, reviews, output):
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
    agreed, disputes = [], []
    for key, original in drafts.items():
        a, b = (rows[key] for rows in results)
        ea, eb = json.loads(a['event_json']), json.loads(b['event_json'])
        tags_a, tags_b = ea.pop('tags', []), eb.pop('tags', [])
        clean_tags = lambda rows: [{k: v for k, v in t.items() if k not in ('tagger', 'agreed')} for t in rows]
        if (a['decision'] != b['decision'] or ea != eb or a['decision'] not in ('include', 'exclude')
                or ea.get('press_release_conflict') is not False or clean_tags(tags_a) != clean_tags(tags_b)):
            disputes.append(dict(candidate_id=key, review_one=json.dumps(a), review_two=json.dumps(b)))
            continue
        for field in IMMUTABLE:
            if original.get(field) is not None:
                require(ea.get(field) == original[field], 'Review changed a structured candidate field. ' + field)
        ea['tags'] = [dict(t, tagger=model) for model, tags in (('claude', tags_a), ('codex', tags_b)) for t in tags]
        from .engine import reconcile_tags
        ea = reconcile_tags(ea)
        seal(ea, a['decision'], [str(Path(p).resolve()) for p in reviews])
        agreed.append(ea)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    with (output / 'events.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS); writer.writeheader()
        for e in agreed:
            writer.writerow(dict(candidate_id=e['candidate_id'], decision=e['event_review']['decision'],
                                 event_json=json.dumps(e, sort_keys=True), reason='Both reviews agree'))
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
