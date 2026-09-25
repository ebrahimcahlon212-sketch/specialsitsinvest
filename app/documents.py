"""Local originals, immutable cleaned versions, search and verified citations."""

import hashlib
import html
import logging
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import nh3
from bs4 import BeautifulSoup, NavigableString, Tag
from pypdf import PdfReader, apply_configuration
from pypdf.errors import LimitReachedError

from app import constants, db
from app.constants import CLEANER_VERSION, MAX_BLOCK_CHARS, MAX_DOCUMENT_BYTES, MAX_SEARCH_RESULTS

logger = logging.getLogger(__name__)


def _safe_html(value: str, *, marks: bool = False) -> str:
    tags = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'ul', 'ol', 'li',
            'table', 'caption', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
            'b', 'strong', 'i', 'em'}
    if marks:
        tags.add('mark')
    return nh3.clean(
        value, tags=tags,
        attributes={'th': {'colspan', 'rowspan'}, 'td': {'colspan', 'rowspan'}},
        clean_content_tags={'script', 'style', 'iframe', 'object', 'embed',
                            'svg', 'math', 'template', 'noscript', 'head'},
        strip_comments=True, link_rel=None,
    )


def _walk(soup: BeautifulSoup) -> tuple[str, list, dict]:
    """One text walker supplies stored text, region offsets and mark positions."""
    parts, nodes, regions = [], [], {}
    offset = 0
    trailing = ''
    stack = [(soup, False)]
    starts = {}
    while stack:
        node, exiting = stack.pop()
        if isinstance(node, NavigableString):
            value = str(node)
            parts.append(value)
            nodes.append((node, offset, offset + len(value), 0))
            offset += len(value)
            trailing = (trailing + value)[-2:]
            continue
        if not isinstance(node, Tag):
            continue
        name = node.name
        separator = ''
        if name in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'table', 'caption'}:
            separator = '\n\n'
        elif name == 'tr':
            separator = '\n'
        elif name in {'th', 'td'}:
            separator = '\t'
        if exiting:
            regions[id(node)] = (starts[id(node)], offset)
        if separator and offset and not trailing.endswith(separator):
            parts.append(separator)
            offset += len(separator)
            trailing = (trailing + separator)[-2:]
        if not exiting:
            starts[id(node)] = offset
            stack.append((node, True))
            stack.extend((child, False) for child in reversed(node.contents))
    full = ''.join(parts)
    left = len(full) - len(full.lstrip())
    right = len(full.rstrip())
    text = full[left:right]
    spans = [(node, max(start, left) - left, min(end, right) - left,
              max(left - start, 0))
             for node, start, end, _ in nodes if end > left and start < right]
    bounds = {key: (min(max(start - left, 0), len(text)), min(max(end - left, 0), len(text)))
              for key, (start, end) in regions.items()}
    return text, spans, bounds


def canonical_text(clean_html: str) -> str:
    options = {'preserve_whitespace_tags': {'html', 'body'}} if '<mark>' in clean_html else {}
    return _walk(BeautifulSoup(clean_html, 'lxml', **options))[0]


def _blocks(soup: BeautifulSoup, text: str, bounds: dict) -> list[dict]:
    names = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'table'}
    units = [tag for tag in soup.find_all(names)
             if not any(parent.name in names for parent in tag.parents)]
    result = []
    heading = None
    previous_end = 0

    def append_range(start, end, label, partial=False):
        while start < end:
            while start < end and text[start].isspace():
                start += 1
            if start == end:
                break
            stop = min(start + MAX_BLOCK_CHARS, end)
            if stop < end:
                boundary = max(text.rfind('\n', start, stop), text.rfind(' ', start, stop))
                if boundary > start:
                    stop = boundary
            trimmed = stop
            while trimmed > start and text[trimmed - 1].isspace():
                trimmed -= 1
            if trimmed > start:
                result.append({'heading': label, 'start_offset': start,
                               'end_offset': trimmed, 'text': text[start:trimmed],
                               'partial': partial})
            start = stop

    for tag in units:
        start, end = bounds[id(tag)]
        append_range(previous_end, start, heading)
        if tag.name in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            heading = text[start:end].strip()
        partial = tag.name == 'table' and end - start > MAX_BLOCK_CHARS
        label = heading
        if partial:
            header = tag.find('thead')
            if header is None:
                header = next((row for row in tag.find_all('tr') if row.find('th')), None)
            columns = ' | '.join(header.stripped_strings) if header else None
            context = ('Partial table; column headings: ' + columns if columns
                       else 'Partial table; column headings could not be identified')
            label = f'{heading}\n{context}' if heading else context
        append_range(start, end, label, partial)
        previous_end = end
    append_range(previous_end, len(text), heading)
    return result


