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
    candidates = {c['candidate_id']: c for c in snapshot.get('candidates', [])}
    gaps = list(snapshot.get('gaps', []))
    coverage = dict(snapshot.get('coverage', {}))
    for path in paths:
        data = json.loads(Path(path).read_text())
        source = data['source']
        if source not in ('drugs_at_fda', 'openfda_crl', 'edgar', 'ibkr', 'massive'):
            raise ValueError('Unknown collection source')
        entry = dict(path=str(path), complete=data.get('complete', False), scope=data.get('scope', {}))
        previous = coverage.get(source, [])
        if not isinstance(previous, list):
            previous = [previous]
        coverage[source] = previous + [entry] if entry not in previous else previous
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
        snapshot.setdefault('prices', []).extend(data.get('prices', []) if source != 'ibkr' else [])
        snapshot.setdefault('ibkr_checks', []).extend(data.get('ibkr_checks', []))
    # XBI is intentionally included in each ticker collection. Repeated bars
    # may share values, but conflicting vintages must not silently overwrite.
    for name, fields in (('prices', ('close', 'adjusted_close')), ('ibkr_checks', ('close',))):
        unique = {}
        for row in snapshot.get(name, []):
            key = (row['ticker'], row['date'])
            if key in unique and any(unique[key][f] != row[f] for f in fields):
                raise ValueError('Conflicting ' + name + ' for ' + str(key))
            unique[key] = row
        snapshot[name] = list(unique.values())
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
