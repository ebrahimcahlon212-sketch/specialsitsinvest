"""Ingest saved historical JSON lines from the kit's read-only IBKR price workflow.

The existing quote reader is reused. Historical close, split-only adjustment and
session dates must be supplied explicitly; a current quote is never a daily bar.
The MCP connection and historical response mapping need live-build verification.
"""
from datetime import date
import json
from pathlib import Path

from lib.quotes import read_quotes
from ..math import positive
from ..publication import price_evidence


def collect(path, *, tickers, since, until):
    path = Path(path).resolve()
    start, end = date.fromisoformat(since), date.fromisoformat(until)
    if start > end:
        raise ValueError('Start date must not follow end date.')
    wanted = set(tickers) | {'XBI'}
    result = dict(source='ibkr', prices=[], gaps=[], complete=False,
                  scope=dict(since=since, until=until, tickers=sorted(wanted)))
    parsed = {json.dumps(row, sort_keys=True) for row in read_quotes(path)}
    seen = set()
    cache = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            if json.dumps(raw, sort_keys=True) not in parsed:
                raise ValueError('Not a quote object recognised by the kit price reader.')
            if raw.get('error'):
                raise ValueError(raw['error'])
            if raw['ticker'] not in wanted:
                continue
            day = date.fromisoformat(raw['date'])
            if not start <= day <= end:
                continue
            row = dict(ticker=raw['ticker'], date=day.isoformat(), close=positive(raw['close']),
                       adjusted_close=positive(raw['adjusted_close']), source=f'{path}#L{number}')
            price_evidence(row, cache)
            key = (row['ticker'], row['date'])
            if key in seen:
                raise ValueError('Duplicate daily bar.')
            seen.add(key)
            result['prices'].append(row)
        except (ValueError, KeyError, TypeError) as exc:
            result['gaps'].append(f'{path} L.{number}. {exc}')
    missing = wanted - {r['ticker'] for r in result['prices']}
    result['gaps'].extend(f'{ticker}. No historical bars supplied.' for ticker in sorted(missing))
    result['complete'] = not result['gaps']
    result['gap_count'] = len(result['gaps'])
    result['coverage_gaps'] = ['Saved-bar ingestion does not establish full session coverage; event windows check missing bars.']
    result['gap_count'] += len(result['coverage_gaps'])
    return result