def _pdf_markup(content: bytes) -> tuple[str, set[str]]:
    """Extract text only; generated notices are explicitly separate from source text."""
    limit = constants.PDF_MAX_STREAM_BYTES
    markup = ['<p>[Extraction notice: Text extraction only; no OCR was performed. '
              'Images, tables and reading order may not be represented completely. '
              'Page numbers below count PDF pages, including covers.]</p>']
    partial_pages, usable_characters, stream_bytes, text_bytes = set(), 0, 0, 0
    # Context-local pypdf limits apply before decompression, including font/form
    # streams. These bounds reduce allocation risk; they are not an OS memory cap.
    with apply_configuration(
        maximum_declared_stream_length=limit, array_based_stream_maximum_output_length=limit,
        zlib_maximum_output_length=limit, lzw_maximum_output_length=limit,
        run_length_maximum_output_length=limit, jbig2_maximum_output_length=limit,
        image_maximum_buffer_size=limit, jbig2dec_binary=None,
    ), PdfReader(BytesIO(content), strict=True) as reader:
        if reader.is_encrypted:
            raise ValueError('Encrypted PDFs are not supported; the original was saved.')
        if len(reader.pages) > constants.PDF_MAX_PAGES:
            raise ValueError(f'PDF exceeds the {constants.PDF_MAX_PAGES}-page limit; the original was saved.')
        for number, page in enumerate(reader.pages, 1):
            heading = f'Page {number}'
            markup.append(f'<h2>{heading}</h2>')
            try:
                stream = page.get_contents()
                stream_bytes += len(stream.get_data()) if stream is not None else 0
                if stream_bytes > limit:
                    raise LimitReachedError('PDF page content exceeds the total decoded-stream limit.')
                extracted = page.extract_text()
            except LimitReachedError:
                raise
            except Exception as error:
                logger.warning('PDF page %s could not be extracted: %s', number, error)
                partial_pages.add(heading)
                markup.append('<p>[Extraction notice: This page could not be extracted: '
                              + html.escape(str(error)[:500]) + '. No OCR was performed.]</p>')
                continue
            text_bytes += len(extracted.encode('utf-8'))
            if text_bytes > limit:
                raise LimitReachedError('PDF text exceeds the total extracted-text limit.')
            usable = sum(character.isalnum() for character in extracted)
            usable_characters += usable
            if usable < constants.PDF_MIN_PAGE_CHARS:
                partial_pages.add(heading)
                description = 'No usable text' if not usable else 'Little usable text'
                markup.append(f'<p>[Extraction notice: {description} was extracted from this page. '
                              'It may be blank or image-based; no OCR was performed.]</p>')
            markup.extend(f'<p>{html.escape(line)}</p>' for line in extracted.splitlines())
        if not usable_characters:
            raise ValueError(f'No usable text was extracted from any of the {len(reader.pages)} PDF pages. '
                             'The PDF may be blank or image-based; no OCR was performed. The original was saved.')
    return ''.join(markup), partial_pages


