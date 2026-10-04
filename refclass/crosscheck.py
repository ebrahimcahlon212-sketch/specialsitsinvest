"""Independent broker observations, never substitutes for census prices."""
from datetime import date
from decimal import Decimal
import json
from .quality import require


def verify_check(row, cache=None):
    from .publication import primary_line
    source, marker, line = row['source'].rpartition('#L')
    require(marker and line.isdigit(), 'IBKR check needs a primary line.')
    raw = json.loads(primary_line(source, int(line), cache))
    require(raw.get('provider') == 'IBKR', 'Independent check needs IBKR evidence.')
    for field in ('ticker', 'date', 'close'):
        require(raw[field] == row[field], 'IBKR check source mismatch.')
    if 'broker_response' in raw:
        from .bars import transcript_bars
        # Reparse the original transcript, including contract resolution.
        key = ('transcript', raw['transcript'])
        if cache is None:
            cache = {}
        if key not in cache:
            cache[key] = transcript_bars(raw['transcript'], raw['broker_tool'].split('__')[1])
        records = cache[key]
        require(raw in records, 'IBKR observation differs from original tool transcript.')
    return raw


def compare_bars(events, prices, sessions, checks, as_of):
    from .engine import session_dates
    from .collectors.massive import years_before
    earliest = years_before(date.fromisoformat(as_of), 5).isoformat()
    census = {(p['ticker'], p['date']): p for p in prices}
    broker = {(p['ticker'], p['date']): p for p in checks}
    results = []
    for event in sorted(events, key=lambda e: e['event_id']):
        if (event.get('event_review', {}).get('decision') == 'exclude' or
                not earliest <= event.get('action_date', '') <= as_of):
            continue
        try:
            dates = session_dates(event['announced_at'], sessions)[:3]
        except (ValueError, KeyError):
            results.append(dict(event_id=event['event_id'], status='missing', reason='Event sessions unavailable'))
            continue
        for ticker in (event.get('ticker'), 'XBI'):
            for day in dates:
                a, b = census.get((ticker, day)), broker.get((ticker, day))
                record = dict(event_id=event['event_id'], ticker=ticker, date=day)
                if a is None or b is None:
                    record.update(status='missing', reason='Massive or IBKR close unavailable')
                else:
                    difference = abs(Decimal(str(a['close'])) - Decimal(str(b['close'])))
                    record.update(status='review' if difference > Decimal('.01') else 'matched',
                        difference=str(difference), massive_close=a['close'], ibkr_close=b['close'],
                        massive_source=a['source'], ibkr_source=b['source'])
                results.append(record)
    return results
