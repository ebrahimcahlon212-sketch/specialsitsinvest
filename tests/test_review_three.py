"""Concrete regressions from review-3. Offline examples are not census evidence."""
from contextlib import redirect_stderr
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from tests.support import ROOT, bundle
from tests.test_collectors import fixture_client
from refclass.collectors import edgar, fda
from refclass.collectors.http import Client
from refclass.engine import build, report
from refclass.jobs import job_key
from refclass.background import launch
from refclass.pipeline import assemble
from refclass.publication import check, price_evidence
from refclass.quality import GateError, decision_date
from refclass.locking import job_lock


class ReviewThreeTests(unittest.TestCase):
    def test_date_wording_and_estimates(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'deals/test/filings/action.txt'
            source.parent.mkdir(parents=True)
            ev = dict(source=str(source), line_start=1, line_end=1)
            for when, text in [
                ('2026-11-20', '(FDA) approved the drug on November 20, 2026.'),
                ('2026-11-20', 'The FDA issued a complete response letter on November 20, 2026.'),
                ('2026-11-20', 'On November 20, 2026, the FDA approved the drug.'),
                ('2026-09-20', 'The FDA approved the drug on Sept. 20, 2026.'),
                ('2026-11-05', 'On November 05, 2026, the FDA approved the drug.')]:
                source.write_text(text)
                decision_date('fda_action', when, ev)
            for text in ['We plan to submit the NDA and anticipate an action date of November 20, 2026.',
                         'We expect a PDUFA target action date of November 20, 2026.',
                         'Submitted November 20, 2026. The FDA approved it on March 20, 2027.']:
                source.write_text(text)
                for kind in ('fda_goal', 'fda_action'):
                    with self.assertRaises(GateError): decision_date(kind, '2026-11-20', ev)

    def test_deal_writers_share_lock(self):
        for action in ('final', 'biotech', 'quotes', 'check', 'model'):
            self.assertEqual(job_key(['savara']), job_key(['savara', action]))

    def test_date_window_sent_to_fda_and_cber_gap(self):
        urls = []
        class Empty:
            def json(self, url):
                urls.append(url)
                return {'error': {'code': 'NOT_FOUND'}}, {}
        result = fda.collect(Empty(), 'drugs_at_fda', since='2015-01-01', until='2026-10-04', search='application_number:NDA*')
        query = parse_qs(urlsplit(urls[0]).query)['search'][0]
        self.assertIn('submissions.submission_status_date:[20150101 TO 20261004]', query)
        self.assertIn('(application_number:NDA*) AND', query)
        self.assertIn('CBER', ' '.join(result['coverage_gaps']))

    def test_bad_edgar_date_keeps_good_filings(self):
        client = fixture_client()
        original = client.json
        def json_(url):
            data, origin = original(url)
            data = copy.deepcopy(data)
            if 'filings' in data:
                data['filings']['recent']['filingDate'][0] = 'not a date'
            return data, origin
        client.json = json_
        result = edgar.collect(client, '1160308', since='2025-10-30', until='2025-10-30', max_history=0, max_exhibits=1)
        self.assertEqual(result['filing_count'], 1)
        self.assertIn('Invalid filingDate', ' '.join(result['gaps']))

    def test_two_clients_do_not_lose_manifest_entries(self):
        from tests.test_collectors import Response
        with tempfile.TemporaryDirectory() as tmp:
            one = Client(tmp, opener=lambda *a, **k: Response(b'{}'))
            two = Client(tmp, opener=lambda *a, **k: Response(b'{}'))
            one.get('https://api.fda.gov/one')
            two.get('https://api.fda.gov/two')
            self.assertEqual(len(json.loads((Path(tmp) / 'manifest.json').read_text())), 2)

    def test_pipeline_preserves_unreviewed_candidates_and_coverage_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'collection.json'
            p.write_text(json.dumps(dict(source='drugs_at_fda', complete=False, gaps=['bounded'],
                                        candidates=[dict(candidate_id='a', event_type='approval')],
                                        coverage_gaps=['CBER missing'])))
            snapshot = assemble(dict(as_of='2026-10-04', events=[]), [p])
            db = Path(tmp) / 'data.sqlite'
            result = build(db, snapshot, ROOT / 'knowledge')
            self.assertEqual(result['candidate_count'], 1)
            self.assertEqual(result['pending_candidates'], ['a'])
            self.assertEqual(result['eligible'], 0)
            self.assertIn('CBER missing', result['gaps'])
            updated = build(db, dict(as_of='2026-10-04'), ROOT / 'knowledge', update=True)
            self.assertEqual(updated['candidate_count'], 1)

    def test_renamed_synthetic_prices_do_not_pass_source_gate(self):
        data = bundle(); data['fixture'] = False
        for row in data['prices']: row['source'] = 'IBKR genuine historical data'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(GateError, 'saved IBKR bar'):
                build(Path(tmp) / 'data.sqlite', data, ROOT / 'knowledge')

    def test_primary_bar_reread_detects_changed_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'deals/test/filings/bars.jsonl'; p.parent.mkdir(parents=True)
            bar = dict(provider='IBKR', ticker='TEST', date='2026-09-01', close=10.0,
                       adjusted_close=10.0, adjustment='split_only')
            p.write_text(json.dumps(bar))
            row = {k: bar[k] for k in ('ticker', 'date', 'close', 'adjusted_close')}
            row['source'] = str(p) + '#L1'
            price_evidence(row)
            row['close'] = 11.0
            with self.assertRaises(GateError): price_evidence(row)

    def test_legacy_checks_warn_without_mutating_results(self):
        from tests.test_amendments import calc, catalysts
        baseline = json.loads((ROOT / 'tests/fixtures/legacy-baseline.json').read_text())
        import datetime
        for row in baseline['cases']:
            module = calc if row['module'] == 'calc' else catalysts
            with redirect_stderr(io.StringIO()) as err, patch.object(module, 'TODAY', datetime.date(2026, 10, 4)):
                actual = module.compute(row['input'], row['prices']) if module is calc else module.numbers(row['input'])
                self.assertEqual(json.loads(json.dumps(actual)), row['result'])
                if row['label'] in ('partial tender', 'extreme discount'):
                    self.assertIn('Warning.', err.getvalue())

    def test_actual_detached_build_finishes_and_releases_lock(self):
        # Launch the real worker with no network and wait/reap it in this test.
        # Only the log location is redirected to the temporary test directory.
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); db = p / 'data.sqlite'; source = p / 'input.json'
            source.write_text(json.dumps(dict(as_of='2026-10-04', events=[], prices=[], sessions=[])))
            processes = []
            real_popen = subprocess.Popen
            def start(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                processes.append(process)
                return process
            with patch('refclass.background.subprocess.Popen', side_effect=start):
                pid, log = launch(['build', '--input', str(source), '--db', str(db)], ROOT, p / 'logs')
            deadline = time.monotonic() + 10
            try:
                while 'Job finished.' not in log.read_text() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertIn('Job finished. Exit status 1.', log.read_text())
                self.assertTrue(db.exists())
                processes[0].wait(timeout=5)
                with job_lock(str(db) + '.job.lock'): pass
            finally:
                if processes[0].poll() is None:
                    processes[0].terminate()
                    processes[0].wait(timeout=5)

    def test_nonempty_legacy_renderers_match_pre_phase_one_snapshot(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'tests/legacy_render_contract.py'), str(ROOT / 'lib')],
                              capture_output=True, text=True, check=True)
        baseline = json.loads((ROOT / 'tests/fixtures/legacy-render-baseline.json').read_text())
        self.assertEqual(json.loads(proc.stdout), baseline)

    def test_ibkr_saved_bars_reuse_quote_reader_and_keep_xbi_gaps(self):
        from refclass.collectors import ibkr
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'deals/test/filings/bars.jsonl'; p.parent.mkdir(parents=True)
            bar = dict(provider='IBKR', ticker='TEST', date='2026-09-01', close=10.0,
                       adjusted_close=10.0, adjustment='split_only')
            p.write_text(json.dumps(bar) + '\n')
            result = ibkr.collect(p, tickers=['TEST'], since='2026-01-01', until='2026-10-04')
            self.assertEqual(len(result['prices']), 1)
            self.assertFalse(result['complete'])
            self.assertIn('XBI', ' '.join(result['gaps']))
            p.write_text(json.dumps(dict(ticker='TEST', price=10, time='2026-09-01')))
            self.assertEqual(ibkr.collect(p, tickers=['TEST'], since='2026-01-01', until='2026-10-04')['prices'], [])

    def test_inventory_reread_detects_omitted_periodic_filing(self):
        from refclass.inventory import verify
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'deals/test/filings/SEC.json'; p.parent.mkdir(parents=True)
            rows = dict(accessionNumber=['new'], filingDate=['2026-08-01'], form=['10-Q'], primaryDocument=['q.htm'])
            p.write_text(json.dumps(dict(tickers=['TEST'], filings=dict(recent=rows, files=[]))))
            event = dict(ticker='TEST', announced_at='2026-09-01', shares_as_of='2026-06-30', shares_source='q.htm',
                         inventory_sources=[dict(source=str(p))], share_filings=[dict(accessionNumber='old')])
            with self.assertRaisesRegex(GateError, 'latest SEC'):
                verify(event)
            event['share_filings'] = [dict(accessionNumber='new', filed_at='2026-08-01', source='q.htm')]
            verify(event)
            data = json.loads(p.read_text()); data['filings']['files'] = [dict(name='history.json')]
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(GateError, 'historical inventory'):
                verify(event)

    def test_strict_output_rechecks_sources_and_all_reaction_metrics(self):
        # Fabricated unit data exercises the production checks. It is not a
        # historical-price fixture or acceptance evidence.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'deals/test/filings'; root.mkdir(parents=True)
            source = root / 'event.txt'
            timestamp = '2026-09-02T08:00:00-04:00'
            source.write_text('TEST listed on NASDAQ.\nSponsor is applicant for Drug.\n'
                              'Sponsor has 10000000 shares outstanding.\n' + timestamp + '\n'
                              'The FDA approved Drug on September 2, 2026.\nFirst product yes.\n')
            def ev(n): return dict(source=str(source), line_start=n, line_end=n, locator=f'L.{n}')
            inv = root / 'SEC.json'
            inv.write_text(json.dumps(dict(tickers=['TEST'], filings=dict(recent=dict(
                accessionNumber=['q'], filingDate=['2026-08-01'], form=['10-Q'], primaryDocument=['q.htm']), files=[]))))
            event = dict(event_id='TEST', company='Sponsor', applicant='Sponsor', ticker='TEST', drug='Drug',
                         application='NDA', original=True, listed_us=True, event_type='approval',
                         announced_at=timestamp, source=str(source), locator='L.5',
                         listing_evidence=dict(ev(1), venue='NASDAQ', valid_from='2026-01-01', valid_through='2026-10-04'),
                         applicant_evidence=ev(2), shares=10000000, shares_as_of='2026-06-30', shares_source=str(source),
                         share_filings=[dict(ev(3), accessionNumber='q', filed_at='2026-08-01', as_of='2026-06-30', shares=10000000)],
                         inventory_sources=[dict(source=str(inv))], action_date='2026-09-02', action_evidence=ev(5),
                         announcement_evidence=ev(4), tags=[dict(ev(6), feature='first_product', value='yes', tagger=who)
                                                         for who in ('one', 'two')])
            bars = root / 'bars.jsonl'; prices = []; records = []
            sessions = [dict(date=f'2026-09-0{i}', open='09:30', close='16:00') for i in (1, 2, 3)]
            for ticker in ('TEST', 'XBI'):
                for session in sessions:
                    bar = dict(ticker=ticker, date=session['date'], close=10.0, adjusted_close=10.0,
                               provider='IBKR', adjustment='split_only')
                    records.append(json.dumps(bar))
                    prices.append({**{k: bar[k] for k in ('ticker', 'date', 'close', 'adjusted_close')},
                                   'source': f'{bars}#L{len(records)}'})
            bars.write_text('\n'.join(records))
            db = Path(tmp) / 'data.sqlite'
            result = build(db, dict(as_of='2026-10-04', events=[event], prices=prices, sessions=sessions), ROOT / 'knowledge')
            self.assertEqual(result['eligible'], 1)
            check(db, result)
            result['events'][0]['reaction']['day1_abnormal'] = .5
            with self.assertRaisesRegex(GateError, 'reaction'): check(db, result)
            result = report(db, 'all', ROOT / 'knowledge')
            source.write_text(source.read_text().replace('approved', 'expects to approve'))
            with self.assertRaisesRegex(GateError, 'Date type'): check(db, result)

    def test_legacy_currency_mismatch_warns_even_when_converted_discount_is_normal(self):
        from tests.test_amendments import catalysts
        with redirect_stderr(io.StringIO()) as err:
            result = catalysts.numbers(dict(anchor_value=1, anchor_currency='GBP', price=100, currency='GBp'))
        self.assertEqual(result['discount'], -99)
        self.assertIn('different units', err.getvalue())