def clean(content: bytes, media_type: str) -> dict:
    partial_pages = set()
    if media_type == 'application/pdf':
        markup, partial_pages = _pdf_markup(content)
        soup = BeautifulSoup(markup, 'lxml')
    elif media_type == 'text/plain':
        try:
            decoded = content.decode('utf-8-sig')
        except UnicodeDecodeError as error:
            raise ValueError('Text file is not valid UTF-8. Save a UTF-8 copy and import it.') from error
        if '\x00' in decoded:
            raise ValueError('Text file contains null bytes and cannot be read as plain text.')
        markup = ''.join(f'<p>{html.escape(line)}</p>' for line in decoded.splitlines())
        soup = BeautifulSoup(markup, 'lxml')
    else:
        # SEC's saved document wrapper is SGML, not part of the HTML page.
        # Feeding its unclosed metadata tags to the HTML sanitizer loses the body.
        if re.match(br'\s*<document\s*>', content, re.IGNORECASE):
            payload = re.search(br'<html\b', content, re.IGNORECASE)
            if payload:
                content = content[payload.start():]
        soup = BeautifulSoup(content, 'lxml')
        if soup.contains_replacement_characters:
            raise ValueError('HTML character encoding could not be read without losing text.')
        for tag in soup.find_all(['script', 'style', 'head', 'iframe', 'object',
                                  'embed', 'svg', 'math', 'template', 'noscript']):
            tag.decompose()
        for tag in soup.find_all('br'):
            tag.replace_with(NavigableString('\n'))
        for tag in soup.find_all('div'):
            if not tag.find(['p', 'div', 'table', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                tag.name = 'p'
    cleaned = _safe_html(str(soup))
    # Serialize the parsed sanitized tree, then sanitize once more so the saved
    # fragment and its reparsed citation tree have the same browser-safe structure.
    cleaned = _safe_html(str(BeautifulSoup(cleaned, 'lxml')))
    parsed = BeautifulSoup(cleaned, 'lxml')
    text, _, bounds = _walk(parsed)
    blocks = _blocks(parsed, text, bounds)
    if media_type == 'application/pdf':
        for block in blocks:
            block['partial'] = block['heading'] in partial_pages or block['text'].startswith('[Extraction notice:')
    return {'html': cleaned, 'canonical_text': text, 'blocks': blocks}


def _stored_path(data_dir: Path, relative: str) -> Path:
    value = Path(relative)
    if value.is_absolute() or len(value.parts) != 2 or value.parts[0] != 'documents':
        raise ValueError('Saved document path is outside the document folder.')
    if not re.fullmatch(r'[0-9a-f]{64}(?:\.html)?', value.name):
        raise ValueError('Saved document filename is not a content hash.')
    root = data_dir.resolve()
    directory = root / 'documents'
    candidate = directory / value.name
    for path in (directory, candidate):
        if path.is_symlink() or path.is_junction():
            raise ValueError('Saved document paths cannot use symbolic links or junctions.')
    if not candidate.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Saved document path escapes the document folder.')
    return candidate


def _write_immutable(data_dir: Path, content: bytes, *, cleaned=False) -> str:
    digest = hashlib.sha256(content).hexdigest()
    relative = f'documents/{digest}' + ('.html' if cleaned else '')
    path = _stored_path(data_dir, relative)
    try:
        with path.open('xb') as output:
            output.write(content)
    except FileExistsError:
        with path.open('rb') as existing:
            if hashlib.file_digest(existing, 'sha256').hexdigest() != digest:
                raise ValueError('A saved document file has changed; it was not overwritten.')
    return relative


def _summary(row) -> dict:
    fields = ('id', 'logical_document_id', 'name', 'filing_date', 'form_type',
              'original_sha256', 'text_hash', 'cleaner_version', 'media_type', 'processing_error')
    result = {name: row[name] for name in fields}
    result['searchable'] = bool(row['canonical_text']) and not row['processing_error']
    return result


def import_local(data_dir: Path, case_id: int, selected_path: Path, *,
                 cleaner_version: str | None = None) -> dict:
    """The bridge supplies a path selected by the operating-system file picker."""
    suffix = selected_path.suffix.lower()
    if suffix not in {'.html', '.htm', '.txt', '.pdf'}:
        raise ValueError('Choose an HTML, UTF-8 text or text-PDF file.')
    with selected_path.open('rb') as source:
        content = source.read(MAX_DOCUMENT_BYTES + 1)
    media_type = {'.txt': 'text/plain', '.pdf': 'application/pdf'}.get(suffix, 'text/html')
    return store_document(data_dir, case_id, content, selected_path.name, media_type,
                          cleaner_version=cleaner_version)


def store_document(data_dir: Path, case_id: int, content: bytes, name: str, media_type: str, *,
                   logical_document_id: str | None = None, metadata: dict | None = None,
                   cleaner_version: str | None = None) -> dict:
    """Save document bytes and source metadata without replacing earlier versions."""
    if media_type not in {'text/html', 'text/plain', 'application/pdf'}:
        raise ValueError('Only HTML, UTF-8 text and text-PDF documents can be imported.')
    if len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError(f'Document exceeds the {MAX_DOCUMENT_BYTES // (1024 * 1024)} MiB limit.')
    digest = hashlib.sha256(content).hexdigest()
    version = constants.PDF_CLEANER_VERSION if media_type == 'application/pdf' else CLEANER_VERSION
    if cleaner_version is not None:
        version = cleaner_version
    if not version.strip():
        raise ValueError('A cleaning version is required.')
    metadata_fields = ('source_url', 'filing_date', 'accession_number',
                       'form_type', 'exhibit_label', 'company_id')
    metadata = {} if metadata is None else metadata
    if set(metadata) - set(metadata_fields):
        raise ValueError('Document source metadata contains an unsupported field.')
    if metadata and logical_document_id is None:
        raise ValueError('Source metadata requires a logical document identity.')
    if logical_document_id is not None and not logical_document_id.strip():
        raise ValueError('A supplied logical document identity cannot be empty.')
    with db.DATA_LOCK, closing(db.connect(data_dir)) as connection:
        if not connection.execute('SELECT 1 FROM cases WHERE id = ?', (case_id,)).fetchone():
            raise ValueError('Case does not exist.')
        if logical_document_id is None:
            raw = connection.execute(
                'SELECT * FROM documents WHERE case_id = ? AND original_sha256 = ? '
                'AND cleaner_version IS NULL AND source_url IS NULL AND accession_number IS NULL',
                (case_id, digest),
            ).fetchone()
            logical_document_id = raw['logical_document_id'] if raw else str(uuid.uuid4())
        else:
            if connection.execute(
                'SELECT 1 FROM documents WHERE logical_document_id = ? AND case_id != ? LIMIT 1',
                (logical_document_id, case_id),
            ).fetchone():
                raise ValueError('This logical document identity belongs to another case.')
            raw = connection.execute(
                'SELECT * FROM documents WHERE logical_document_id = ? AND original_sha256 = ? '
                'AND cleaner_version IS NULL', (logical_document_id, digest),
            ).fetchone()
        if raw and raw['media_type'] != media_type:
            raise ValueError('These bytes were already imported in this case using a different file type.')
        path = _write_immutable(data_dir, content)
        if raw is None:
            with connection:
                cursor = connection.execute(
                    'INSERT INTO documents(logical_document_id, case_id, name, retrieved_at, '
                    'original_sha256, original_path, media_type, source_url, filing_date, '
                    'accession_number, form_type, exhibit_label, company_id) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (logical_document_id, case_id, name,
                     datetime.now(timezone.utc).isoformat(), digest, path, media_type,
                     *(metadata.get(field) for field in metadata_fields)),
                )
            raw = connection.execute('SELECT * FROM documents WHERE id = ?', (cursor.lastrowid,)).fetchone()
        existing = connection.execute(
            'SELECT * FROM documents WHERE logical_document_id = ? AND original_sha256 = ? '
            'AND cleaner_version = ?', (raw['logical_document_id'], digest, version),
        ).fetchone()
        if existing:
            return _summary(existing)
        try:
            result = clean(content, media_type)
            if not result['canonical_text'].strip():
                raise ValueError('No usable text was found. The original file is saved.')
            cleaned_path = _write_immutable(data_dir, result['html'].encode('utf-8'), cleaned=True)
            text_hash = hashlib.sha256(result['canonical_text'].encode('utf-8')).hexdigest()
            with connection:
                cursor = connection.execute(
                    'INSERT INTO documents(logical_document_id, case_id, name, retrieved_at, '
                    'original_sha256, original_path, media_type, cleaner_version, clean_html_path, '
                    'canonical_text, text_hash, source_url, filing_date, accession_number, '
                    'form_type, exhibit_label, company_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (raw['logical_document_id'], case_id, raw['name'], raw['retrieved_at'], digest,
                     path, media_type, version, cleaned_path, result['canonical_text'], text_hash,
                     *(raw[field] for field in metadata_fields)),
                )
                document_id = cursor.lastrowid
                for block in result['blocks']:
                    cursor = connection.execute(
                        'INSERT INTO blocks(document_id, heading, start_offset, end_offset, text, partial) '
                        'VALUES (?, ?, ?, ?, ?, ?)',
                        (document_id, block['heading'], block['start_offset'], block['end_offset'],
                         block['text'], int(block['partial'])),
                    )
                    connection.execute('INSERT INTO blocks_fts(rowid, heading, text) VALUES (?, ?, ?)',
                                       (cursor.lastrowid, block['heading'], block['text']))
                connection.execute('UPDATE documents SET processing_error = NULL WHERE id = ?', (raw['id'],))
        except Exception as error:
            logger.exception('Document processing failed for saved document %s.', raw['id'])
            with connection:
                connection.execute('UPDATE documents SET processing_error = ? WHERE id = ?',
                                   (str(error), raw['id']))
            return _summary(connection.execute('SELECT * FROM documents WHERE id = ?', (raw['id'],)).fetchone())
        return _summary(connection.execute('SELECT * FROM documents WHERE id = ?', (document_id,)).fetchone())


