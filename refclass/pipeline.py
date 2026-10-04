"""Join staged primary-source candidates to explicitly reviewed event records.

Unreviewed candidates remain in the database census and never silently become
eligible events. A live build still needs independent timestamps and IBKR bars.
"""
import json
from pathlib import Path


def assemble(snapshot, paths):
    snapshot = dict(snapshot)
    snapshot["prices"] = list(snapshot.get("prices", []))
    events = {e['event_id']: e for e in snapshot.get('events', [])}
    candidates = {}
    gaps = list(snapshot.get('gaps', []))
    coverage = dict(snapshot.get('coverage', {}))
    for path in paths:
        data = json.loads(Path(path).read_text())
        source = data['source']
        if source not in ('drugs_at_fda', 'openfda_crl', 'edgar', 'ibkr'):
            raise ValueError('Unknown collection source')
        coverage[source] = dict(path=str(path), complete=data.get('complete', False),
                                scope=data.get('scope', {}))
        gaps.extend(data.get('gaps', []))
        gaps.extend(data.get('coverage_gaps', []))
        if not data.get('complete'):
            gaps.append(f'{source}. Collection is incomplete.')
        for row in data.get('candidates', []):
            identity = row['candidate_id']
            if identity in candidates and candidates[identity] != row:
                raise ValueError('Conflicting candidate records. ' + identity)
            candidates[identity] = row
        for row in data.get('filings', []):
            identity = 'edgar:' + row['accessionNumber']
            candidates[identity] = dict(row, candidate_id=identity)
        snapshot.setdefault('prices', []).extend(data.get('prices', []))
    linked = set()
    for event in events.values():
        identity = event.get('candidate_id')
        if identity not in candidates:
            raise ValueError('Reviewed event does not link to a collected candidate. ' + event['event_id'])
        candidate = candidates[identity]
        if candidate.get('event_type') and event['event_type'] != candidate['event_type']:
            raise ValueError('Reviewed event type conflicts with collected candidate.')
        if candidate.get('application') and event.get('application_number') != candidate['application']:
            raise ValueError('Reviewed application conflicts with collected candidate.')
        linked.add(identity)
    pending = sorted(set(candidates) - linked)
    if pending:
        gaps.append(f'{len(pending)} collected candidates still need event review or a sourced exclusion.')
    snapshot.update(events=list(events.values()), candidates=list(candidates.values()),
                    pending_candidates=pending, coverage=coverage, gaps=sorted(set(gaps)))
    return snapshot
