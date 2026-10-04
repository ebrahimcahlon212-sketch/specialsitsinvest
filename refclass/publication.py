"""Strict checks over the actual reference-class output, not a model's metric list."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .engine import reaction, market_value, summarize, exclusion
from .provenance import eligibility_gap, shares_verified
from .quality import require, source_excerpt, decision_date, acceptance_time, primary_path


def primary_line(source, line, cache=None):
    if cache is None:
        return source_excerpt(dict(source=source, line_start=line, line_end=line))
    path = primary_path(source)
    if path not in cache:
        cache[path] = path.read_text().splitlines()
    require(1 <= line <= len(cache[path]), 'Invalid bar line locator.')
    return cache[path][line - 1]


def price_evidence(row, cache=None):
    """Match each used bar to an exact saved primary JSON line.

    A label containing 'IBKR' is insufficient. Source must be a primary file
    under deals/*/filings or work, with a line containing the original bar.
    This verifies stored inputs, not the authenticity of a broker connection.
    """
    source, marker, line = row['source'].rpartition('#L')
    require(bool(marker) and line.isdigit(), 'Price gate needs a saved IBKR bar and #L locator.')
    text = primary_line(source, int(line), cache)
    bar = json.loads(text)
    require(bar.get('provider') in ('IBKR', 'Massive'), 'Price gate needs a primary price response.')
    for key in ('ticker', 'date', 'close', 'adjusted_close'):
        require(bar.get(key) == row[key], 'Price gate source mismatch. ' + key)
    require(bar.get('adjustment') == 'split_only', 'Price gate needs explicit split-only adjustment.')
    if bar.get('provider') == 'Massive':
        from .collectors.massive import verify
        verify(bar)
    if 'broker_response' in bar:
        payload = bar['broker_response']
        native = payload['bars'][bar['broker_index']]
        for key in ('ticker', 'date', 'close', 'adjusted_close', 'adjustment'):
            require(native.get(key, payload.get(key)) == bar[key], 'Broker payload mismatch. ' + key)
        # The original transport line remains independently readable primary evidence.
        origin = primary_line(bar['transcript'], bar['transcript_line'], cache)
        blocks = json.loads(origin).get('message', {}).get('content', [])
        matched = False
        for block in blocks:
            if block.get('type') == 'tool_result' and block.get('tool_use_id') == bar['tool_use_id']:
                content = block.get('content')
                if isinstance(content, list):
                    content = ''.join(c.get('text', '') for c in content if c.get('type') == 'text')
                matched = (json.loads(content) if isinstance(content, str) else content) == payload
        require(matched, 'Bar is not supported by the original broker tool result.')
    return bar


def check(db, result):
    require(not result['fixture'], 'Strict publication refuses synthetic fixture results.')
    require(not result.get('profile_gap'), 'Strict publication requires a sourced deal profile.')
    with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        prices = [dict(r) for r in conn.execute('SELECT * FROM prices')]
        sessions = [dict(r) for r in conn.execute('SELECT * FROM sessions')]
    cache = {}
    for price in prices:
        require(price_evidence(price, cache).get('provider') == 'Massive',
                'Census prices require Massive daily aggregates.')
    for row in result.get('exclusions', []):
        event = row['event']
        current = ('Excluded by independent reviews' if event.get('event_review', {}).get('decision') == 'exclude' else None) or exclusion(event, result['as_of']) or eligibility_gap(event)
        require(current == row['reason'], 'Excluded event provenance changed. ' + event['event_id'])
        # Exclusions need primary evidence and independent review too.
        from .review import verify_event_review
        verify_event_review(event)
    from .crosscheck import verify_check, compare_bars
    for bar in result.get('ibkr_checks', []):
        verify_check(bar, cache)
    all_events = [r['event'] for r in result['events']] + [r['event'] for r in result.get('exclusions', [])]
    require(result.get('ibkr_comparisons', []) == compare_bars(
        all_events, prices, sessions, result.get('ibkr_checks', []), result['as_of']),
        'Independent IBKR comparisons differ from recomputation.')
    rows = []
    for row in result['events']:
        event = row['event']
        from .review import verify_event_review
        verify_event_review(event)
        require(event['event_review']['decision'] == 'include', 'Excluded review entered an eligible class.')
        require(eligibility_gap(event) is None, 'Event provenance changed. ' + event['event_id'])
        require(shares_verified(event), 'Event share evidence failed. ' + event['event_id'])
        # Source inventory completeness remains explicit, never inferred from
        # the supplied share_filings array.
        require(bool(event.get('inventory_sources')), 'Strict publication needs saved SEC submissions inventory.')
        from .inventory import verify
        verify(event)
        if event['event_type'] in ('approval', 'crl'):
            decision_date('fda_action', event['action_date'], event['action_evidence'])
        else:
            raise ValueError('Strict publication date checks for this event type are not implemented.')
        acceptance_time(event['announced_at'], event['announcement_evidence'])
        for tag in event.get('tags', []):
            source_excerpt(tag)
        recomputed = reaction(event, prices, sessions)
        require(row['reaction'] == recomputed, 'Stored reaction differs from recomputation.')
        cap = market_value(event, prices, sessions)
        require(row['market_value'] == cap, 'Stored market value differs from recomputation.')
        rows.append((event, recomputed, cap))
    first = [r for r in rows if r[0].get('first_product') is True]
    core = [r for r in first if r[2] is not None and r[2] < 3_000_000_000]
    for published, subset in zip(result['classes'], (rows, first, core)):
        require(published['count'] == len(subset), 'Class count mismatch.')
        require(published['without_same_day_news'] == summarize([r for r in subset if r[0].get('same_day_news') is False]),
                'Unconfounded class summary mismatch.')
        for key, value in summarize(subset).items():
            require(published[key] == value, 'Class summary mismatch. ' + key)
    return result