def list_documents(data_dir: Path, case_id: int) -> list[dict]:
    with closing(db.connect(data_dir)) as connection:
        rows = connection.execute(
            'SELECT d.* FROM documents d WHERE d.case_id = ? AND d.id = '
            '(SELECT MAX(v.id) FROM documents v WHERE v.logical_document_id = d.logical_document_id) '
            'ORDER BY d.id DESC', (case_id,),
        ).fetchall()
    return [_summary(row) for row in rows]


def search(data_dir: Path, case_id: int, query: str) -> list[dict]:
    phrase = query.strip()
    if not phrase:
        raise ValueError('Enter a word or phrase to search.')
    expression = '"' + phrase.replace('"', '""') + '"'
    with closing(db.connect(data_dir)) as connection:
        rows = connection.execute(
            'SELECT b.id, b.id AS block_id, b.document_id, d.name, b.heading, b.text, '
            'b.start_offset, b.end_offset, b.partial FROM blocks_fts '
            'JOIN blocks b ON b.id = blocks_fts.rowid JOIN documents d ON d.id = b.document_id '
            'WHERE blocks_fts MATCH ? AND d.case_id = ? AND d.id = '
            '(SELECT MAX(v.id) FROM documents v WHERE v.logical_document_id = d.logical_document_id '
            'AND v.canonical_text IS NOT NULL) ORDER BY bm25(blocks_fts), b.id LIMIT ?',
            (expression, case_id, MAX_SEARCH_RESULTS),
        ).fetchall()
    return [{**dict(row), 'partial': bool(row['partial'])} for row in rows]


