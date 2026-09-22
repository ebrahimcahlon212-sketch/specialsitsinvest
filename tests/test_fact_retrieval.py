"""Saved real Sandisk filing and labelled synthetic structural retrieval checks."""

from contextlib import closing
from pathlib import Path

import pytest

from app import constants, db, documents


@pytest.fixture
def research(tmp_path):
    data = tmp_path / 'isolated-data'
    db.initialize(data)
    with closing(db.connect(data)) as connection, connection:
        connection.executemany('INSERT INTO cases(id,title,created_at) VALUES (?,?,?)',
                               [(1, 'Synthetic retrieval case', 'synthetic-date'),
                                (2, 'Other synthetic case', 'synthetic-date')])
    return data


def save(data, text, *, case_id=1, logical='synthetic-document', version='synthetic-1', metadata=None):
    return documents.store_document(data, case_id, text.encode(), 'Synthetic document', 'text/html',
                                    logical_document_id=logical, cleaner_version=version, metadata=metadata)


def joined(result, key):
    selected = set(result['key_passages'][key])
    return '\n'.join(value['text'] for value in result['passages'] if value['id'] in selected)


def assert_ranges(data, document_id, result):
    canonical = documents.read_document(data, document_id)['canonical_text']
    for passage in result['passages']:
        assert passage['document_id'] == document_id
        assert passage['text'] == canonical[passage['start_offset']:passage['end_offset']]
    for key, ids in result['key_passages'].items():
        limit = constants.FACT_FINANCIAL_RETRIEVAL_CHARS if key in constants.FACT_FINANCIAL_KEYS else constants.FACT_RETRIEVAL_CHARS
        assert sum(len(p['text']) for p in result['passages'] if p['id'] in ids) <= limit


def test_selected_old_version_searches_beyond_opening_and_never_other_case(research):
    filler = '<p>Synthetic irrelevant opening paragraph.</p>' * 1600
    markup = filler + '<h2>Distribution terms</h2><p>Synthetic record date is [blank].</p>'
    old = save(research, markup)
    save(research, '<p>Synthetic record date is December 31.</p>', version='synthetic-2')
    save(research, '<p>Synthetic record date is January 1.</p>', case_id=2, logical='other-case')
    result = documents.retrieve_fact_passages(research, 1, old['id'], {'record_date': ('record date',)})
    assert '[blank]' in joined(result, 'record_date')
    assert 'December' not in joined(result, 'record_date') and 'January' not in joined(result, 'record_date')
    assert min(value['start_offset'] for value in result['passages']) > 40_000
    assert result['source']['filing_date'] is None and result['source']['accession_number'] is None
    assert_ranges(research, old['id'], result)


def test_partial_table_keeps_actual_entity_units_periods_and_exact_offsets(research):
    rows = ''.join('<tr><td>Synthetic unrelated row ' + str(index) + ' ' + 'context ' * 10 + '</td><td>1</td><td>2</td></tr>'
                   for index in range(350))
    markup = ('<h2>Synthetic Spinco A pro forma statement</h2><p>All amounts in USD millions.</p>'
              '<table><thead><tr><th>Metric</th><th>Year ended June 2024</th><th>Year ended June 2023</th></tr></thead>'
              + rows + '<tr><td>Synthetic net revenue</td><td>125</td><td>100</td></tr></table>')
    saved = save(research, markup)
    result = documents.retrieve_fact_passages(research, 1, saved['id'], {'pro_forma_revenue': ('net revenue',)})
    text = joined(result, 'pro_forma_revenue')
    assert all(value in text for value in ('Spinco A', 'USD millions', 'June 2024', 'June 2023', 'net revenue', '125', '100'))
    assert len(result['passages']) >= 2 and any(value['partial'] for value in result['passages'])
    assert any('large table' in value for value in result['warnings'])
    assert_ranges(research, saved['id'], result)


def test_missing_terms_are_reported_without_false_index_failure(research):
    saved = save(research, '<p>Synthetic distribution date is unknown.</p>')
    result = documents.retrieve_fact_passages(research, 1, saved['id'], {'pro_forma_ebitda': ('EBITDA',)})
    assert result['passages'] == [] and result['key_passages']['pro_forma_ebitda'] == []
    assert result['searches'] == {'pro_forma_ebitda': ['EBITDA']}
    assert any('absence from the filing is not established' in value for value in result['warnings'])


