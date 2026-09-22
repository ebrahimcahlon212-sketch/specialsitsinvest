"""Manual SEC filing imports, their document lists and bounded downloads."""

import json
import logging
import re
import time
import uuid
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from app import constants, db, documents, worker

logger = logging.getLogger(__name__)
_rate_lock = Lock()
_start_lock = Lock()
_last_request = 0.0


def _now():
    return datetime.now(timezone.utc).isoformat()


def contact(data_dir: Path) -> dict:
    with closing(db.connect(data_dir)) as connection:
        values = dict(connection.execute(
            "SELECT key, value FROM settings WHERE key IN ('sec_name', 'sec_email')"))
    return {'name': values.get('sec_name', constants.SEC_CONTACT_NAME),
            'email': values.get('sec_email', constants.SEC_CONTACT_EMAIL)}


def save_contact(data_dir: Path, name: str, email: str) -> dict:
    name, email = name.strip(), email.strip()
    _user_agent(name, email)
    with db.DATA_LOCK, closing(db.connect(data_dir)) as connection, connection:
        connection.executemany(
            'INSERT INTO settings(key,value) VALUES (?,?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            [('sec_name', name), ('sec_email', email)])
    return {'name': name, 'email': email}


def _user_agent(name: str, email: str) -> str:
    if (not name or len(name) > 200 or len(email) > 254 or
            not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or
            any(ord(character) < 32 or ord(character) > 126 for character in name + email)):
        raise ValueError('Enter your name and contact email in Settings using plain characters for the SEC header.')
    return f'InvestResearch {name} {email}'


def resolve_url(url: str) -> dict:
    value = urlsplit(url.strip())
    if (value.scheme != 'https' or value.hostname != 'www.sec.gov' or
            value.netloc != 'www.sec.gov' or value.query or value.fragment):
        raise ValueError('Paste an HTTPS www.sec.gov/Archives filing or exhibit URL without a query or fragment.')
    match = re.fullmatch(r'/Archives/edgar/data/(\d{1,10})/(\d{18})/([A-Za-z0-9_.-]*)', value.path)
    if match:
        cik, digits, filename = match.groups()
        accession = f'{digits[:10]}-{digits[10:12]}-{digits[12:]}'
    else:
        match = re.fullmatch(r'/Archives/edgar/data/(\d{1,10})/(\d{10}-\d{2}-\d{6})-index\.html', value.path)
        if not match:
            raise ValueError('This is not a supported SEC filing-directory, filing-index or document URL.')
        cik, accession = match.groups()
        digits, filename = accession.replace('-', ''), accession + '-index.html'
    if filename in {'.', '..'} or int(cik) == 0:
        raise ValueError('The SEC filing URL is invalid.')
    cik = str(int(cik))
    base = f'https://www.sec.gov/Archives/edgar/data/{cik}/{digits}/'
    return {'url': base + filename, 'base_url': base,
            'filing_url': base + accession + '-index.html',
            'accession_number': accession, 'cik': cik}


def fetch(url: str, user_agent: str) -> bytes:
    """All SEC requests share this limiter, including retries and redirects."""
    global _last_request
    expected = resolve_url(url)['base_url']
    last_error = None
    for attempt in range(constants.SEC_ATTEMPTS):
        current = url
        try:
            for redirect in range(4):
                if resolve_url(current)['base_url'] != expected:
                    raise ValueError('SEC redirected outside the requested filing; no redirected content was fetched.')
                with _rate_lock:
                    delay = constants.SEC_REQUEST_INTERVAL - (time.monotonic() - _last_request)
                    if delay > 0:
                        time.sleep(delay)
                    _last_request = time.monotonic()
                    response = requests.get(current, headers={'User-Agent': user_agent,
                        'Accept-Encoding': 'gzip, deflate'}, timeout=constants.SEC_TIMEOUT,
                        stream=True, allow_redirects=False)
                with response:
                    if response.is_redirect:
                        current = urljoin(current, response.headers.get('Location', ''))
                        if redirect == 3:
                            raise ValueError('SEC returned too many redirects.')
                        continue
                    if response.status_code == 403:
                        raise ValueError('SEC denied access (HTTP 403). No bypass was attempted. Check your contact details or try later.')
                    if response.status_code == 429 or response.status_code >= 500:
                        last_error = f'SEC returned HTTP {response.status_code}; bounded retries were exhausted.'
                        break
                    if response.status_code != 200:
                        raise ValueError(f'SEC download failed: HTTP {response.status_code}.')
                    length = response.headers.get('Content-Length')
                    if length and length.isdigit() and int(length) > constants.MAX_DOCUMENT_BYTES:
                        raise ValueError('SEC document exceeds the 10 MiB download limit.')
                    content = bytearray()
                    for chunk in response.iter_content(65536):
                        content.extend(chunk)
                        if len(content) > constants.MAX_DOCUMENT_BYTES:
                            raise ValueError('SEC document exceeds the 10 MiB download limit.')
                    prefix = bytes(content[:3000]).lower()
                    if any(message in prefix for message in (
                            b'your request originates from an undeclared automated tool',
                            b'request rate threshold exceeded', b'access denied')):
                        raise ValueError('SEC returned an access restriction page, not a filing. No content was imported.')
                    return bytes(content)
        except requests.RequestException as error:
            last_error = f'SEC network request failed: {type(error).__name__}.'
        if attempt + 1 < constants.SEC_ATTEMPTS:
            time.sleep(2 ** (attempt + 1))
    raise ValueError(last_error or 'SEC download failed without a usable response.')


def parse_index(content: bytes, info: dict) -> dict:
    soup = BeautifulSoup(content, 'lxml')
    if not soup.title or info['accession_number'] not in soup.title.get_text():
        raise ValueError('The returned page does not identify the requested SEC accession.')
    cik_values = []
    for link in soup.select('.companyInfo a[href]'):
        value = parse_qs(urlsplit(link['href']).query).get('CIK', [])
        cik_values.extend(str(int(item)) for item in value if item.isdigit())
    if info['cik'] not in cik_values:
        raise ValueError('The filing index does not confirm the company CIK in this URL.')
    filing_date = None
    for heading in soup.select('.infoHead'):
        if heading.get_text(strip=True) == 'Filing Date':
            sibling = heading.find_next_sibling(class_='info')
            if sibling:
                filing_date = date.fromisoformat(sibling.get_text(strip=True)).isoformat()
    form = soup.select_one('#formName')
    form_match = re.search(r'Form\s+(\S+)', form.get_text(' ', strip=True)) if form else None
    form_type = form_match.group(1) if form_match else None
    items, seen = [], set()
    table = soup.find('table', attrs={'summary': 'Document Format Files'})
    if table is None:
        raise ValueError('The SEC filing document list could not be read.')
    for row in table.find_all('tr'):
        cells = row.find_all('td', recursive=False)
        if len(cells) != 5 or not cells[0].get_text(strip=True).isdigit():
            continue  # The full-submission archive is not an individual document.
        link = cells[2].find('a', href=True)
        if link is None:
            raise ValueError('A filing document has no usable source link.')
        source = resolve_url(urljoin(info['filing_url'], link['href']))
        if source['base_url'] != info['base_url']:
            raise ValueError('A filing document link points outside the verified accession.')
        if source['url'] in seen:
            continue
        seen.add(source['url'])
        size = cells[4].get_text(strip=True)
        items.append({'name': source['url'].rsplit('/', 1)[1], 'url': source['url'],
                      'document_type': cells[3].get_text(strip=True) or None,
                      'size': int(size) if size.isdigit() else None,
                      'status': 'not fetched', 'detail': 'Not yet downloaded.',
                      'document_id': None, 'logical_document_id': str(uuid.uuid4())})
    if not items or not filing_date or not form_type:
        raise ValueError('The filing index is missing its document list, filing date or form type.')
    if len(items) > 1000:
        raise ValueError('The filing document list exceeds the supported 1,000 entries.')
    return {'filing_date': filing_date, 'form_type': form_type, 'items': items}


def list_imports(data_dir: Path, case_id: int) -> list[dict]:
    with closing(db.connect(data_dir)) as connection:
        rows = connection.execute('SELECT * FROM sec_imports WHERE case_id=? ORDER BY id DESC',
                                  (case_id,)).fetchall()
    result = []
    for row in rows:
        record = dict(row)
        record['items'] = json.loads(record.pop('items_json'))
        result.append(record)
    return result


def _save(data_dir, record):
    with db.DATA_LOCK, closing(db.connect(data_dir)) as connection, connection:
        connection.execute(
            'UPDATE sec_imports SET filing_date=?,form_type=?,status=?,detail=?,checked_at=?, '
            'selected_document_url=?,items_json=? WHERE id=?',
            (record['filing_date'], record['form_type'], record['status'], record['detail'],
             _now(), record['selected_document_url'], json.dumps(record['items']), record['id']))


def prepare_import(data_dir: Path, case_id: int, url: str) -> int:
    info = resolve_url(url)
    _user_agent(**contact(data_dir))
    with db.DATA_LOCK, closing(db.connect(data_dir)) as connection, connection:
        if not connection.execute('SELECT 1 FROM cases WHERE id=?', (case_id,)).fetchone():
            raise ValueError('Case does not exist.')
        connection.execute(
            'INSERT INTO sec_imports(case_id,request_url,filing_url,accession_number,cik,status,detail,checked_at) '
            "VALUES (?,?,?,?,?,'queued','Waiting for the SEC import worker.',?) "
            'ON CONFLICT(case_id,filing_url) DO UPDATE SET request_url=excluded.request_url, '
            'status=excluded.status,detail=excluded.detail,checked_at=excluded.checked_at',
            (case_id, info['url'], info['filing_url'], info['accession_number'], info['cik'], _now()))
        return connection.execute('SELECT id FROM sec_imports WHERE case_id=? AND filing_url=?',
                                  (case_id, info['filing_url'])).fetchone()[0]


def _record(data_dir, import_id):
    with closing(db.connect(data_dir)) as connection:
        row = connection.execute('SELECT * FROM sec_imports WHERE id=?', (import_id,)).fetchone()
    if row is None:
        raise ValueError('The saved SEC import does not exist.')
    record = dict(row)
    record['items'] = json.loads(record.pop('items_json'))
    return record


def run_import(data_dir: Path, import_id: int, selected_url: str | None = None):
    record = _record(data_dir, import_id)
    try:
        ua = _user_agent(**contact(data_dir))
        record.update(status='running', detail='Reading the SEC filing document list.')
        _save(data_dir, record)
        info = resolve_url(record['request_url'])
        notice = ''
        if selected_url is None:
            try:
                directory = json.loads(fetch(info['base_url'] + 'index.json', ua))
                if not isinstance(directory.get('directory', {}).get('item'), list):
                    raise ValueError('Directory index contains no file list.')
            except (ValueError, TypeError) as error:
                notice = f'Directory index unavailable ({error}); used the filing index HTML. '
                logger.warning('SEC directory index unavailable for import %s: %s', import_id, error)
            parsed = parse_index(fetch(info['filing_url'], ua), info)
            previous = {item['url']: item for item in record['items']}
            for item in parsed['items']:
                if item['url'] in previous:
                    old = previous.pop(item['url'])
                    for key in ('logical_document_id', 'document_id', 'status', 'detail'):
                        item[key] = old[key]
            # Retain references if SEC later removes an item from the listing.
            for item in previous.values():
                item['detail'] = 'Not in the latest filing list; previous saved version retained.'
                parsed['items'].append(item)
            record.update(parsed)
            if not record['selected_document_url']:
                expected = next((item for item in record['items']
                                 if item['document_type'] == 'EX-99.1'), None)
                record['selected_document_url'] = expected['url'] if expected else None
        else:
            if not any(item['url'] == selected_url for item in record['items']):
                raise ValueError('Choose a document from this saved filing list.')
            record['selected_document_url'] = selected_url
        _save(data_dir, record)
        with closing(db.connect(data_dir)) as connection:
            researching = connection.execute('SELECT status FROM cases WHERE id=?',
                                              (record['case_id'],)).fetchone()[0] == 'research'
        main = next((item['url'] for item in record['items']
                     if item['document_type'] == record['form_type']), None)
        priority = [record['selected_document_url'], main, record['request_url']]
        ordered = sorted(record['items'], key=lambda item:
                         priority.index(item['url']) if item['url'] in priority else len(priority))
        total, count = 0, 0
        for item in ordered:
            suffix = Path(item['name']).suffix.lower()
            wanted = item['url'] in priority or (
                researching and (item['document_type'] or '').startswith('EX-'))
            if selected_url is not None:
                wanted = item['url'] == selected_url
            if not wanted:
                if item['document_id'] is None:
                    item['detail'] = ('Unsupported format; HTML/text only.' if suffix not in {'.htm', '.html', '.txt'}
                                      else 'Not requested; remaining exhibits download for cases in research.')
                continue
            record['detail'] = f"Checking {item['name']} ({count + 1} of at most {constants.SEC_MAX_DOCUMENTS} downloads)."
            _save(data_dir, record)
            try:
                if suffix not in {'.htm', '.html', '.txt'}:
                    item.update(status='not fetched', detail='Unsupported format; HTML/text only. No PDF or image text extraction.')
                    continue
                if item['document_id'] is not None:
                    with closing(db.connect(data_dir)) as connection:
                        saved = connection.execute('SELECT case_id,logical_document_id,canonical_text FROM documents WHERE id=?',
                                                   (item['document_id'],)).fetchone()
                    if not saved or saved['case_id'] != record['case_id'] or saved['logical_document_id'] != item['logical_document_id']:
                        raise ValueError('Saved document reference does not match this case and filing.')
                    if saved['canonical_text']:
                        documents.original_path(data_dir, item['document_id'])
                        item.update(status='fetched', detail='Saved searchable version reused; not analysed.')
                        continue
                if (count >= constants.SEC_MAX_DOCUMENTS or
                        total + (item['size'] or 0) > constants.SEC_MAX_IMPORT_BYTES):
                    item.update(status='not fetched', detail='Import download limit reached; select this document separately if needed.')
                    continue
                count += 1
                content = fetch(item['url'], ua)
                total += len(content)
                if total > constants.SEC_MAX_IMPORT_BYTES:
                    raise ValueError('The 50 MiB import download limit was exceeded; this document was not saved.')
                metadata = {key: record[key] for key in ('filing_date', 'accession_number', 'form_type')}
                metadata.update(source_url=item['url'], exhibit_label=item['document_type']
                                if (item['document_type'] or '').startswith('EX-') else None)
                saved = documents.store_document(data_dir, record['case_id'], content, item['name'],
                    'text/plain' if suffix == '.txt' else 'text/html',
                    logical_document_id=item['logical_document_id'], metadata=metadata)
                item['document_id'] = saved['id']
                if not saved['searchable']:
                    raise ValueError(saved['processing_error'] or 'The saved document has no usable searchable text.')
                item.update(status='fetched', detail='Saved and searchable; not analysed.')
            except Exception as error:
                logger.exception('SEC document import %s failed for %s.', import_id, item['name'])
                item.update(status='failed', detail=str(error))
            finally:
                _save(data_dir, record)
        statement = next((item for item in record['items']
                          if item['url'] == record['selected_document_url']), None)
        missing = [item for item in record['items'] if
                   (item['document_type'] == record['form_type'] or
                    (researching and (item['document_type'] or '').startswith('EX-')))
                   and item['status'] != 'fetched']
        if statement is None:
            record.update(status='partial', detail=notice + 'Exhibit 99.1 is absent. Select the information statement from the document list; the cover form is not a complete statement.')
        elif statement['status'] != 'fetched':
            record.update(status='partial', detail=notice + 'The selected information statement has no verified searchable download. See its status below or choose another listed document.')
        else:
            record.update(status='partial' if missing else 'complete', detail=notice +
                f"Information statement saved and searchable. {len(missing)} required document(s) not fetched or failed. Downloaded text has not been analysed or fully checked for text quality.")
        _save(data_dir, record)
    except Exception as error:
        logger.exception('SEC filing import %s failed.', import_id)
        record.update(status='failed', detail=f'{error} Previously saved documents have been retained.')
        _save(data_dir, record)


def start_import(data_dir: Path, case_id: int, url: str):
    with _start_lock:
        if worker.busy():
            raise ValueError('An import is already running. Wait for it to finish.')
        import_id = prepare_import(data_dir, case_id, url)
        worker.submit(run_import, data_dir, import_id)


def select_statement(data_dir: Path, case_id: int, import_id: int, document_url: str):
    with _start_lock:
        if worker.busy():
            raise ValueError('An import is already running. Wait for it to finish.')
        record = _record(data_dir, import_id)
        if record['case_id'] != case_id or not any(item['url'] == document_url for item in record['items']):
            raise ValueError('Choose a document listed for this case and filing.')
        record.update(status='queued', detail='Waiting to fetch the selected information statement.')
        _save(data_dir, record)
        worker.submit(run_import, data_dir, import_id, document_url)


def recover_interrupted(data_dir: Path):
    with db.DATA_LOCK, closing(db.connect(data_dir)) as connection, connection:
        connection.execute("UPDATE sec_imports SET status='interrupted', detail=? WHERE status IN ('queued','running')",
                           ('The application closed before this import finished. Saved documents remain available; paste the URL again to retry.',))
