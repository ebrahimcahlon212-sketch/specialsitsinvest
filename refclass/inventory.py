"""Reconcile saved SEC inventory files before strict event publication."""
from datetime import date
import json
from pathlib import Path
from .quality import require, source_excerpt
from .collectors.edgar import inventory


def verify(event, filing_available=None):
    documents = {}
    for evidence in event['inventory_sources']:
        # Enforce the same deal/primary-file boundary before reading JSON.
        source_excerpt(dict(evidence, line_start=1, line_end=1))
        path = Path(evidence['source'])
        require(path.is_absolute(), 'Inventory sources must use absolute primary-file paths.')
        documents[path.name] = json.loads(path.read_text())
    roots = [d for d in documents.values() if 'filings' in d]
    require(len(roots) == 1, 'Need one SEC company submissions inventory.')
    root = roots[0]
    require(event['ticker'] in root.get('tickers', []), 'Inventory ticker mismatch needs review.')
    rows = inventory(root['filings']['recent'])
    for history in root['filings'].get('files', []):
        require(history['name'] in documents, 'Missing SEC historical inventory. ' + history['name'])
        rows.extend(inventory(documents[history['name']]))
    for row in rows:
        date.fromisoformat(row['filingDate'])
    when = event['announced_at'][:10]
    prior = [r for r in rows if r['form'] in ('10-Q', '10-K', '10-Q/A', '10-K/A')
             and (filing_available(r) if filing_available else r['filingDate'] < when)]
    require(bool(prior), 'No pre-event share filing in the SEC inventory; cannot establish the latest SEC periodic filing.')
    latest = max(prior, key=lambda r: r['filingDate'])
    require(any(f.get('accessionNumber') == latest['accessionNumber']
                and f.get('filed_at') == latest['filingDate']
                and f.get('source') == event['shares_source']
                for f in event['share_filings']),
            'Share evidence omits the latest SEC periodic filing.')
    for row in rows:
        require(not (event['shares_as_of'] <= row['filingDate'] <= when and '1.03' in str(row.get('items', ''))),
                'Listing gate failed. SEC inventory contains Item 1.03.')
    return latest