def test_complete_matching_paragraph_precedes_neighbour_context(research):
    markup = ''.join('<p>Synthetic amount ' + str(index) + ': ' + 'earlier context ' * 80
                     + 'The record date is unknown.</p><p>' + 'Unrelated neighbour. ' * 150 + '</p>'
                     for index in range(3))
    saved = save(research, markup)
    result = documents.retrieve_fact_passages(research, 1, saved['id'], {'record_date': ('record date',)})
    text = joined(result, 'record_date')
    assert all('Synthetic amount ' + str(index) + ':' in text for index in range(3))
    assert_ranges(research, saved['id'], result)


def test_prose_context_does_not_silently_present_adjacent_partial_table_as_complete(research):
    rows = '<tr><td>Synthetic long neighbour row ' + 'context ' * 80 + '</td><td>10</td></tr>'
    saved = save(research, '<p>Synthetic record date is unknown.</p><table>' + rows * 20 + '</table>')
    result = documents.retrieve_fact_passages(research, 1, saved['id'], {'record_date': ('record date',)})
    assert any(value['partial'] for value in result['passages'])
    assert any('Neighbouring table context is partial' in value for value in result['warnings'])
    assert_ranges(research, saved['id'], result)


def test_pro_forma_caption_selects_following_table_with_financial_rows(research):
    rows = ''.join('<tr><td>Synthetic expense ' + str(index) + ' ' + 'context ' * 8 + '</td><td>10</td></tr>'
                   for index in range(80))
    markup = ('<p>UNAUDITED PRO FORMA CONDENSED COMBINED STATEMENT OF OPERATIONS</p>'
              '<p>Synthetic company. For the year ended 2024. USD millions.</p>'
              '<table><tr><th>Metric</th><th>Synthetic company pro forma</th></tr>'
              '<tr><td>Revenue, net</td><td>125</td></tr>' + rows[:rows.index('<tr><td>Synthetic expense 30 ')]
              + '<tr><td>Operating income</td><td>25</td></tr>' + rows + '</table>')
    saved = save(research, markup)
    result = documents.retrieve_fact_passages(research, 1, saved['id'],
                                             {'pro_forma_revenue': ('"pro forma" AND "statement of operations"',)})
    text = joined(result, 'pro_forma_revenue')
    assert all(value in text for value in ('USD millions', 'year ended 2024', 'Revenue, net', 'Operating income', '125', '25'))
    assert_ranges(research, saved['id'], result)


