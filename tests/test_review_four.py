"""Amendments 7-12 and review-4 regressions. No live services."""
import copy
import csv
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from refclass.quality import GateError, decision_date, acceptance_time, source_excerpt
from refclass.profile import verify_profile
from refclass.pipeline import assemble
from refclass.review import prepare, reconcile, seal, verify_event_review
from refclass.collectors import ibkr
from refclass.engine import build
from refclass.publication import check
from refclass.bars import request
from tests.support import ROOT


class ReviewFourTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'deals/test'
        (self.root / 'filings').mkdir(parents=True)
        self.source = self.root / 'filings/source.txt'
        self.ev = dict(source=str(self.source), line_start=1, line_end=1)

    def test_profile_exact_numbers_scientific_currency_date_and_candidate(self):
        profile = dict(self.ev, as_of='2026-10-04', first_product=True, market_value=300000000,
                       market_value_evidence=dict(self.ev, currency='USD', as_of='2026-10-04'))
        self.source.write_text('We have no approved products. Market value USD 1300000000 on 2026-10-04.')
        with self.assertRaises(GateError): verify_profile(profile, self.root)
        profile['market_value'] = 1.2e9
        self.source.write_text('We have no approved products. Market value USD 1.2e9 on 2026-10-04.')
        verify_profile(profile, self.root)
        for text in ('Our first product candidate. Market value USD 1.2e9 on 2026-10-04.',
                     'We have no approved products. Market value GBP 1.2e9 on 2026-10-04.',
                     'We have no approved products. Market value USD 1.2e9 on 2026-09-04.'):
            self.source.write_text(text)
            with self.assertRaises(GateError): verify_profile(profile, self.root)

    def test_dates_only_structured_and_wrong_field_rejected(self):
        for text in ('On November 20, 2026, the U.S. Food and Drug Administration (FDA) approved X.',
                     'FDA approved X on March 3, 2026, ahead of its PDUFA date of November 20, 2026.'):
            self.source.write_text(text)
            with self.assertRaises(GateError): decision_date('fda_action', '2026-11-20', self.ev)
        self.source.write_text(json.dumps(dict(action=dict(submission_status='AP', submission_type='ORIG',
                                                           submission_status_date='20261120'))))
        evidence = dict(source=str(self.source), pointer='/action/submission_status_date')
        decision_date('fda_action', '2026-11-20', evidence)
        with self.assertRaises(GateError): decision_date('fda_action', '2026-03-03', evidence)
        self.source.write_text(self.source.read_text().replace('ORIG', 'SUPPL'))
        with self.assertRaises(GateError): decision_date('fda_action', '2026-11-20', evidence)

    def test_acceptance_timezone_and_index_and_wrong_form(self):
        self.source.write_text(json.dumps(dict(recent=dict(form=['8-K'], acceptanceDateTime=['2026-09-01T12:00:00Z']))))
        ev = dict(source=str(self.source), pointer='/recent', index=0)
        acceptance_time('2026-09-01T08:00:00-04:00', ev)
        with self.assertRaises(GateError): acceptance_time('2026-09-01T09:00:00-04:00', ev)
        self.source.write_text(self.source.read_text().replace('8-K', '10-Q'))
        with self.assertRaises(GateError): acceptance_time('2026-09-01T08:00:00-04:00', ev)

    def test_raw_root_and_symlink_boundary(self):
        raw = ROOT / 'data/refclass/raw'
        raw.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=raw) as tmp:
            path = Path(tmp) / 'sample'; path.write_text('primary')
            self.assertEqual(source_excerpt(dict(source=str(path), line_start=1, line_end=1)), 'primary')
            outside = Path(self.tmp.name) / 'draft'; outside.write_text('model output')
            link = Path(tmp) / 'escape'; link.symlink_to(outside)
            with self.assertRaises(GateError): source_excerpt(dict(source=str(link), line_start=1, line_end=1))

    def test_ibkr_large_file_reads_are_bounded(self):
        bar = dict(provider='IBKR', ticker='TEST', date='2026-09-01', close=10.0,
                   adjusted_close=10.0, adjustment='split_only')
        self.source.write_text('\n'.join(json.dumps(dict(bar, ticker=f'T{i}')) for i in range(1000)))
        reads = []
        original = Path.read_text
        def read(path, *a, **kw):
            reads.append(path); return original(path, *a, **kw)
        with patch.object(Path, 'read_text', read):
            result = ibkr.collect(self.source, tickers=[f'T{i}' for i in range(1000)], since='2026-01-01', until='2026-10-04')
        self.assertEqual(len(result['prices']), 1000)
        self.assertLessEqual(len(reads), 3)

    def test_partition_coverage_survives_assembly_and_update(self):
        paths = []
        for n in range(2):
            path = Path(self.tmp.name) / f'{n}.json'
            path.write_text(json.dumps(dict(source='drugs_at_fda', complete=True, scope=dict(partition=n), candidates=[])))
            paths.append(path)
        snapshot = assemble(dict(as_of='2026-10-04'), paths)
        self.assertEqual(len(snapshot['coverage']['drugs_at_fda']), 2)
        db = Path(self.tmp.name) / 'db'
        build(db, assemble(dict(as_of='2026-10-04'), paths[:1]), ROOT / 'knowledge')
        result = build(db, assemble(dict(as_of='2026-10-04'), paths[1:]), ROOT / 'knowledge', update=True)
        self.assertEqual(len(result['coverage']['drugs_at_fda']), 2)

    def test_tender_dividend_and_invalid_residual_only_warn(self):
        from tests.test_amendments import calc
        baseline = json.loads((ROOT / 'tests/fixtures/legacy-baseline.json').read_text())
        row = next(r for r in baseline['cases'] if r['label'] == 'partial tender')
        data = copy.deepcopy(row['input'])
        data['dividends_to_close'] = [dict(who='target', amount=1)]
        data['tender']['back_end_prices'] = {'invalid': -1}
        with redirect_stderr(io.StringIO()) as err:
            calc.compute(data, row['prices'])
        self.assertIn('Residual', err.getvalue())

    def test_review_agreement_disagreement_and_source_changes(self):
        self.source.write_text('Primary evidence for exclusion.')
        candidate = dict(candidate_id='fda:one', event_type='approval', application='NDA123456',
                         source=str(self.source), locator='L.1', action_date='2026-09-01', company='Company')
        collection = Path(self.tmp.name) / 'collected.json'
        collection.write_text(json.dumps(dict(source='drugs_at_fda', complete=True, candidates=[candidate])))
        folder = Path(self.tmp.name) / 'review'
        snapshot = prepare([collection], folder)
        event = dict(snapshot['event_drafts'][0], ticker='TEST', announced_at='2026-09-01',
                     review_evidence=self.ev, press_release_conflict=False)
        paths = [folder / 'one.csv', folder / 'two.csv']
        def write(path, decision, payload):
            with path.open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['candidate_id', 'decision', 'event_json', 'reason'])
                writer.writeheader(); writer.writerow(dict(candidate_id='fda:one', decision=decision,
                                                          event_json=json.dumps(payload), reason='Reviewed'))
        for path in paths: write(path, 'exclude', event)
        self.assertEqual(reconcile(folder / 'candidates.json', paths, folder), 0)
        reviewed = json.loads((folder / 'reviewed.json').read_text())
        accepted = reviewed['events'][0]; verify_event_review(accepted)
        db = Path(self.tmp.name) / 'db'
        result = build(db, reviewed, ROOT / 'knowledge')
        check(db, result)
        self.source.write_text('Changed primary evidence.')
        with self.assertRaises(GateError): check(db, result)
        write(paths[1], 'include', event)
        self.assertEqual(reconcile(folder / 'candidates.json', paths, folder), 1)
        self.assertIn('fda:one', (folder / 'disagreements.csv').read_text())

    def test_saved_broker_tool_transcript_and_assistant_fabrication(self):
        from refclass.bars import transcript_bars
        sample = ROOT / 'tests/fixtures/ibkr-tool-sample.jsonl'
        rows = transcript_bars(sample, 'ibkr')
        self.assertEqual(rows[0]['close'], 10)
        self.assertEqual(rows[0]['broker_response']['bars'][0]['date'], '2026-09-01')
        self.source.write_text(json.dumps(dict(type='assistant', message=dict(content=[
            dict(type='text', text=json.dumps(rows[0]))]))))
        with self.assertRaisesRegex(ValueError, 'No historical'): transcript_bars(self.source, 'ibkr')
        self.source.write_text(sample.read_text().replace('split_only', 'dividend_adjusted'))
        with self.assertRaisesRegex(ValueError, 'both close conventions'): transcript_bars(self.source, 'ibkr')

    def test_fetch_request_bounds_and_xbi(self):
        self.assertEqual(request(['VRNA'], '2024-06-01', '2024-07-01')['tickers'], ['VRNA', 'XBI'])
        for tickers, since, until in [(['BAD;'], '2024-01-01', '2025-01-01'), (['VRNA'], '2025-01-01', '2024-01-01')]:
            with self.assertRaises(ValueError): request(tickers, since, until)
