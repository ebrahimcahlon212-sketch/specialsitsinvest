"""Live phase-one acceptance, never an offline fixture certification."""
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from .engine import report, render
from .publication import check
from .quality import primary_path, require


def evaluate(db, knowledge, targets):
    result = report(db, 'savara', knowledge)
    check(db, result)
    expected = json.loads(primary_path(targets).read_text())
    require({r['ticker'] for r in expected} == {'VRNA', 'KALV', 'CRNX', 'LQDA'} and len(expected) == 4,
            'Acceptance needs exactly Verona, KalVista, Crinetics and Liquidia targets.')
    require(not result.get('pending_candidates'), 'Census still has unreviewed candidates.')
    for name in ('drugs_at_fda', 'openfda_crl', 'edgar', 'ibkr'):
        partitions = result['coverage'].get(name, [])
        require(isinstance(partitions, list) and partitions and all(p['complete'] for p in partitions),
                'Incomplete collection partitions. ' + name)
    require(result.get('candidate_count', 0) > 0, 'Census has no collected candidates.')
    from datetime import date, timedelta
    for name in ('drugs_at_fda', 'openfda_crl'):
        end = date(2014, 12, 31)
        for part in sorted(result['coverage'][name], key=lambda p: p['scope']['since']):
            scope = part['scope']
            require(not scope.get('search'), 'Acceptance census cannot be narrowed by an extra FDA search.')
            start, stop = date.fromisoformat(scope['since']), date.fromisoformat(scope['until'])
            require(start <= end + timedelta(days=1), 'Gap between FDA census partitions.')
            end = max(end, stop)
        require(end >= date.fromisoformat(result['as_of']), 'FDA census does not reach the build date.')
    cents = lambda n: Decimal(str(n)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    for target in expected:
        rows = [r for r in result['events'] if r['event']['ticker'] == target['ticker']
                and r['event']['action_date'] == target['action_date']]
        require(len(rows) == 1, 'Comparable missing or ambiguous. ' + target['ticker'])
        reaction = rows[0]['reaction']
        require(reaction['status'] == 'priced', 'Comparable is unpriced. ' + target['ticker'])
        for field in ('pre', 'day1', 'day2'):
            require(reaction[field + '_date'] == target[field + '_date'], 'Comparable session differs.')
            require(cents(reaction[field + '_close']) == cents(target[field + '_close']),
                    'Comparable differs to the cent. ' + target['ticker'] + ' ' + field)
    return render(result) + f'Four comparables matched to the cent. Targets [{Path(targets).resolve()}].\n'