def test_fts_content_rows_do_not_disguise_missing_index_and_no_rebuild_occurs(research):
    saved = save(research, '<p>Synthetic record date is unknown.</p>')
    with closing(db.connect(research)) as connection, connection:
        connection.execute("INSERT INTO blocks_fts(blocks_fts) VALUES ('delete-all')")
        assert connection.execute('SELECT COUNT(*) FROM blocks_fts').fetchone()[0] > 0
    with pytest.raises(ValueError, match='index is incomplete'):
        documents.retrieve_fact_passages(research, 1, saved['id'], {'record_date': ('record date',)})
    with closing(db.connect(research)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM blocks_fts WHERE blocks_fts MATCH 'record'").fetchone()[0] == 0


def test_bad_blocks_missing_index_wrong_case_and_hash_damage_are_explicit(research):
    saved = save(research, '<p>Synthetic record date is unknown.</p>')
    with pytest.raises(ValueError, match='does not belong'):
        documents.retrieve_fact_passages(research, 2, saved['id'], {'record_date': ('record date',)})
    with closing(db.connect(research)) as connection, connection:
        connection.execute("UPDATE blocks SET text='Synthetic altered block' WHERE document_id=?", (saved['id'],))
    with pytest.raises(ValueError, match='blocks disagree'):
        documents.retrieve_fact_passages(research, 1, saved['id'], {'record_date': ('record date',)})
    other = save(research, '<p>Synthetic distribution date is unknown.</p>', logical='second')
    with closing(db.connect(research)) as connection:
        relative = connection.execute('SELECT clean_html_path FROM documents WHERE id=?', (other['id'],)).fetchone()[0]
    (research / relative).write_text('<p>Synthetic damaged saved file</p>')
    with pytest.raises(ValueError, match='hash check'):
        documents.retrieve_fact_passages(research, 1, other['id'], {'distribution_date': ('distribution date',)})
    with closing(db.connect(research)) as connection, connection:
        connection.execute('DROP TABLE blocks_fts')
    with pytest.raises(ValueError, match='index is unavailable'):
        documents.retrieve_fact_passages(research, 1, other['id'], {'distribution_date': ('distribution date',)})


def test_same_request_is_deterministic_and_shared_ranges_deduplicate(research):
    saved = save(research, '<h2>Synthetic terms</h2><p>The record date and distribution date remain unknown.</p>')
    queries = {'record_date': ('record date',), 'distribution_date': ('distribution date',)}
    first = documents.retrieve_fact_passages(research, 1, saved['id'], queries)
    assert first == documents.retrieve_fact_passages(research, 1, saved['id'], queries)
    assert first['key_passages']['record_date'] == first['key_passages']['distribution_date']
    assert len(first['passages']) == 1


def test_saved_real_sandisk_filing_retains_version_metadata_and_late_financial_context(research):
    fixture = Path(__file__).parent / 'fixtures' / 'sandisk_20241125_d835366dex991.htm'
    saved = documents.store_document(research, 1, fixture.read_bytes(), fixture.name, 'text/html',
        logical_document_id='saved-real-sandisk-20241125',
        metadata={'filing_date': '2024-11-25', 'accession_number': '0001193125-24-264578', 'exhibit_label': '99.1'})
    queries = {'record_date': ('record date',), 'pro_forma_revenue': ('net revenue', 'total revenues')}
    result = documents.retrieve_fact_passages(research, 1, saved['id'], queries)
    assert result['source']['filing_date'] == '2024-11-25'
    assert result['source']['accession_number'] == '0001193125-24-264578'
    assert 'record date' in joined(result, 'record_date').lower()
    assert any(p['start_offset'] > 40_000 for p in result['passages'] if p['id'] in result['key_passages']['pro_forma_revenue'])
    assert_ranges(research, saved['id'], result)


def test_saved_december_filing_has_conditions_award_rules_pensions_and_financial_headers(research):
    fixture = Path(__file__).parent / 'fixtures' / 'sandisk_20241220_d835366dex991.htm'
    saved = documents.store_document(research, 1, fixture.read_bytes(), fixture.name, 'text/html',
        logical_document_id='saved-real-sandisk-20241220',
        metadata={'filing_date': '2024-12-20', 'accession_number': '0001193125-24-283199', 'exhibit_label': '99.1'})
    keys = ('tax_free_condition', 'management_equity_awards', 'pension_and_other_liabilities',
            'pro_forma_revenue', 'pro_forma_operating_income', 'pro_forma_ebitda')
    result = documents.retrieve_fact_passages(research, 1, saved['id'],
                                             {key: constants.FACT_QUERIES[key] for key in keys})
    text = {key: ' '.join(joined(result, key).split()) for key in keys}
    assert 'WDC will have received the Tax Opinion from its tax counsel, Skadden' in text['tax_free_condition']
    assert 'This condition may be waived by WDC in its sole discretion.' in text['tax_free_condition']
    awards = text['management_equity_awards']
    assert 'will convert to both a WDC award and a Spinco award' in awards
    assert 'China, Israel, Malaysia, the Philippines or Thailand' in awards
    assert 'based on actual performance for completed fiscal years' in awards
    assert 'subject to only time-based vesting following the spin-off' in awards
    assert 'number of performance-adjusted WDC shares' in awards
    pensions = text['pension_and_other_liabilities']
    assert 'September 27, 2024, and June 28, 2024' in pensions
    assert 'net unfunded status of $7 million and $6 million, respectively' in pensions
    assert 'June 28, 2024, and June 30, 2023' in pensions
    assert 'net unfunded status of $6 million and $5 million, respectively' in pensions
    for key in ('pro_forma_revenue', 'pro_forma_operating_income'):
        assert 'UNAUDITED PRO FORMA CONDENSED COMBINED STATEMENT OF OPERATIONS' in text[key]
        assert 'The Flash Business of Western Digital Corporation' in text[key]
        assert 'For the three months ended September 27, 2024' in text[key]
        assert '(in millions, except per share amounts)' in text[key]
        assert 'Revenue, net $ 1,883' in text[key] and 'Operating income (loss)' in text[key]
    assert 'Pro Forma Historical Three months ended Year ended' in text['pro_forma_ebitda']
    assert 'EBITDA (10) 337 (338 )' in text['pro_forma_ebitda']
    assert result['source']['filing_date'] == '2024-12-20'
    assert result['source']['accession_number'] == '0001193125-24-283199'
    assert_ranges(research, saved['id'], result)
