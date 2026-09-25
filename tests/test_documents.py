"""Labelled synthetic checks and saved real filing retrieval; no live service calls."""

import hashlib
import json
from contextlib import closing
from io import BytesIO
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from pypdf import PdfWriter, get_configuration
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

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
        documents.store_document(data_dir, 1, b'Synthetic unsupported bytes', 'synthetic.zip',
                                 'application/zip')
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


def test_question_terms_are_literal_and_only_selected_version_is_used(local_case):
    data_dir, _ = local_case
    old = documents.store_document(data_dir, 1, b'<p>Synthetic Alpha original gamma delta.</p>',
                                   'Synthetic old', 'text/html', logical_document_id='synthetic-question')
    documents.store_document(data_dir, 1, b'<p>Synthetic Alpha later-amendment.</p>',
                             'Synthetic later', 'text/html', logical_document_id='synthetic-question')
    documents.store_document(data_dir, 2, b'<p>Synthetic Alpha other-case.</p>',
                             'Synthetic other', 'text/html', logical_document_id='synthetic-other')
    result = documents.retrieve_question_passages(data_dir, 1, old['id'],
                                                 'What are "Alpha": NOT (gamma* OR ^delta) [shares]?')
    assert result['searches'] == ['"alpha"', '"not"', '"gamma"', '"delta"', '"shares"']
    assert result['source']['document_id'] == old['id']
    assert result['passages'] and all(p['document_id'] == old['id'] for p in result['passages'])
    text = '\n'.join(p['text'] for p in result['passages'])
    assert 'original' in text and 'later-amendment' not in text and 'other-case' not in text


def test_question_no_hit_is_valid_but_missing_index_or_wrong_case_is_not(local_case):
    data_dir, source = local_case
    saved = documents.import_local(data_dir, 1, source)
    for question in ('Zyzzyvaquux', '() : "*', 'What is it?'):
        result = documents.retrieve_question_passages(data_dir, 1, saved['id'], question)
        assert result['passages'] == [] and result['source']['document_id'] == saved['id']
        assert any('absence from the filing is not established' in note for note in result['warnings'])
    with pytest.raises(ValueError, match='does not belong'):
        documents.retrieve_question_passages(data_dir, 2, saved['id'], 'Alpha?')
    with closing(db.connect(data_dir)) as connection, connection:
        connection.execute("INSERT INTO blocks_fts(blocks_fts) VALUES ('delete-all')")
    with pytest.raises(ValueError, match='index is incomplete'):
        documents.retrieve_question_passages(data_dir, 1, saved['id'], 'Zyzzyvaquux')


def test_question_table_context_keeps_headers_and_obeys_total_limits(local_case):
    data_dir, source = local_case
    rows = '<tr><td>Unrelated synthetic row ' + 'context ' * 30 + '</td><td>20</td></tr>'
    source.write_text(''.join('<h2>Synthetic company ' + str(index) + '</h2><p>USD millions.</p>'
                             '<table><tr><th>Metric</th><th>Year ended 2024</th></tr>' + rows * 50
                             + '<tr><td>Target revenue</td><td>125</td></tr></table>'
                             for index in range(6)), encoding='utf-8')
    saved = documents.import_local(data_dir, 1, source)
    result = documents.retrieve_question_passages(data_dir, 1, saved['id'], 'Target revenue?')
    assert 1 <= len(result['passages']) <= 6
    assert sum(len(p['text']) for p in result['passages']) <= 24_000
    text = '\n'.join(p['text'] for p in result['passages'])
    assert 'Target revenue' in text and 'USD millions' in text and 'Year ended 2024' in text
    assert any('passage limit omitted' in note for note in result['warnings'])
    canonical = documents.read_document(data_dir, saved['id'])['canonical_text']
    for passage in result['passages']:
        assert passage['text'] == canonical[passage['start_offset']:passage['end_offset']]
        assert passage['partial']


