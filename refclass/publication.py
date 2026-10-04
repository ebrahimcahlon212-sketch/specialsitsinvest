"""Strict checks over the actual reference-class output, not a model's metric list."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .engine import reaction, market_value, summarize
from .provenance import eligibility_gap, shares_verified
from .quality import require, source_excerpt, decision_date


def price_evidence(row):
    """Match each used bar to an exact saved primary JSON line.

    A label containing 'IBKR' is insufficient. Source must be a primary file
    under deals/*/filings or work, with a line containing the original bar.
    This verifies stored inputs, not the authenticity of a broker connection.
    """
    source, marker, line = row['source'].rpartition('#L')
    require(bool(marker) and line.isdigit(), 'Price gate needs a saved IBKR bar and #L locator.')
    text = source_excerpt(dict(source=source, line_start=int(line), line_end=int(line)))
    bar = json.loads(text)
    require(bar.get('provider') == 'IBKR', 'Price gate needs an IBKR response.')
    for key in ('ticker', 'date', 'close', 'adjusted_close'):
        require(bar.get(key) == row[key], 'Price gate source mismatch. ' + key)
    require(bar.get('adjustment') == 'split_only', 'Price gate needs explicit split-only adjustment.')
    return bar


def check(db, result):
    require(not result['fixture'], 'Strict publication refuses synthetic fixture results.')
    require(not result.get('profile_gap'), 'Strict publication requires a sourced deal profile.')
    with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        prices = [dict(r) for r in conn.execute('SELECT * FROM prices')]
        sessions = [dict(r) for r in conn.execute('SELECT * FROM sessions')]
    for price in prices:
        price_evidence(price)
    rows = []
    for row in result['events']:
        event = row['event']
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
        announcement = source_excerpt(event['announcement_evidence'])
        require(event['announced_at'] in announcement, 'Announcement timestamp needs exact source support.')
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
