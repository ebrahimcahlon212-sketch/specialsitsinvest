"""Bounded public document collection from an owner-supplied HTTPS page."""

import http.client
import ipaddress
import re
import socket
import ssl
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from app import constants, db, documents


def _url(value: str, origin: str | None = None) -> str:
    if not isinstance(value, str) or len(value) > 4000 or re.search(r'[\s\\\x00-\x1f\x7f]', value):
        raise ValueError('Use a public HTTPS URL without spaces or control characters.')
    parts = urlsplit(value)
    host = parts.hostname or ''
    if (parts.scheme != 'https' or parts.username is not None or parts.password is not None
            or parts.port not in (None, 443) or '%' in parts.netloc
            or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host)
            or '.' not in host or host.endswith(('.localhost', '.local', '.internal'))):
        raise ValueError('Only public HTTPS hostnames on port 443 are supported; no credentials.')
    if host == 'sec.gov' or host.endswith('.sec.gov'):
        raise ValueError('Use the existing SEC filing URL importer for SEC documents.')
    if any(re.search(r'token|password|secret|signature|credential|(?:^|_)key$|^sig$', key, re.I)
           for key, _ in parse_qsl(parts.query, max_num_fields=100)):
        raise ValueError('URLs containing authentication or signed-access parameters are not supported.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('Enter an official hostname, not an IP address.')
    netloc = host.lower()
    if origin is not None and netloc != urlsplit(origin).netloc:
        raise ValueError('Outside the supplied HTTPS origin; not fetched automatically.')
    return urlunsplit(('https', netloc, parts.path or '/', parts.query, ''))


def _addresses(url: str) -> list[str]:
    addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(
        urlsplit(url).hostname, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(address).is_global
                            or ipaddress.ip_address(address).is_multicast for address in addresses):
        raise ValueError('The hostname resolves to a non-public address; no request was sent.')
    return addresses


def _check(state: dict):
    if state['cancel'].is_set():
        raise InterruptedError('Document collection cancelled; saved documents are preserved.')
    if time.monotonic() >= state['deadline']:
        raise TimeoutError('The document collection time limit was reached.')


def _request(url: str, state: dict, limit: int) -> tuple[int, dict, bytes]:
    """Connect to a checked IP while verifying TLS against the original hostname."""
    _check(state)
    if state['count'] >= constants.SOURCE_MAX_REQUESTS:
        raise ValueError('The document collection request limit was reached.')
    address = _addresses(url)[0]  # No DNS re-resolution or alternate-address retry.
    delay = state['interval'] - (time.monotonic() - state['last_request'])
    if delay > 0:
        if time.monotonic() + delay >= state['deadline']:
            raise TimeoutError('The site request delay exceeds the remaining collection time.')
        state['cancel'].wait(delay)
        _check(state)
    parts = urlsplit(url)
    target = quote(urlunsplit(('', '', parts.path, parts.query, '')), safe="/%?=&:+,;@!$'()*~-._")
    request = (f'GET {target} HTTP/1.1\r\nHost: {parts.hostname}\r\n'
               f'User-Agent: {constants.SOURCE_USER_AGENT}\r\nAccept-Encoding: identity\r\n'
               'Connection: close\r\n\r\n').encode('ascii')
    state['count'] += 1
    state['last_request'] = time.monotonic()
    timeout = min(constants.SOURCE_TIMEOUT_SECONDS, state['deadline'] - time.monotonic())
    context = ssl.create_default_context()
    context.keylog_filename = None
    with socket.create_connection((address, 443), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=parts.hostname) as secured:
            secured.sendall(request)
            with http.client.HTTPResponse(secured) as response:
                response.begin()
                headers = {key.lower(): value for key, value in response.getheaders()}
                if response.status != 200:
                    return response.status, headers, b''
                if headers.get('content-encoding', 'identity').lower() != 'identity':
                    raise ValueError('The site ignored the uncompressed download request; not imported.')
                length = headers.get('content-length', '')
                if length.isdigit() and int(length) > limit:
                    raise ValueError('The download exceeds the document size limit.')
                content = bytearray()
                while True:
                    _check(state)
                    secured.settimeout(min(constants.SOURCE_TIMEOUT_SECONDS,
                                           state['deadline'] - time.monotonic()))
                    chunk = response.read1(min(65536, limit + 1 - len(content)))
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > limit:
                        raise ValueError('The download exceeds the document size limit.')
                if length.isdigit() and int(length) != len(content):
                    raise ValueError('The response was truncated; no incomplete document was imported.')
                return response.status, headers, bytes(content)


def _fetch(url: str, state: dict, limit: int, robots=None) -> tuple[str, int, dict, bytes]:
    current = url
    for attempt in range(constants.SOURCE_MAX_REDIRECTS + 1):
        current = _url(current, state['origin'])
        if robots is not None and not robots.can_fetch(constants.SOURCE_USER_AGENT, current):
            raise ValueError('robots.txt disallows this URL; no document request was sent.')
        code, headers, content = _request(current, state, limit)
        if code not in (301, 302, 303, 307, 308):
            return current, code, headers, content
        if attempt == constants.SOURCE_MAX_REDIRECTS or not headers.get('location'):
            raise ValueError('The redirect limit was reached or the redirect had no destination.')
        current = urljoin(current, headers['location'])
    raise ValueError('The redirect limit was reached.')


def _robots(state: dict) -> RobotFileParser:
    url = urljoin(state['origin'], '/robots.txt')
    _, code, _, content = _fetch(url, state, constants.SOURCE_ROBOTS_MAX_BYTES)
    parser = RobotFileParser(url)
    if code in (404, 410):
        parser.parse([])
    elif code == 200:
        if b'<html' in content[:1000].lower() or b'<!doctype' in content[:1000].lower():
            raise ValueError('robots.txt returned an HTML page; collection stopped.')
        parser.parse(content.decode('utf-8-sig', errors='strict').splitlines())
    else:
        raise ValueError(f'robots.txt returned HTTP {code}; collection stopped without bypassing it.')
    delay = parser.crawl_delay(constants.SOURCE_USER_AGENT) or 0
    rate = parser.request_rate(constants.SOURCE_USER_AGENT)
    state['interval'] = max(1, delay, rate.seconds / rate.requests if rate and rate.requests else 0)
    return parser


def _gate(soup: BeautifulSoup) -> bool:
    if soup.find('input', attrs={'type': re.compile('password', re.I)}):
        return True
    controls = soup.find(['button', 'select', 'form']) or soup.find('input', attrs={'type': 'checkbox'})
    if not controls:
        return False
    text = soup.get_text(' ', strip=True).lower()
    return bool(re.search(r'verify (?:that )?you are human|select your (?:country|jurisdiction)|'
                         r'country of residence|agree to (?:these|the) terms|'
                         r'accept (?:these|the) (?:terms|restrictions)|'
                         r'confirm that you (?:are|have read)', text))


def _links(soup: BeautifulSoup, url: str, origin: str) -> tuple[list[tuple[str, str]], list[str]]:
    found, excluded, seen = [], [], {url}
    base = soup.find('base', href=True)
    try:
        if base and re.search(r'[\s\\\x00-\x1f\x7f]', base['href']):
            raise ValueError('Malformed base URL.')
        base_url = _url(urljoin(url, base['href']), origin) if base else url
    except ValueError as error:
        return [], [f'Document links were not fetched because the HTML base URL was rejected: {error}']
    for anchor in soup.find_all('a', href=True):
        if len(found) + len(excluded) >= constants.SOURCE_MAX_REQUESTS:
            excluded.append('Link discovery limit reached; further page links were not inspected.')
            break
        href = anchor['href']
        label = anchor.get_text(' ', strip=True)
        combined = (label + ' ' + href).lower()
        try:
            suffix = Path(urlsplit(href).path).suffix.lower()
        except ValueError:
            excluded.append('A malformed page link was not inspected.')
            continue
        if suffix not in ('.pdf', '.htm', '.html', '.txt') and not any(
                term in combined for term in constants.SOURCE_LINK_TERMS):
            continue
        if re.search(r'privacy|cookie|mailto:|javascript:|terms.of.use', combined):
            continue
        candidate = urljoin(base_url, href)
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            candidate = _url(candidate)
        except ValueError as error:
            excluded.append(f'A linked URL was rejected: {error}')
            continue
        try:
            candidate = _url(candidate, origin)
        except ValueError as error:
            excluded.append(f'Linked document not fetched: {candidate[:4000]} ({error})')
            continue
        found.append((candidate, label[:200]))
    return found, excluded


def _save(data_dir: Path, case_id: int, url: str, name: str, content: bytes, media: str) -> dict:
    with closing(db.connect(data_dir)) as connection:
        row = connection.execute('SELECT logical_document_id FROM documents '
            'WHERE case_id=? AND source_url=? ORDER BY id DESC LIMIT 1', (case_id, url)).fetchone()
    identity = row['logical_document_id'] if row else str(uuid.uuid4())
    saved = documents.store_document(data_dir, case_id, content, name, media,
        logical_document_id=identity, metadata={'source_url': url})
    return {'document_id': saved['id'], 'name': saved['name'], 'source_url': url,
            'status': 'searchable' if saved['searchable'] else 'processing failed',
            'processing_error': saved['processing_error']}


def collect_sources(data_dir: Path, case_id: int, url: str, cancel_event, progress) -> dict:
    """Collect one public page and its direct relevant same-origin document links."""
    url = _url(url.strip())
    with closing(db.connect(data_dir)) as connection:
        if not connection.execute('SELECT 1 FROM cases WHERE id=?', (case_id,)).fetchone():
            raise ValueError('Case does not exist.')
    _addresses(url)
    state = {'origin': urlunsplit(('https', urlsplit(url).netloc, '/', '', '')),
             'count': 0, 'cancel': cancel_event, 'deadline': time.monotonic() + constants.SOURCE_MAX_SECONDS,
             'last_request': 0, 'interval': 0}
    result = {'url': url, 'documents': [], 'gaps': [], 'cancelled': False,
              'checked_at': datetime.now(timezone.utc).isoformat(), 'request_count': 0,
              'version': constants.SOURCE_COLLECTION_VERSION, 'status': 'partial'}
    try:
        progress('Checking the public source and its robots.txt access rules.')
        robots = _robots(state)
        pending, seen = [(url, '')], set()
        for index, (candidate, label) in enumerate(pending):
            _check(state)
            if candidate in seen:
                continue
            if state['count'] >= constants.SOURCE_MAX_REQUESTS:
                result['gaps'].append('Request limit reached; remaining links were not fetched.')
                break
            if len(result['documents']) >= constants.SOURCE_MAX_DOCUMENTS:
                result['gaps'].append('Document limit reached; remaining links were not fetched.')
                break
            seen.add(candidate)
            progress(f'Collecting public document {len(result["documents"]) + 1}: {candidate}')
            try:
                final, code, headers, content = _fetch(candidate, state, constants.MAX_DOCUMENT_BYTES, robots)
                if code != 200:
                    raise ValueError(f'HTTP {code}; no retry, sign-in or access bypass was attempted.')
                if final != candidate and final in seen:
                    continue
                seen.add(final)
                media = headers.get('content-type', '').split(';')[0].strip().lower()
                if content.startswith(b'%PDF-'):
                    media = 'application/pdf'
                elif media == 'application/xhtml+xml':
                    media = 'text/html'
                if media not in ('text/html', 'text/plain', 'application/pdf'):
                    raise ValueError(f'Unsupported document type: {media or "not supplied"}.')
                soup = BeautifulSoup(content, 'lxml') if media == 'text/html' else None
                if soup is not None and _gate(soup):
                    raise ValueError('Access confirmation, sign-in or anti-bot page; owner action is required.')
                if soup is not None and index == 0:
                    links, excluded = _links(soup, final, state['origin'])
                    result['gaps'].extend(excluded)
                    pending.extend(links)
                    if not links:
                        result['gaps'].append('No directly linked same-origin documents were discovered; '
                                              'JavaScript, other websites and deeper pages were not searched.')
                title = soup.title.get_text(' ', strip=True) if soup is not None and soup.title else ''
                name = (title or label or Path(urlsplit(final).path).name or urlsplit(final).hostname)[:200]
                saved = _save(data_dir, case_id, final, name, content, media)
                result['documents'].append(saved)
                if saved['processing_error']:
                    result['gaps'].append(f'{name}: {saved["processing_error"]}')
                if media == 'application/pdf':
                    result['gaps'].append(f'{name}: PDF text extraction does not verify images, tables or reading order.')
            except (ValueError, OSError, http.client.HTTPException) as error:
                if isinstance(error, InterruptedError):
                    raise
                result['gaps'].append(f'{candidate}: {error}')
    except (ValueError, OSError, http.client.HTTPException) as error:
        result['cancelled'] = isinstance(error, InterruptedError)
        result['gaps'].append(str(error))
    result['request_count'] = state['count']
    result['gaps'].append('Bounded collection only: the owner-supplied site identity, document completeness '
                          'and latest event status have not been established.')
    return result
