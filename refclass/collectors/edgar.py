"""Collect dated 8-K inventories, primary documents and EX-99 announcements.

Keyword matches are research leads, never verified event types or action dates.
The SEC acceptance timestamp is retained separately from company announcement time.
"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import html
import re
from lib.prep import html_text
from .http import CollectionError

SIGNALS = {
    'goal_date': r'PDUFA|target action date|goal date',
    'submission': r'\b(?:submitted|submission)\b',
    'crl': r'complete response letter|\bCRL\b',
    'extension': r'extend(?:ed|s|ing)?|extension',
    'refusal_to_file': r'refus(?:al|ed) to (?:file|accept)',
    'resubmission_accepted': r'resubmission|resubmitted',
    'offering': r'(?:public|registered direct|equity) offering|private placement|at.the.market',
    'approval': r'FDA.{0,80}approv|approv.{0,80}FDA',
}


def acceptance_datetime(value):
    """Convert UTC SEC acceptance times to Eastern, preserving explicit offsets."""
    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(ZoneInfo('America/New_York'))


def cik_number(cik):
    text = str(cik)
    if not re.fullmatch(r'\d{1,10}', text) or int(text) == 0:
        raise CollectionError('CIK must contain one to ten digits and be positive.')
    return f'{int(text):010d}'


def inventory(data):
    """Validate column lengths before zipping to avoid silent row loss."""
    required = ('accessionNumber', 'filingDate', 'form', 'primaryDocument')
    if any(not isinstance(data.get(k), list) for k in required):
        raise CollectionError('Missing SEC submissions columns.')
    count = len(data['accessionNumber'])
    if any(len(data[k]) != count for k in required):
        raise CollectionError('SEC submissions columns have different lengths.')
    for key in ('acceptanceDateTime', 'items', 'reportDate'):
        if key in data and (not isinstance(data[key], list) or len(data[key]) != count):
            raise CollectionError('SEC optional column has a different length. ' + key)
    return [{key: values[i] for key, values in data.items() if isinstance(values, list) and len(values) == count}
            for i in range(count)]


def filing_base(cik, accession):
    if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession):
        raise CollectionError('Invalid accession number.')
    return f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/'


def documents(raw, base):
    if b'Document Format Files' not in raw:
        raise CollectionError('SEC document index table is missing.')
    result = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', raw.decode('utf-8', 'replace'), re.S | re.I):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S | re.I)
        link = re.search(r'(/Archives/edgar/data/[^\"\'?#<>\s]+)', row)
        if len(cells) < 4 or not link:
            continue
        kind = html.unescape(re.sub(r'<[^>]+>', '', cells[3])).strip().upper()
        url = 'https://www.sec.gov' + link.group(1)
        if url.startswith(base) and re.search(r'\.(?:htm|html|txt)$', url, re.I) and re.fullmatch(r'EX-99(?:\..+)?', kind):
            result.append(dict(url=url, form=kind))
    return result


def read_document(raw, origin, form):
    text = html_text(raw.decode('utf-8', 'replace'))
    lines = text.splitlines()
    signals = []
    for number, line in enumerate(lines, 1):
        matches = [kind for kind, pattern in SIGNALS.items() if re.search(pattern, line, re.I)]
        if matches:
            signals.append(dict(kinds=matches, line=number, text=line))
    return dict(form=form, source=origin['source'], url=origin['url'],
                downloaded_at=origin['downloaded_at'], sha256=origin['sha256'],
                text=text, signals=signals, locator_convention='1-based lines of text, extracted with lib.prep.html_text')


def collect(client, cik, *, since='2015-01-01', until=None, max_filings=1, max_history=1, max_exhibits=2):
    cik = cik_number(cik)
    until = until or date.today().isoformat()
    if date.fromisoformat(since) > date.fromisoformat(until) or min(max_filings, max_history, max_exhibits) < 0:
        raise CollectionError('Invalid EDGAR date range or collection bounds.')
    result = dict(source='edgar', cik=cik, filings=[], gaps=[], responses=[], complete=False,
                  scope=dict(since=since, until=until, max_filings=max_filings,
                             max_history=max_history, max_exhibits=max_exhibits))
    url = f'https://data.sec.gov/submissions/CIK{cik}.json'
    try:
        data, origin = client.json(url)
        result['responses'].append(origin)
        result.update(company=data['name'], current_tickers=data.get('tickers', []),
                      current_exchanges=data.get('exchanges', []))
        rows = inventory(data['filings']['recent'])
        for i, row in enumerate(rows):
            row['announcement_evidence'] = dict(source=origin['source'], pointer='/filings/recent', index=i)
        history = [f for f in data['filings'].get('files', [])
                   if f['filingTo'] >= since and f['filingFrom'] <= until]
        if len(history) > max_history:
            result['gaps'].append(f'Historical submissions bound leaves {len(history) - max_history} files unread.')
        for file in history[:max_history]:
            name = file['name']
            if not re.fullmatch(r'CIK\d{10}-submissions-\d+\.json', name):
                raise CollectionError('Invalid historical submissions filename.')
            try:
                old, source = client.json('https://data.sec.gov/submissions/' + name)
                result['responses'].append(source)
                historical = inventory(old)
                for i, row in enumerate(historical):
                    # Historical inventories are top-level column arrays.
                    row['announcement_evidence'] = dict(source=source['source'], pointer='', index=i)
                rows.extend(historical)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                result['gaps'].append(f'{name}. {exc}')
        chosen = {}
        for row in rows:
            try:
                date.fromisoformat(row['filingDate'])
            except (ValueError, TypeError) as exc:
                result['gaps'].append(f"Invalid filingDate for {row.get('accessionNumber')}. {exc}")
                continue
            if row['form'] in ('8-K', '8-K/A') and since <= row['filingDate'] <= until:
                chosen.setdefault(row['accessionNumber'], row)
        result['inventory_count'] = len(chosen)
        if len(chosen) > max_filings:
            result['gaps'].append(f'Filing bound leaves {len(chosen) - max_filings} matching 8-Ks unread.')
        for row in sorted(chosen.values(), key=lambda r: (r['filingDate'], r['accessionNumber']), reverse=True)[:max_filings]:
            accepted = row.get('acceptanceDateTime')
            entry = dict(row, documents=[], status='pending',
                         announced_at=acceptance_datetime(accepted).isoformat() if accepted else None,
                         note='Timing uses structured 8-K acceptance; earlier press releases need contradiction review.')
            result['filings'].append(entry)
            try:
                base = filing_base(cik, row['accessionNumber'])
                primary = row['primaryDocument']
                if not re.fullmatch(r'[A-Za-z0-9_.-]+\.(?:htm|html|txt)', primary, re.I):
                    raise CollectionError('Invalid primary document name.')
                raw, source = client.get(base + primary)
                result['responses'].append(source)
                entry['documents'].append(read_document(raw, source, row['form']))
                raw, source = client.get(base + row['accessionNumber'] + '-index.htm')
                result['responses'].append(source)
                exhibits = documents(raw, base)
                if len(exhibits) > max_exhibits:
                    result['gaps'].append(f'{row["accessionNumber"]}. Exhibit bound leaves documents unread.')
                for exhibit in exhibits[:max_exhibits]:
                    try:
                        raw, source = client.get(exhibit['url'])
                        result['responses'].append(source)
                        entry['documents'].append(read_document(raw, source, exhibit['form']))
                    except (ValueError, KeyError, TypeError, AttributeError) as exc:
                        result['gaps'].append(f'{exhibit["url"]}. {exc}')
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                result['gaps'].append(f'{row["accessionNumber"]}. {exc}')
        result['complete'] = not result['gaps']
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        result['gaps'].append(f'{url}. {exc}')
    result['gap_count'] = len(result['gaps'])
    result['filing_count'] = len(result['filings'])
    return result
