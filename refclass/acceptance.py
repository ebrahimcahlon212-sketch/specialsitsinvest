"""Live phase-one acceptance, never an offline fixture certification."""
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from .engine import report, render
from .publication import check
from .quality import primary_path, require


def compare(reaction, target):
    """Report closes are contemporaneous; returns use the fixed split convention."""
    cents = lambda n: Decimal(str(n)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    require(target.get('close_convention') == 'as_traded',
            'Comparable targets must identify closes as as_traded.')
    require(target.get('return_convention') == 'split_only',
            'Comparable targets must identify returns as split_only fractions.')
    for field in ('pre', 'day1', 'day2'):
        require(reaction[field + '_date'] == target[field + '_date'], 'Comparable session differs.')
        require(cents(reaction[field + '_unadjusted_close']) == cents(target[field + '_close']),
                'Comparable differs to the cent. ' + target['ticker'] + ' ' + field)
    from .quality import arithmetic
    for field in ('day1_raw', 'day2_raw'):
        require(field in target, 'Comparable target needs both report returns.')
        arithmetic(target[field], reaction[field], tolerance=.00005 + 1e-12)


def evaluate(db, knowledge, targets):
    result = report(db, 'savara', knowledge)
    check(db, result)
    expected = json.loads(primary_path(targets).read_text())
    require({r['ticker'] for r in expected} == {'VRNA', 'KALV', 'CRNX', 'LQDA'} and len(expected) == 4,
            'Acceptance needs exactly Verona, KalVista, Crinetics and Liquidia targets.')
    require(not result.get('pending_candidates'), 'Census still has unreviewed candidates.')
    for name in ('drugs_at_fda', 'openfda_crl', 'edgar', 'massive'):
        partitions = result['coverage'].get(name, [])
        require(isinstance(partitions, list) and partitions and
                (name == 'massive' or all(p['complete'] for p in partitions)),
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
    for target in expected:
        rows = [r for r in result['events'] if r['event']['ticker'] == target['ticker']
                and r['event']['action_date'] == target['action_date']]
        require(len(rows) == 1, 'Comparable missing or ambiguous. ' + target['ticker'])
        reaction = rows[0]['reaction']
        require(reaction['status'] == 'priced', 'Comparable is unpriced. ' + target['ticker'])
        for origin in reaction['price_sources']:
            from .publication import primary_line
            source, _, line = origin['source'].rpartition('#L')
            require(json.loads(primary_line(source, int(line))).get('provider') == 'Massive',
                    'Acceptance comparables require Massive bars.')
        compare(reaction, target)
    return render(result) + f'Four comparables matched as-traded closes to the cent and both split-adjusted returns to half a basis point. Targets [{Path(targets).resolve()}].\n'
