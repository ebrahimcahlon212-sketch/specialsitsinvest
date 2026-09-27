"""Synthetic HTTP structures plus a saved real filing; no live network calls."""

from contextlib import closing
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from app import constants, db, documents, sources


@pytest.fixture
def local_case(tmp_path, monkeypatch):
    data_dir = tmp_path / 'isolated-data'
    db.initialize(data_dir)
    with closing(db.connect(data_dir)) as connection, connection:
        connection.execute("INSERT INTO cases(id,title,created_at) VALUES (1,'Synthetic source case','test')")
    monkeypatch.setattr(sources.socket, 'getaddrinfo', lambda *args, **kwargs:
        [(sources.socket.AF_INET, sources.socket.SOCK_STREAM, 0, '', ('93.184.215.14', 443))])
    return data_dir


def serve(monkeypatch, responses):
    calls = []

    def request(url, state, limit):
        sources._check(state)
        state['count'] += 1
        calls.append(url)
        code, headers, content = responses[url]
        return code, headers, content

    monkeypatch.setattr(sources, '_request', request)
    return calls


def test_real_filing_bytes_search_duplicate_and_changed_version(local_case, monkeypatch):
    # Real Sandisk fixture served under an explicitly synthetic issuer URL.
    fixture = Path(__file__).parent / 'fixtures' / 'sandisk_20241125_d835366dex991.htm'
    content = fixture.read_bytes()
    root = 'https://issuer.example/'
    page = b'<title>Synthetic investor page</title><p>Document list.</p><a href="/statement.htm">Information statement</a>'
    responses = {root + 'robots.txt': (404, {}, b''), root: (200, {'content-type': 'text/html'}, page),
                 root + 'statement.htm': (200, {'content-type': 'text/html'}, content)}
    calls = serve(monkeypatch, responses)
    first = sources.collect_sources(local_case, 1, root, Event(), lambda value: None)
    filing = first['documents'][1]
    assert filing['status'] == 'searchable'
    assert documents.original_path(local_case, filing['document_id']).read_bytes() == content
    assert documents.search(local_case, 1, 'fractional shares')
    second = sources.collect_sources(local_case, 1, root, Event(), lambda value: None)
    assert [row['document_id'] for row in first['documents']] == [row['document_id'] for row in second['documents']]
    responses[root + 'statement.htm'] = (200, {'content-type': 'text/html'}, b'<p>Synthetic revised content.</p>')
    third = sources.collect_sources(local_case, 1, root, Event(), lambda value: None)
    assert third['documents'][1]['document_id'] != filing['document_id']
    with closing(db.connect(local_case)) as connection:
        identities = connection.execute('SELECT DISTINCT logical_document_id FROM documents WHERE source_url=?',
                                        (root + 'statement.htm',)).fetchall()
    assert len(identities) == 1
    assert documents.original_path(local_case, filing['document_id']).read_bytes() == content
    assert first['request_count'] == 3 and len(calls) == 9
    assert first['status'] == 'partial' and 'completeness' in first['gaps'][-1]


@pytest.mark.parametrize('url', ['http://issuer.example/', 'https://user:pass@issuer.example/',
    'https://issuer.example:444/', 'https://127.0.0.1/', 'https://[::1]/',
    'https://host.local/', 'https://localhost/', 'https://issuer.example/\npath',
    'https://issuer.example\\@other.example/', 'https://www.sec.gov/Archives/',
    'https://issuer.example/?access_token=synthetic-secret'])
def test_invalid_entry_is_rejected_before_network(local_case, monkeypatch, url):
    calls = serve(monkeypatch, {})
    with pytest.raises(ValueError):
        sources.collect_sources(local_case, 1, url, Event(), lambda value: None)
    assert calls == []


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', 'fc00::1',
                                    '100.64.0.1', '224.0.0.1', 'ff02::1'])
def test_private_dns_is_rejected_before_network(local_case, monkeypatch, address):
    monkeypatch.setattr(sources.socket, 'getaddrinfo', lambda *args, **kwargs:
        [(sources.socket.AF_INET, sources.socket.SOCK_STREAM, 0, '', (address, 443))])
    calls = serve(monkeypatch, {})
    with pytest.raises(ValueError, match='non-public'):
        sources.collect_sources(local_case, 1, 'https://issuer.example/', Event(), lambda value: None)
    assert not calls


@pytest.mark.parametrize('target', ['https://other.example/statement.pdf', 'http://issuer.example/document',
                                   'https://127.0.0.1/private', 'https://issuer.example:8443/document'])
def test_redirect_escape_not_requested(local_case, monkeypatch, target):
    root = 'https://issuer.example/'
    calls = serve(monkeypatch, {root + 'robots.txt': (404, {}, b''), root: (302, {'location': target}, b'')})
    result = sources.collect_sources(local_case, 1, root, Event(), lambda value: None)
    assert not result['documents'] and result['gaps']
    assert calls == [root + 'robots.txt', root]


def test_robots_denial_and_offsite_links_are_visible(local_case, monkeypatch):
    root = 'https://issuer.example/'
    page = b'<p>Synthetic investor page.</p><a href="/blocked.htm">Scheme document</a><a href="https://cdn.example/scheme.pdf">Scheme PDF</a>'
    calls = serve(monkeypatch, {root + 'robots.txt': (200, {}, b'User-agent: *\nDisallow: /blocked.htm'),
        root: (200, {'content-type': 'text/html'}, page)})
    result = sources.collect_sources(local_case, 1, root, Event(), lambda value: None)
    assert len(result['documents']) == 1
    assert any('robots.txt disallows' in gap for gap in result['gaps'])
    assert any('https://cdn.example/scheme.pdf' in gap for gap in result['gaps'])
    assert len(calls) == 2


