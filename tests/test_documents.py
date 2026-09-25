"""Synthetic structural checks only; no real filing or live service is represented."""

import hashlib
import json
from contextlib import closing
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app import db, documents


@pytest.fixture
def local_case(tmp_path):
    data_dir = tmp_path / 'isolated-data'
    db.initialize(data_dir)
    with closing(db.connect(data_dir)) as connection, connection:
        connection.execute("INSERT INTO cases(id, title, created_at) VALUES (1, 'Synthetic case', 'synthetic-date')")
        connection.execute("INSERT INTO cases(id, title, created_at) VALUES (2, 'Other synthetic case', 'synthetic-date')")
    source = tmp_path / 'synthetic.html'
    fixture = Path(__file__).parent / 'fixtures' / 'synthetic_document.html'
    source.write_bytes(fixture.read_bytes())
    return data_dir, source


def test_sanitised_html_search_and_quote_round_trip(local_case):
    data_dir, source = local_case
    saved = documents.import_local(data_dir, 1, source)
    assert saved['searchable'] and saved['processing_error'] is None
    assert saved['filing_date'] is None and saved['form_type'] is None
    result = documents.read_document(data_dir, saved['id'], quote='Alpha beta gamma delta.')
    parsed = BeautifulSoup(result['html'], 'lxml')
    assert not parsed.find(['script', 'style', 'a', 'img', 'iframe', 'svg'])
    assert not any(name not in {'rowspan', 'colspan'}
                   for tag in parsed.find_all(True) for name in tag.attrs)
    assert parsed.th['colspan'] == '2'
    assert 'Safe link text' in result['canonical_text']
    assert 'synthetic_forbidden_call' not in result['canonical_text']
    assert 'Synthetic iframe content' not in result['canonical_text']
    citation = result['citation']
    assert citation['status'] == 'quote matched'
    assert citation['document_hash'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert citation['text_version_id'] == saved['id']
    expected = 'Alpha\xa0 beta gamma delta.'
    assert citation['quote'] == expected
    assert result['canonical_text'][citation['start_offset']:citation['end_offset']] == expected
    assert ''.join(mark.get_text() for mark in parsed.find_all('mark')) == expected
    assert documents.canonical_text(result['html']) == result['canonical_text']
    hits = documents.search(data_dir, 1, 'Second context')
    assert len(hits) == 1 and hits[0]['document_id'] == saved['id']
    assert hits[0]['heading'] == 'Second section'
    assert documents.search(data_dir, 2, 'Second context') == []


def test_sgml_wrapped_html_keeps_filing_body_search_and_highlights(local_case):
    data_dir, source = local_case
    content = (b'<DOCUMENT>\n<TYPE>EX-99.1\n<SEQUENCE>1\n'
               b'<FILENAME>synthetic.htm\n<DESCRIPTION>EX-99.1\n<TEXT>\n'
               b'<HTML><HEAD><TITLE>EX-99.1</TITLE></HEAD><BODY>'
               b'<p>Synthetic cash in lieu of fractional shares.</p>'
               b'<script>synthetic_forbidden_call()</script></BODY></HTML></TEXT></DOCUMENT>')
    source.write_bytes(content)
    saved = documents.import_local(data_dir, 1, source)
    assert documents.original_path(data_dir, saved['id']).read_bytes() == content
    hit, = documents.search(data_dir, 1, 'fractional shares')
    result = documents.read_document(data_dir, saved['id'], hit['block_id'], 'fractional shares')
    assert result['canonical_text'] == 'Synthetic cash in lieu of fractional shares.'
    assert '<mark>fractional shares</mark>' in result['html']
    assert documents.canonical_text(result['html']) == result['canonical_text']
    assert 'script' not in result['html']


def test_table_highlight_does_not_move_whitespace_outside_cells():
    markup = ('<p>Synthetic prefix.</p><table><tr><td><p>Question?</p></td>\n'
              '<td><p>fractional shares</p></td></tr></table>')
    text = documents.canonical_text(markup)
    marked = documents._highlight(markup, text, text.index('Question?'), len(text))
    assert documents.canonical_text(marked) == text
    assert '<mark>fractional shares</mark>' in marked


@pytest.mark.parametrize('empty_ends', ['', '<p> </p><table><tr><td> </td></tr></table>'])
def test_table_highlight_does_not_move_whitespace_outside_cells(empty_ends):
    markup = ('<p>Synthetic prefix.</p><table><tr><td><p>Question?</p></td>\n'
              '<td><p>fractional shares</p></td></tr></table>')
    cleaned = documents.clean((empty_ends + markup + empty_ends).encode(), 'text/html')
    text = documents.canonical_text(markup)
    assert cleaned['canonical_text'] == text
    assert all(0 <= b['start_offset'] < b['end_offset'] <= len(text) for b in cleaned['blocks'])
    marked = documents._highlight(markup, text, text.index('Question?'), len(text))
    assert documents.canonical_text(marked) == text
    assert '<mark>fractional shares</mark>' in marked

@pytest.mark.parametrize('quote', ['quoted phrase', 'quoted'])
def test_highlight_keeps_trailing_mixed_node_whitespace(quote):
    markup = '<p>Synthetic prefix quoted phrase \n<b>next</b></p>'
    text = documents.canonical_text(markup)
    start, end = documents.match_quote(text, quote)
    assert documents.canonical_text(documents._highlight(markup, text, start, end)) == text


def test_repeated_quotes_need_context_and_cannot_cross_documents(local_case):
    data_dir, source = local_case
    saved = documents.import_local(data_dir, 1, source)
    with pytest.raises(ValueError, match='ambiguous'):
        documents.read_document(data_dir, saved['id'], quote='repeated phrase')
    block = documents.search(data_dir, 1, 'Second context')[0]
    result = documents.read_document(data_dir, saved['id'], block['id'], 'repeated phrase')
    assert result['citation']['start_offset'] > result['canonical_text'].index('repeated phrase')
    with pytest.raises(ValueError, match='not found'):
        documents.read_document(data_dir, saved['id'], block['id'], 'First context')
    other = documents.import_local(data_dir, 2, source)
    with pytest.raises(ValueError, match='does not belong'):
        documents.read_document(data_dir, other['id'], block['id'])


def test_saved_repeated_quote_reopens_at_its_original_offsets(local_case):
    data_dir, source = local_case
    saved = documents.import_local(data_dir, 1, source)
    block = documents.search(data_dir, 1, 'Second context')[0]
    matched = documents.read_document(data_dir, saved['id'], block['id'], 'repeated phrase')
    with closing(db.connect(data_dir)) as connection, connection:
        connection.execute('INSERT INTO settings VALUES (?, ?)',
                           ('synthetic_saved_citation', json.dumps(matched['citation'])))
    with closing(db.connect(data_dir)) as reopened:
        citation = json.loads(reopened.execute(
            "SELECT value FROM settings WHERE key = 'synthetic_saved_citation'"
        ).fetchone()[0])
    result = documents.read_citation(data_dir, citation)
    assert result == matched
    assert result['citation']['start_offset'] > result['canonical_text'].index('repeated phrase')
    with pytest.raises(ValueError, match='exact text'):
        documents.read_citation(data_dir, {**citation, 'start_offset': 0})


@pytest.mark.parametrize(('text', 'quote', 'expected'), [
    ('  Alpha\t\n\xa0beta end  ', 'Alpha beta', (2, 14)),
    ('left one\r\n  two right', 'one two', (5, 15)),
    ('SYNTHETIC <literal> & text', '<literal> &', (10, 21)),
])
def test_whitespace_offsets_match_original_text(text, quote, expected):
    assert documents.match_quote(text, quote) == expected


def test_reimport_deduplicates_bytes_and_keeps_case_associations(local_case):
    data_dir, source = local_case
    first = documents.import_local(data_dir, 1, source)
    renamed = source.with_name('synthetic-renamed.html')
    renamed.write_bytes(source.read_bytes())
    repeated = documents.import_local(data_dir, 1, renamed)
    assert first == repeated
    other = documents.import_local(data_dir, 2, renamed)
    assert first['logical_document_id'] != other['logical_document_id']
    assert documents.original_path(data_dir, first['id']) == documents.original_path(data_dir, other['id'])
    with closing(db.connect(data_dir)) as connection:
        assert connection.execute('SELECT count(*) FROM documents').fetchone()[0] == 4
    assert len(list((data_dir / 'documents').iterdir())) == 2
    assert len(documents.list_documents(data_dir, 1)) == 1


def test_shared_storage_keeps_metadata_on_original_and_cleaned_versions(local_case):
    data_dir, source = local_case
    # Explicitly synthetic metadata; no accession number or real filing is invented.
    metadata = {'source_url': 'https://example.invalid/synthetic-document.html',
                'filing_date': '2000-01-01', 'accession_number': None,
                'form_type': 'synthetic-form', 'exhibit_label': 'synthetic-exhibit', 'company_id': 7}
    with closing(db.connect(data_dir)) as connection, connection:
        connection.execute("INSERT INTO companies(id, name) VALUES (7, 'Synthetic company')")
    first = documents.store_document(data_dir, 1, source.read_bytes(), source.name, 'text/html',
                                    logical_document_id='synthetic-source', metadata=metadata)
    newer = documents.store_document(data_dir, 1, source.read_bytes(), source.name, 'text/html',
                                    logical_document_id='synthetic-source', metadata=metadata,
                                    cleaner_version='synthetic-cleaner-next')
    assert first['id'] != newer['id'] and first['searchable'] and newer['searchable']
    with closing(db.connect(data_dir)) as connection:
        rows = connection.execute('SELECT * FROM documents ORDER BY id').fetchall()
    assert len(rows) == 3 and rows[0]['cleaner_version'] is None
    assert all({key: row[key] for key in metadata} == metadata for row in rows)
    assert len({row['retrieved_at'] for row in rows}) == 1
    assert documents.read_document(data_dir, first['id'])['filing_date'] == '2000-01-01'


def test_shared_storage_deduplicates_and_preserves_distinct_associations(local_case):
    data_dir, source = local_case
    content = source.read_bytes()
    local = documents.import_local(data_dir, 1, source)
    metadata = {'source_url': 'https://example.invalid/synthetic-first.html'}
    first = documents.store_document(data_dir, 1, content, source.name, 'text/html',
                                    logical_document_id='synthetic-first', metadata=metadata)
    repeated = documents.store_document(data_dir, 1, content, source.name, 'text/html',
                                       logical_document_id='synthetic-first', metadata=metadata)
    other = documents.store_document(data_dir, 1, content, source.name, 'text/html',
                                    logical_document_id='synthetic-other',
                                    metadata={'source_url': 'https://example.invalid/synthetic-other.html'})
    assert first == repeated
    assert len({item['logical_document_id'] for item in (local, first, other)}) == 3
    assert len({documents.original_path(data_dir, item['id']) for item in (local, first, other)}) == 1
    assert len(list((data_dir / 'documents').iterdir())) == 2
    changed = documents.store_document(data_dir, 1, b'<p>Changed synthetic bytes.</p>', source.name,
                                      'text/html', logical_document_id='synthetic-first', metadata=metadata)
    assert changed['id'] != first['id'] and changed['original_sha256'] != first['original_sha256']
    assert changed['logical_document_id'] == first['logical_document_id']
    assert documents.original_path(data_dir, first['id']).read_bytes() == content
    assert len(documents.list_documents(data_dir, 1)) == 3
    with pytest.raises(ValueError, match='another case'):
        documents.store_document(data_dir, 2, content, source.name, 'text/html',
                                 logical_document_id='synthetic-first', metadata=metadata)
    with closing(db.connect(data_dir)) as connection:
        assert connection.execute('SELECT count(*) FROM documents').fetchone()[0] == 8


def test_shared_storage_rejects_unsupported_media_before_saving(local_case):
    data_dir, _ = local_case
    with pytest.raises(ValueError, match='Only HTML'):
        documents.store_document(data_dir, 1, b'Synthetic unsupported bytes', 'synthetic.pdf',
                                 'application/pdf')
    assert not list((data_dir / 'documents').iterdir())


def test_changed_bytes_at_same_selected_path_preserve_original(local_case):
    data_dir, source = local_case
    original_bytes = source.read_bytes()
    first = documents.import_local(data_dir, 1, source)
    source.write_text('<p>Changed synthetic content.</p>', encoding='utf-8')
    changed = documents.import_local(data_dir, 1, source)
    assert changed['original_sha256'] != first['original_sha256']
    assert documents.original_path(data_dir, first['id']).read_bytes() == original_bytes
    assert len(documents.list_documents(data_dir, 1)) == 2


def test_new_cleaner_version_preserves_old_citation(local_case, monkeypatch):
    data_dir, source = local_case
    first = documents.import_local(data_dir, 1, source)
    old = documents.read_document(data_dir, first['id'], quote='Alpha beta gamma delta.')
    original_clean = documents.clean

    def synthetic_changed_cleaner(content, media_type):
        changed = content.replace(b'</body>', b'<p>Synthetic cleaner two addition.</p></body>')
        return original_clean(changed, media_type)

    monkeypatch.setattr(documents, 'clean', synthetic_changed_cleaner)
    second = documents.import_local(data_dir, 1, source, cleaner_version='synthetic-version-2')
    assert second['id'] != first['id']
    assert second['logical_document_id'] == first['logical_document_id']
    assert second['text_hash'] != first['text_hash']
    assert documents.read_document(data_dir, first['id'], quote='Alpha beta gamma delta.') == old
    assert documents.list_documents(data_dir, 1)[0]['id'] == second['id']
    assert {hit['document_id'] for hit in documents.search(data_dir, 1, 'Alpha')} == {second['id']}


def test_plain_text_is_escaped_before_display(local_case):
    data_dir, source = local_case
    source = source.with_suffix('.txt')
    source.write_text('<script>synthetic()</script>\nPlain <b>text</b> & value.', encoding='utf-8')
    saved = documents.import_local(data_dir, 1, source)
    result = documents.read_document(data_dir, saved['id'], quote='Plain <b>text</b> & value.')
    parsed = BeautifulSoup(result['html'], 'lxml')
    assert not parsed.find(['script', 'b'])
    assert '<script>synthetic()</script>' in result['canonical_text']
    assert result['citation']['quote'] == 'Plain <b>text</b> & value.'


@pytest.mark.parametrize('content', [b'\xff\xfe\x00', b'', b'<script>synthetic()</script>'])
def test_unusable_documents_retain_original_and_visible_error(local_case, content):
    data_dir, source = local_case
    if content.startswith(b'\xff'):
        source = source.with_suffix('.txt')
    source.write_bytes(content)
    saved = documents.import_local(data_dir, 1, source)
    assert saved['processing_error'] and not saved['searchable']
    assert documents.original_path(data_dir, saved['id']).read_bytes() == content
    assert documents.list_documents(data_dir, 1)[0]['processing_error'] == saved['processing_error']
    with pytest.raises(ValueError):
        documents.read_document(data_dir, saved['id'])


def test_oversized_tables_retain_column_context_and_mark_partial(local_case, monkeypatch):
    data_dir, source = local_case
    monkeypatch.setattr(documents, 'MAX_BLOCK_CHARS', 60)
    rows = ''.join(f'<tr><td>Synthetic row {number}</td><td>Other cell {number}</td></tr>'
                   for number in range(12))
    source.write_text('<h2>Synthetic table</h2><table><thead><tr><th>Label</th><th>Context</th>'
                      '</tr></thead><tbody>' + rows + '</tbody></table>', encoding='utf-8')
    saved = documents.import_local(data_dir, 1, source)
    result = documents.read_document(data_dir, saved['id'])
    hits = documents.search(data_dir, 1, 'Synthetic row')
    assert hits and all(hit['partial'] for hit in hits)
    assert all('Label' in hit['heading'] and 'Context' in hit['heading'] for hit in hits)
    assert all(len(hit['text']) <= 60 for hit in hits)
    for hit in hits:
        assert hit['text'] == result['canonical_text'][hit['start_offset']:hit['end_offset']]


def test_size_limit_and_original_hash_failure_are_explicit(local_case, monkeypatch):
    data_dir, source = local_case
    saved = documents.import_local(data_dir, 1, source)
    stored = documents.original_path(data_dir, saved['id'])
    stored.write_bytes(b'Synthetic corruption')
    with pytest.raises(ValueError, match='hash check'):
        documents.original_path(data_dir, saved['id'])
    with pytest.raises(ValueError, match='not overwritten'):
        documents.import_local(data_dir, 1, source)
    assert stored.read_bytes() == b'Synthetic corruption'
    monkeypatch.setattr(documents, 'MAX_DOCUMENT_BYTES', 5)
    with pytest.raises(ValueError, match='exceeds'):
        documents.import_local(data_dir, 1, source)


def test_clean_html_hash_and_path_escape_are_rejected(local_case):
    data_dir, source = local_case
    saved = documents.import_local(data_dir, 1, source)
    with closing(db.connect(data_dir)) as connection:
        relative = connection.execute('SELECT clean_html_path FROM documents WHERE id = ?',
                                      (saved['id'],)).fetchone()[0]
    (data_dir / relative).write_bytes(b'<script>synthetic corruption</script>')
    with pytest.raises(ValueError, match='hash check'):
        documents.read_document(data_dir, saved['id'])
    with pytest.raises(ValueError, match='outside'):
        documents._stored_path(data_dir, '../outside')