def test_question_saved_sandisk_passages_keep_source_hash_and_clickable_offsets(local_case):
    data_dir, _ = local_case
    source = Path(__file__).parent / 'fixtures' / 'sandisk_20241220_d835366dex991.htm'
    saved = documents.import_local(data_dir, 1, source)
    result = documents.retrieve_question_passages(data_dir, 1, saved['id'],
                                                 'What happens to fractional shares?')
    assert result['source']['original_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert 1 <= len(result['passages']) <= 6
    assert sum(len(p['text']) for p in result['passages']) <= 24_000
    canonical = documents.read_document(data_dir, saved['id'])['canonical_text']
    for passage in result['passages']:
        assert passage['text'] == canonical[passage['start_offset']:passage['end_offset']]
    passage = next(p for p in result['passages'] if 'fractional shares' in p['text'])
    quote = 'fractional shares'
    start = passage['start_offset'] + passage['text'].index(quote)
    opened = documents.read_citation(data_dir, {'document_id': saved['id'],
        'text_version_id': saved['id'], 'document_hash': result['source']['original_sha256'],
        'quote': quote, 'start_offset': start, 'end_offset': start + len(quote), 'status': 'quote matched'})
    assert opened['citation']['text_version_id'] == saved['id']
    assert '<mark>fractional shares</mark>' in opened['html']


def _synthetic_pdf(pages, *, compress=False, encrypted=False):
    """Structural fixtures: text, blank pages and an image-only simulated scan."""
    output = BytesIO()
    with PdfWriter() as writer:
        for text in pages:
            page = writer.add_blank_page(width=612, height=792)
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                     NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({
                NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject()
            if text is None:
                stream.set_data(b'q 100 0 0 100 0 0 cm BI /W 1 /H 1 /BPC 8 /CS /G ID \x00 EI Q')
            else:
                escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
                stream.set_data(f'BT /F1 12 Tf 50 700 Td ({escaped}) Tj ET'.encode('ascii'))
            page.replace_contents(stream.flate_encode() if compress else stream)
        if encrypted:
            writer.encrypt('synthetic-fixture-password')
        writer.write(output)
    return output.getvalue()


def test_pdf_pages_search_citations_dedup_and_new_versions(local_case):
    data_dir, source = local_case
    source = source.with_suffix('.pdf')
    quote = 'Synthetic debt was USD 125 million at the reporting date.'
    content = _synthetic_pdf(['Synthetic first page has enough explanatory text for extraction.', quote])
    source.write_bytes(content)
    first = documents.import_local(data_dir, 1, source)
    assert first['searchable'] and first['cleaner_version'] == documents.constants.PDF_CLEANER_VERSION
    assert documents.original_path(data_dir, first['id']).read_bytes() == content
    assert documents.import_local(data_dir, 1, source)['id'] == first['id']
    hits = documents.search(data_dir, 1, 'Synthetic debt')
    assert len(hits) == 1 and hits[0]['heading'] == 'Page 2' and not hits[0]['partial']
    opened = documents.read_document(data_dir, first['id'], hits[0]['block_id'], quote)
    assert '<h2>Page 1</h2>' in opened['html'] and '<h2>Page 2</h2>' in opened['html']
    assert f'<mark>{quote}</mark>' in opened['html']
    assert documents.canonical_text(opened['html']) == opened['canonical_text']
    later = documents.import_local(data_dir, 1, source, cleaner_version='synthetic-pdf-version-2')
    assert later['id'] != first['id'] and later['logical_document_id'] == first['logical_document_id']
    assert documents.read_citation(data_dir, opened['citation']) == opened
    assert {hit['document_id'] for hit in documents.search(data_dir, 1, 'Synthetic debt')} == {later['id']}


def test_pdf_blank_image_only_and_low_text_pages_are_explicitly_partial(local_case):
    data_dir, _ = local_case
    content = _synthetic_pdf(['Synthetic readable page contains enough text to support a useful quotation.',
                              '', None, '42'])
    saved = documents.store_document(data_dir, 1, content, 'Synthetic mixed PDF', 'application/pdf')
    opened = documents.read_document(data_dir, saved['id'])
    assert opened['canonical_text'].count('No usable text was extracted from this page') == 2
    assert 'Little usable text was extracted from this page' in opened['html']
    assert 'no OCR was performed' in opened['html']
    with closing(db.connect(data_dir)) as connection:
        blocks = connection.execute('SELECT * FROM blocks WHERE document_id = ?', (saved['id'],)).fetchall()
    assert all(block['partial'] for block in blocks if block['heading'] in {'Page 2', 'Page 3', 'Page 4'})
    assert all(block['text'] == opened['canonical_text'][block['start_offset']:block['end_offset']]
               for block in blocks)
    assert all(block['partial'] for block in blocks if block['text'].startswith('[Extraction notice:'))


@pytest.mark.parametrize('pages', [[''], [None]])
def test_pdf_without_usable_text_preserves_original_and_reports_failure(local_case, pages):
    data_dir, _ = local_case
    content = _synthetic_pdf(pages)
    saved = documents.store_document(data_dir, 1, content, 'Synthetic unreadable PDF', 'application/pdf')
    assert not saved['searchable'] and 'No usable text' in saved['processing_error']
    assert 'no OCR' in saved['processing_error']
    assert documents.original_path(data_dir, saved['id']).read_bytes() == content


@pytest.mark.parametrize('constraint', ['pages', 'stream', 'aggregate'])
def test_pdf_resource_limits_preserve_original_and_restore_library_limits(local_case, monkeypatch, constraint):
    data_dir, _ = local_case
    original_configuration = get_configuration()
    if constraint == 'pages':
        monkeypatch.setattr(documents.constants, 'PDF_MAX_PAGES', 1)
        content = _synthetic_pdf(['Synthetic page one', 'Synthetic page two'])
    else:
        monkeypatch.setattr(documents.constants, 'PDF_MAX_STREAM_BYTES', 150)
        content = _synthetic_pdf(['Synthetic ' * 30] if constraint == 'stream' else ['Synthetic ' * 9] * 2,
                                 compress=True)
    saved = documents.store_document(data_dir, 1, content, 'Synthetic limited PDF', 'application/pdf')
    assert not saved['searchable'] and 'limit' in saved['processing_error'].lower()
    assert documents.original_path(data_dir, saved['id']).read_bytes() == content
    assert get_configuration() == original_configuration


@pytest.mark.parametrize('content', [b'%PDF-1.7\nSynthetic malformed PDF',
                                    _synthetic_pdf(['Synthetic encrypted text.'], encrypted=True)])
def test_malformed_or_encrypted_pdf_is_not_represented_as_read(local_case, content):
    data_dir, _ = local_case
    saved = documents.store_document(data_dir, 1, content, 'Synthetic rejected PDF', 'application/pdf')
    assert not saved['searchable'] and saved['processing_error']
    assert documents.original_path(data_dir, saved['id']).read_bytes() == content


def test_saved_mbgl_final_pdf_cover_ratio_and_page_citation(local_case):
    # Saved official June 4, 2026 information statement; no network in this test.
    # https://s29.q4cdn.com/690959130/files/doc_downloads/2026/06/Mobility-Global-Inc-Information-Statement-June-4-2026.pdf
    data_dir, _ = local_case
    source = Path(__file__).parent / 'fixtures' / 'mbgl_20260604_information_statement.pdf'
    saved = documents.import_local(data_dir, 1, source)
    assert saved['searchable'] and saved['processing_error'] is None
    opened = documents.read_document(data_dir, saved['id'])
    text = opened['canonical_text']
    page_one_end = text.index('\n\nPage 2\n\n')
    assert 'The date of this information statement is June 4, 2026.' in text[:page_one_end]
    quote = ('Each holder of S&P Global common stock will receive one share of Mobility common stock for every '
             'share of S&P Global common stock held as of the close of business on June 15, 2026, the record date for '
             'the Distribution.')
    start, end = documents.match_quote(text, quote, 0, page_one_end)
    citation = {'document_id': saved['id'], 'text_version_id': saved['id'],
                'document_hash': saved['original_sha256'], 'quote': text[start:end],
                'start_offset': start, 'end_offset': end, 'status': 'quote matched'}
    highlighted = documents.read_citation(data_dir, citation)
    marked = BeautifulSoup(highlighted['html'], 'lxml').find_all('mark')
    assert ' '.join(' '.join(mark.stripped_strings) for mark in marked) == quote
    hits = documents.search(data_dir, 1, 'Each holder of S&P Global common stock')
    assert any(hit['heading'] == 'Page 1' and hit['document_id'] == saved['id'] for hit in hits)