def _fact_ranges(text, hit, phrases, tables, limit):
    """Select exact source slices, keeping large-table headers separately."""
    start, end = hit['start_offset'], hit['end_offset']
    positions = []
    terms = [term for query in phrases for term in (re.findall(r'"([^"]+)"', query) or [query])]
    for phrase in terms:
        words = re.findall(r'\w+', phrase)
        pattern = r'\W+'.join(re.escape(word) for word in words)
        match = re.search(pattern, text[start:end], re.IGNORECASE) if pattern else None
        if match:
            positions.append(start + match.start())
    if not positions:
        raise ValueError('A search-index hit does not match its saved text. Retrieval was stopped.')
    anchor = min(positions)
    table = next((value for value in tables if value['start'] <= anchor < value['end']), None)
    ranges, notes = [], []
    neighbour = constants.FACT_NEIGHBOUR_CHARS
    from_caption = False
    if table is None and end - start <= neighbour:
        following = next((value for value in tables if end <= value['start'] <= end + neighbour
                          and re.search(r'[A-Za-z]', text[value['start']:value['end']])), None)
        # A prose mention of financial statements is not a table caption: keep
        # that paragraph rather than jumping to an unrelated following table.
        if following and re.search(r'\b(statements? of (?:operations|(?:comprehensive )?income|'
                                   r'earnings|cash flows)|balance sheets?)\s*$', hit['text'], re.IGNORECASE):
            table, from_caption = following, True
    if table:
        table_start, table_end = table['start'], table['end']
        if table_end - table_start <= limit:
            start = max(0, table_start - min(neighbour, limit - (table_end - table_start)))
            ranges.append((start, table_end, False))
        else:
            header_budget = min(constants.FACT_TABLE_HEADER_CHARS, limit // 2)
            # Reserve caption context before selecting header rows; otherwise a
            # final length clamp could silently discard the entity and units.
            header_start = max(0, table_start - min(neighbour, header_budget // 3))
            header_room = header_budget - (table_start - header_start)
            header_end = max((right for left, right in table['rows'] if right - table_start <= header_room), default=table_start)
            if header_end == table_start:
                header_end = min(table_end, table_start + header_room)
                notes.append('The table opening exceeds its context allowance and is partial.')
            ranges.append((header_start, header_end, True))
            remaining = limit - (header_end - header_start)
            start = header_end if from_caption else max(table_start, anchor - remaining // 3)
            end = min(table_end, start + remaining)
            left_row = next((left for left, right in table['rows'] if left <= start < right), start)
            right_row = next((right for left, right in table['rows'] if left < end <= right), end)
            if right_row - left_row <= remaining:
                start, end = left_row, right_row
            ranges.append((start, end, True))
            notes.append('A large table is only partly supplied; the table opening is separate context and later headers may be omitted.')
            if not table['has_header']:
                notes.append('The table has no explicit column-header cells; its opening rows are supplied without inferred labels.')
    else:
        left, right = max(0, start - neighbour), min(len(text), end + neighbour)
        if right - left <= limit:
            start, end = left, right
        elif end - start <= limit:
            # Keep the complete matching paragraph before allocating neighbours;
            # anchoring on a late term can otherwise discard its earlier figures.
            start = max(left, start - (limit - (end - start)) // 2)
            end = min(right, start + limit)
        else:
            start = max(left, anchor - limit // 3)
            end = min(right, start + limit)
        partial = start > hit['start_offset'] or end < hit['end_offset']
        ranges.append((start, end, partial))
        if partial:
            notes.append('A matching text block was shortened to the context allowance.')
    for index, (start, end, partial) in enumerate(ranges):
        if not partial and any(table['start'] < end and table['end'] > start
                               and not (start <= table['start'] and end >= table['end']) for table in tables):
            ranges[index] = (start, end, True)
            notes.append('Neighbouring table context is partial; do not infer omitted rows or column labels.')
    return ranges, notes


def retrieve_fact_passages(data_dir: Path, case_id: int, document_id: int,
                           queries: dict[str, tuple[str, ...]]) -> dict:
    """Search one selected immutable version; never repair its index as a side effect."""
    if not queries or any(not phrases or any(not isinstance(value, str) or not value.strip()
                                             for value in phrases) for phrases in queries.values()):
        raise ValueError('Each fact key requires nonempty fixed search phrases.')
    budgets = {key: (constants.FACT_FINANCIAL_RETRIEVAL_CHARS if key in constants.FACT_FINANCIAL_KEYS
                     else constants.FACT_RETRIEVAL_CHARS) for key in queries}
    return _retrieve_passages(data_dir, case_id, document_id, queries, budgets,
                              constants.FACT_RETRIEVAL_HITS)


def retrieve_question_passages(data_dir: Path, case_id: int, document_id: int, question: str) -> dict:
    """Retrieve literal question words from one selected version, without model rewriting."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError('Enter a question before retrieving evidence.')
    words = list(dict.fromkeys(word for word in re.findall(r'[^\W_]+', question.casefold())
                               if word not in constants.QUESTION_STOP_WORDS))
    # Every token is quoted: user punctuation and FTS operators are never executed.
    terms = tuple('"' + word + '"' for word in words[:constants.QUESTION_RETRIEVAL_TERMS])
    result = _retrieve_passages(data_dir, case_id, document_id, {'question': terms},
                               {'question': constants.QUESTION_RETRIEVAL_CHARS},
                               constants.QUESTION_RETRIEVAL_PASSAGES,
                               constants.QUESTION_RETRIEVAL_PASSAGES)
    result.pop('key_passages')
    result['searches'] = list(terms)
    if len(words) > constants.QUESTION_RETRIEVAL_TERMS:
        result['warnings'].append('Only the first bounded set of distinct searchable question words was used.')
    if not terms:
        result['warnings'].append('The question contains no searchable words after removing common question words.')
    result['warnings'].append('Question words are searched literally with OR; wording that differs from the filing can miss evidence.')
    return result


def retrieve_summary_passages(data_dir: Path, case_id: int, document_id: int) -> dict:
    """Opening context plus bounded full-text searches in one immutable source."""
    limit = min(constants.SUMMARY_MAX_CHARS, constants.SUMMARY_DOCUMENT_CHARS)
    with closing(db.connect(data_dir)) as connection:
        row = connection.execute('SELECT canonical_text FROM documents WHERE id=? AND case_id=?',
                                 (document_id, case_id)).fetchone()
    if row is None or not row[0]:
        raise ValueError('The selected document has no searchable text.')
    text = row[0]
    opening_end = min(len(text), limit, limit if len(text) <= limit else constants.SUMMARY_OPENING_CHARS)
    if opening_end < len(text):
        boundary = text.rfind('\n', opening_end * 4 // 5, opening_end)
        if boundary > 0:
            opening_end = boundary
    queries = constants.SUMMARY_QUERIES if len(text) > limit else {}
    budget = (limit - opening_end) // len(queries) if queries else 0
    if not budget:
        queries = {}
    result = _retrieve_passages(data_dir, case_id, document_id, queries,
                               {key: budget for key in queries}, 2)
    opening = {'id': 1, 'document_id': document_id, 'start_offset': 0,
               'end_offset': opening_end, 'text': text[:opening_end],
               'heading': 'Opening context', 'partial': opening_end < len(text)}
    passages = [opening] + [value for value in result['passages'] if value['end_offset'] > opening_end]
    for identity, passage in enumerate(passages, 1):
        passage['id'] = identity
    if sum(len(value['text']) for value in passages) > limit:
        raise ValueError('Retrieved briefing passages exceed the input allowance; no request was sent.')
    result['passages'] = passages
    result.pop('key_passages')
    if len(text) <= limit:
        result['warnings'] = ['The complete searchable text was supplied. Images and material absent from extracted text were not reviewed.']
    else:
        result['warnings'].append('Opening context and fixed searches can miss important material. Supplied character counts include any overlapping passages.')
    if result['source']['cleaner_version'].startswith('pdf-'):
        result['warnings'].append('PDF page labels are application locators. Text extraction can lose columns, tables and images; check financial figures against the original PDF.')
        notices = re.findall(r'\[Extraction notice:[^\]]*\]', text)
        result['warnings'].extend(dict.fromkeys(notices))
    return result


def _retrieve_passages(data_dir, case_id, document_id, queries, budgets, hit_limit, passage_limit=None):
    """Shared selected-version checks and canonical context for facts and questions."""
    with closing(db.connect(data_dir)) as connection:
        row = connection.execute('SELECT * FROM documents WHERE id = ? AND case_id = ?',
                                 (document_id, case_id)).fetchone()
        if row is None:
            raise ValueError('The selected document version does not belong to this case.')
        if not row['canonical_text'] or row['processing_error'] or not row['text_hash']:
            raise ValueError('The selected document has no verified searchable text.')
        blocks = connection.execute('SELECT * FROM blocks WHERE document_id = ? ORDER BY start_offset, id',
                                    (document_id,)).fetchall()
        if not blocks:
            raise ValueError('The selected document has no search blocks; its index was not rebuilt.')
        text = row['canonical_text']
        for block in blocks:
            start, end = block['start_offset'], block['end_offset']
            if not 0 <= start < end <= len(text) or block['text'] != text[start:end]:
                raise ValueError('Saved search blocks disagree with the selected canonical text.')
        # FTS external-content row counts read the content table even when its index
        # is empty. The temporary vocabulary reads actual index entries instead.
        try:
            connection.execute("CREATE VIRTUAL TABLE temp.fact_index_terms USING fts5vocab(main, 'blocks_fts', 'instance')")
            indexed = {value[0] for value in connection.execute(
                "SELECT DISTINCT v.doc FROM fact_index_terms v JOIN blocks b ON b.id = v.doc "
                "WHERE v.col = 'text' AND b.document_id = ?", (document_id,))}
        except sqlite3.DatabaseError:
            raise ValueError('The document search index is unavailable; it was not rebuilt.') from None
        if any(block['id'] not in indexed and any(char.isalnum() for char in block['text']) for block in blocks):
            raise ValueError('The selected document search index is incomplete; it was not rebuilt.')
        hits = {}
        searches = {key: list(phrases) for key, phrases in queries.items()}
        for key, phrases in queries.items():
            if not phrases:
                hits[key] = []
                continue
            expressions = [value if value.startswith('"') else '"' + value.replace('"', '""') + '"' for value in phrases]
            expression = 'text : (' + ' OR '.join('(' + value + ')' for value in expressions) + ')'
            hits[key] = connection.execute(
                'SELECT b.* FROM blocks_fts JOIN blocks b ON b.id = blocks_fts.rowid '
                'WHERE blocks_fts MATCH ? AND b.document_id = ? '
                'ORDER BY bm25(blocks_fts), b.id LIMIT ?',
                (expression, document_id, hit_limit),
            ).fetchall()
        source = {key: row[key] for key in ('name', 'cleaner_version', 'text_hash', 'original_sha256',
                                            'filing_date', 'accession_number')}
    document = read_document(data_dir, document_id)
    soup = BeautifulSoup(document['html'], 'lxml')
    walked, _, bounds = _walk(soup)
    if walked != text:
        raise ValueError('The cleaned document no longer matches its selected text version.')
    tables = []
    for tag in soup.find_all('table'):
        if tag.find_parent('table') is not None:
            continue
        start, end = bounds[id(tag)]
        rows = [bounds[id(value)] for value in tag.find_all('tr') if value.find_parent('table') is tag]
        tables.append({'start': start, 'end': end, 'rows': rows,
                       'has_header': tag.find(['thead', 'th']) is not None})
    passages, by_range, key_passages, warnings = [], {}, {}, []
    for key, found in hits.items():
        key_passages[key] = []
        if not found:
            warnings.append(key + ': no matching indexed text was found for the fixed searches; absence from the filing is not established.')
            continue
        for hit in found:
            ranges, notes = _fact_ranges(text, hit, queries[key], tables, budgets[key] // len(found))
            warnings.extend(key + ': ' + note for note in notes)
            prepared = []
            for start, end, partial in ranges:
                while start < end and text[start].isspace():
                    start += 1
                while end > start and text[end - 1].isspace():
                    end -= 1
                if start == end:
                    continue
                prepared.append((start, end, partial))
            new_ranges = {(start, end) for start, end, _ in prepared if (start, end) not in by_range}
            if passage_limit is not None and len(passages) + len(new_ranges) > passage_limit:
                warnings.append('The passage limit omitted a search hit and its context; separate table headers were not detached from their rows.')
                continue
            for start, end, partial in prepared:
                identity = (start, end)
                if identity not in by_range:
                    by_range[identity] = len(passages) + 1
                    passages.append({'id': by_range[identity], 'document_id': document_id,
                                     'start_offset': start, 'end_offset': end, 'text': text[start:end],
                                     'heading': hit['heading'], 'partial': partial})
                elif partial:
                    passages[by_range[identity] - 1]['partial'] = True
                if by_range[identity] not in key_passages[key]:
                    key_passages[key].append(by_range[identity])
    source.update(document_id=document_id, total_chars=len(text))
    warnings.append('Fixed-phrase retrieval searches the selected version, but supplies only bounded matching passages; unretrieved material has not been analysed.')
    return {'source': source, 'passages': passages, 'key_passages': key_passages,
            'searches': searches, 'warnings': list(dict.fromkeys(warnings))}


def _normalise(value: str) -> tuple[str, list[tuple[int, int]]]:
    characters, positions = [], []
    for index, character in enumerate(value):
        if character.isspace():
            if characters and characters[-1] == ' ':
                positions[-1] = (positions[-1][0], index + 1)
            else:
                characters.append(' ')
                positions.append((index, index + 1))
        else:
            characters.append(character)
            positions.append((index, index + 1))
    if characters and characters[-1] == ' ':
        characters.pop()
        positions.pop()
    if characters and characters[0] == ' ':
        characters.pop(0)
        positions.pop(0)
    return ''.join(characters), positions


def match_quote(text: str, quote: str, start_offset: int = 0,
                end_offset: int | None = None) -> tuple[int, int]:
    end_offset = len(text) if end_offset is None else end_offset
    if not 0 <= start_offset <= end_offset <= len(text):
        raise ValueError('Citation context offsets are outside the saved text.')
    normalised, positions = _normalise(text[start_offset:end_offset])
    expected, _ = _normalise(quote)
    if not expected:
        raise ValueError('Enter a nonempty quote to match.')
    first = normalised.find(expected)
    if first < 0:
        raise ValueError('Quote was not found in the supplied document context; it remains unresolved.')
    if normalised.find(expected, first + 1) >= 0:
        raise ValueError('Quote is ambiguous in the supplied context; select a block or provide more text.')
    return (start_offset + positions[first][0],
            start_offset + positions[first + len(expected) - 1][1])


def _highlight(clean_html: str, text: str, start: int, end: int) -> str:
    soup = BeautifulSoup(clean_html, 'lxml')
    walked, spans, _ = _walk(soup)
    if walked != text:
        raise ValueError('Saved HTML no longer matches its canonical text; highlighting is unavailable.')
    for node, node_start, node_end, source_start in spans:
        left, right = max(start, node_start), min(end, node_end)
        if left >= right or not str(node).strip():
            continue
        value = str(node)
        first = source_start + left - node_start
        last = source_start + right - node_start
        mark = soup.new_tag('mark')
        mark.string = value[first:last]
        node.replace_with(NavigableString(value[:first]), mark, NavigableString(value[last:]))
    highlighted = _safe_html(str(soup), marks=True)
    if canonical_text(highlighted) != text:
        raise ValueError('Highlighting changed the saved text and was rejected.')
    return highlighted


def read_document(data_dir: Path, document_id: int, block_id: int | None = None,
                  quote: str | None = None) -> dict:
    with closing(db.connect(data_dir)) as connection:
        row = connection.execute('SELECT * FROM documents WHERE id = ?', (document_id,)).fetchone()
        if row is None:
            raise ValueError('Document does not exist.')
        if row['clean_html_path'] is None:
            raise ValueError(row['processing_error'] or 'This document has no cleaned text.')
        block = None
        if block_id is not None:
            block = connection.execute('SELECT * FROM blocks WHERE id = ? AND document_id = ?',
                                       (block_id, document_id)).fetchone()
            if block is None:
                raise ValueError('The selected block does not belong to this document version.')
    path = _stored_path(data_dir, row['clean_html_path'])
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != path.stem:
        raise ValueError('Saved clean HTML failed its hash check.')
    text = row['canonical_text']
    if hashlib.sha256(text.encode('utf-8')).hexdigest() != row['text_hash']:
        raise ValueError('Saved canonical text failed its hash check.')
    cleaned = content.decode('utf-8')
    if _safe_html(cleaned) != cleaned or canonical_text(cleaned) != text:
        raise ValueError('Saved clean HTML cannot be safely displayed with its saved text version.')
    citation = None
    if quote is not None:
        start, end = match_quote(text, quote, block['start_offset'] if block else 0,
                                 block['end_offset'] if block else len(text))
        citation = {'document_id': document_id, 'document_hash': row['original_sha256'],
                    'text_version_id': document_id, 'start_offset': start, 'end_offset': end,
                    'quote': text[start:end], 'status': 'quote matched'}
        cleaned = _highlight(cleaned, text, start, end)
    elif block:
        cleaned = _highlight(cleaned, text, block['start_offset'], block['end_offset'])
    return {**_summary(row), 'html': cleaned, 'canonical_text': text, 'citation': citation}


def read_citation(data_dir: Path, citation: dict) -> dict:
    """Reopen saved evidence by its immutable offsets, without rematching words."""
    if citation['document_id'] != citation['text_version_id']:
        raise ValueError('Saved citation document and text-version identities disagree.')
    result = read_document(data_dir, citation['document_id'])
    if citation['document_hash'] != result['original_sha256']:
        raise ValueError('Saved citation document hash does not match its document.')
    text = result['canonical_text']
    start, end = citation['start_offset'], citation['end_offset']
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise ValueError('Saved citation offsets are outside its document text.')
    if citation['quote'] != text[start:end] or citation['status'] != 'quote matched':
        raise ValueError('Saved citation does not match the exact text at its saved offsets.')
    result['html'] = _highlight(result['html'], text, start, end)
    result['citation'] = dict(citation)
    return result


def original_path(data_dir: Path, document_id: int) -> Path:
    with closing(db.connect(data_dir)) as connection:
        row = connection.execute('SELECT original_path, original_sha256 FROM documents WHERE id = ?',
                                 (document_id,)).fetchone()
    if row is None:
        raise ValueError('Document does not exist.')
    path = _stored_path(data_dir, row['original_path'])
    with path.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != row['original_sha256']:
            raise ValueError('Saved original failed its hash check.')
    return path