@pytest.mark.parametrize('code', [403, 429, 500])
def test_access_failure_is_not_retried(local_case, monkeypatch, code):
    root = 'https://issuer.example/'
    calls = serve(monkeypatch, {root + 'robots.txt': (404, {}, b''), root: (code, {}, b'')})
    result = sources.collect_sources(local_case, 1, root, Event(), lambda value: None)
    assert len(calls) == 2 and not result['documents']
    assert any(f'HTTP {code}' in gap for gap in result['gaps'])


def test_access_gate_not_saved_as_filing(local_case, monkeypatch):
    root = 'https://issuer.example/'
    page = b'<p>Confirm that you have read the restrictions.</p><select><option>United Kingdom</option></select><button>Agree</button>'
    serve(monkeypatch, {root + 'robots.txt': (404, {}, b''), root: (200, {'content-type': 'text/html'}, page)})
    result = sources.collect_sources(local_case, 1, root, Event(), lambda value: None)
    assert not result['documents'] and any('owner action' in gap for gap in result['gaps'])
    assert documents.list_documents(local_case, 1) == []


def test_cancel_and_document_limit_preserve_completed_imports(local_case, monkeypatch):
    root = 'https://issuer.example/'
    page = b'<p>Synthetic page.</p><a href="/one.txt">Offer document</a><a href="/two.txt">Scheme document</a>'
    responses = {root + 'robots.txt': (404, {}, b''), root: (200, {'content-type': 'text/html'}, page),
                 root + 'one.txt': (200, {'content-type': 'text/plain'}, b'Synthetic offer text.')}
    calls = serve(monkeypatch, responses)
    monkeypatch.setattr(constants, 'SOURCE_MAX_DOCUMENTS', 2)
    result = sources.collect_sources(local_case, 1, root, Event(), lambda value: None)
    assert len(result['documents']) == 2 and any('Document limit' in gap for gap in result['gaps'])
    event = Event()
    event.set()
    cancelled = sources.collect_sources(local_case, 1, root, event, lambda value: None)
    assert cancelled['cancelled'] and cancelled['request_count'] == 0 and len(calls) == 3
    assert len(documents.list_documents(local_case, 1)) == 2


@pytest.mark.parametrize('length, body, limit, error', [(5, b'hello', 1024, None),
    (5000, b'hello', 1024, 'size limit'), (6, b'hello', 1024, 'truncated'),
    (None, b'hello!', 5, 'size limit')])
def test_public_ip_is_pinned_and_tls_keeps_official_hostname(monkeypatch, length, body, limit, error):
    # Synthetic transport, exercising the actual request builder without network I/O.
    import io
    sent, destinations, server_names = [], [], []
    header = f'Content-Length: {length}\r\n' if length is not None else ''
    wire = io.BytesIO(('HTTP/1.1 200 OK\r\n' + header + 'Content-Type: text/plain\r\n\r\n').encode() + body)
    secured = SimpleNamespace(sendall=sent.append, makefile=lambda *args: wire, settimeout=lambda value: None,
                              close=lambda: None)
    context = SimpleNamespace(wrap_socket=lambda sock, server_hostname:
        (server_names.append(server_hostname) or closing(secured)))
    monkeypatch.setattr(sources.ssl, 'create_default_context', lambda: context)
    monkeypatch.setattr(sources, '_addresses', lambda url: ['93.184.215.14'])
    monkeypatch.setattr(sources.socket, 'create_connection', lambda address, timeout:
        (destinations.append(address) or closing(SimpleNamespace(close=lambda: None))))
    state = {'cancel': Event(), 'deadline': sources.time.monotonic() + 30, 'count': 0,
             'interval': 0, 'last_request': 0}
    if error:
        with pytest.raises(ValueError, match=error):
            sources._request('https://issuer.example/scheme.pdf', state, limit)
    else:
        code, headers, body = sources._request('https://issuer.example/scheme.pdf', state, limit)
        assert code == 200 and body == b'hello'
    assert destinations == [('93.184.215.14', 443)] and server_names == ['issuer.example']
    assert b'Host: issuer.example\r\n' in sent[0] and b'Authorization' not in sent[0]
    assert state['count'] == 1 and context.keylog_filename is None


def test_request_limit_stops_before_another_fetch(local_case, monkeypatch):
    root = 'https://issuer.example/'
    page = b'<p>Synthetic page.</p><a href="/one.txt">Offer document</a>'
    calls = serve(monkeypatch, {root + 'robots.txt': (404, {}, b''),
                              root: (200, {'content-type': 'text/html'}, page)})
    monkeypatch.setattr(constants, 'SOURCE_MAX_REQUESTS', 2)
    result = sources.collect_sources(local_case, 1, root, Event(), lambda value: None)
    assert len(calls) == 2 and len(result['documents']) == 1
    assert any('Request limit' in gap for gap in result['gaps'])


@pytest.mark.parametrize('base, expected', [('', 'https://issuer.example/scheme.pdf'),
    ('/deal/', 'https://issuer.example/deal/scheme.pdf'),
    ('https://issuer.example/deal/', 'https://issuer.example/deal/scheme.pdf'),
    ('https://other.example/deal/', None), ('https://[', None), ('/bad\npath/', None)])
def test_html_base_resolution_preserves_origin_restrictions(base, expected):
    # Synthetic HTML: a rejected base must not fall back to the wrong document URL.
    soup = sources.BeautifulSoup(f'<base href="{base}"><a href="scheme.pdf">Scheme document</a>', 'lxml')
    links, gaps = sources._links(soup, 'https://issuer.example/investors', 'https://issuer.example/')
    if expected:
        assert links == [(expected, 'Scheme document')] and not gaps
    else:
        assert not links and len(gaps) == 1 and 'base URL was rejected' in gaps[0]
