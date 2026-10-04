"""Drugs@FDA data through its openFDA API, and published complete response letters.

FDA action/letter dates are not company announcement timestamps. Records remain
candidates until sponsor economics, listing, event timing and tags are checked.
"""
from datetime import date, datetime
import re
from urllib.parse import urlencode
from .http import CollectionError

ENDPOINTS = {'drugs_at_fda': 'https://api.fda.gov/drug/drugsfda.json',
             'openfda_crl': 'https://api.fda.gov/transparency/crl.json'}


def day(value):
    for fmt in ('%Y%m%d', '%m/%d/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise CollectionError('Unrecognised FDA date. ' + str(value))


def approvals(record, origin, index):
    application = record['application_number']
    if not re.fullmatch(r'(NDA|BLA)\d+', application):
        return []  # ANDAs are outside the fixed rules.
    result = []
    for n, sub in enumerate(record['submissions']):
        if sub.get('submission_type') != 'ORIG' or sub.get('submission_status') != 'AP':
            continue
        when = day(sub['submission_status_date'])
        result.append(dict(candidate_id=f"fda:{application}:{sub['submission_number']}:{when}",
                           company=record['sponsor_name'], application=application, event_type='approval',
                           action_date=when, announced_at=None, announcement_time_unknown=True,
                           drugs=sorted({p['brand_name'] for p in record.get('products', []) if p.get('brand_name')}),
                           review_priority=sub.get('review_priority'), original=True,
                           source=origin['source'], url=origin['url'],
                           locator=f'/results/{index}/submissions/{n}', downloaded_at=origin['downloaded_at'],
                           status='pending', gaps=['Company announcement time, historical listing, first product and economics need verification.']))
    return result


def letters(record, origin, index):
    text = record['text']
    # Exclude explicit supplements. Application identity is not inferred from drug names.
    application = re.search(r'\b(NDA|BLA)\s*(\d{6})(?:\s*/\s*(S-?\d+))?', text, re.I)
    if not application:
        application = re.search(r'(NDA|BLA)(\d{6})', record.get('file_name', ''), re.I)
    if not application:
        raise CollectionError('CRL application number missing or unreadable.')
    supplement = (application.lastindex == 3 and application.group(3)) or re.search(
        r'\bsupplemental (?:new drug|biologics)|\bsupplement to (?:your|the) application|\bsNDA\b|\bsBLA\b', text[:2500], re.I)
    if supplement:
        return []
    app = application.group(1).upper() + application.group(2)
    when = day(record['letter_date'])
    return [dict(candidate_id=f'crl:{app}:{when}', company=record['company_name'], application=app,
                 event_type='crl', action_date=when, announced_at=None, announcement_time_unknown=True,
                 original=None, text=text, file_name=record.get('file_name'), status='pending',
                 source=origin['source'], url=origin['url'], locator=f'/results/{index}',
                 downloaded_at=origin['downloaded_at'],
                 gaps=['Original application status and company announcement date need verification.'])]


def collect(client, source, *, since='2015-01-01', until=None, page_size=10, max_pages=1, search=None):
    if source not in ENDPOINTS:
        raise CollectionError('Unknown FDA source.')
    until = until or date.today().isoformat()
    if date.fromisoformat(since) > date.fromisoformat(until):
        raise CollectionError('Start date must not follow end date.')
    if not 1 <= page_size <= 1000 or max_pages < 1:
        raise CollectionError('Invalid FDA page bounds.')
    parser = approvals if source == 'drugs_at_fda' else letters
    output = dict(source=source, candidates=[], gaps=[], responses=[], excluded=0, complete=False)
    seen = set()
    for page in range(max_pages):
        skip = page * page_size
        if skip > 25000:
            output['gaps'].append('openFDA skip limit reached. Partition the search before continuing.')
            break
        query = dict(limit=page_size, skip=skip)
        if search:
            query['search'] = search
        url = ENDPOINTS[source] + '?' + urlencode(query)
        try:
            data, origin = client.json(url)
            output['responses'].append(origin)
            if data.get('error', {}).get('code') == 'NOT_FOUND':
                output['complete'] = True
                break
            records, total = data['results'], data['meta']['results']['total']
            if not isinstance(records, list) or not isinstance(total, int):
                raise CollectionError('Invalid openFDA result schema.')
            for i, row in enumerate(records):
                try:
                    candidates = parser(row, origin, i)
                    if not candidates:
                        output['excluded'] += 1
                    for candidate in candidates:
                        if not since <= candidate['action_date'] <= until:
                            output['excluded'] += 1
                        elif candidate['candidate_id'] not in seen:
                            seen.add(candidate['candidate_id'])
                            output['candidates'].append(candidate)
                except (ValueError, KeyError, TypeError, AttributeError) as exc:
                    output['gaps'].append(f'{url} /results/{i}. {exc}')
            if skip + len(records) >= total:
                output['complete'] = True
                break
            if len(records) != page_size:
                raise CollectionError('Short FDA page before reported total.')
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            output['gaps'].append(f'{url}. {exc}')
            break
    if not output['complete']:
        output['gaps'].append('FDA collection incomplete at the configured page bound or a source failure.')
    output['complete'] = output['complete'] and not output['gaps']
    output['gap_count'] = len(output['gaps'])
    output['candidate_count'] = len(output['candidates'])
    output['scope'] = dict(since=since, until=until, search=search, page_size=page_size, max_pages=max_pages)
    return output
