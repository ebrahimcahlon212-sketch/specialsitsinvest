"""Round-eight regressions using temporary synthetic evidence and saved HTTP samples."""
import copy
import csv
from datetime import date
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from tests.support import ROOT, bundle, massive_prices
from refclass.collectors import massive
from refclass.engine import build, report, render
from refclass.profile import verify_profile
from refclass.quality import GateError
from refclass.review import pending_reviews


class ReviewSevenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.deal = self.root / 'deals/test'
        self.raw = self.deal / 'filings'
        self.raw.mkdir(parents=True)

    def profile(self):
        source = self.raw / 'quarter.txt'
        source.write_text('We do not have any products approved for sale.\n'
                          'As of September 1, 2026, 200,000,000 shares of common stock were outstanding.\n')
        inventory = self.raw / 'inventory.json'
        inventory.write_text(json.dumps(dict(tickers=['TEST'], filings=dict(recent=dict(
            accessionNumber=['a'], filingDate=['2026-09-02'], form=['10-Q'], primaryDocument=['q.htm']), files=[]))))
        price = massive_prices(self.raw / 'massive', [dict(ticker='TEST', date='2026-09-03', close=5,
                                                         adjusted_close=10)])[0]
        ev = dict(source=str(source), line_start=2, line_end=2, filed_at='2026-09-02',
                  as_of='2026-09-01', shares=200000000, accessionNumber='a')
        return dict(source=str(source), locator='L.1', line_start=1, line_end=1,
                    as_of='2026-09-03', first_product=True,
                    market_value_inputs=dict(currency='USD', ticker='TEST', price=price,
                        shares=ev['shares'], shares_as_of=ev['as_of'], shares_source=str(source),
                        share_filings=[ev], inventory_sources=[dict(source=str(inventory))]))

    def test_profile_calculates_from_realistic_filing_wording_and_primary_bar(self):
        profile = self.profile()
        verify_profile(profile, self.deal)
        self.assertEqual(profile['market_value'], '1000000000.0')
        self.assertIn('5.0 * 200000000', profile['market_value_calculation'])
        # Saved/reloaded calculations remain valid and select class C.
        (self.deal / 'refclass.json').write_text(json.dumps(profile))
        shutil.copytree(ROOT / 'knowledge', self.root / 'knowledge')
        db = self.root / 'db.sqlite'
        build(db, bundle(), self.root / 'knowledge')
        result = report(db, 'test', self.root / 'knowledge')
        self.assertEqual(result['selected_class'], 'C')
        self.assertIn(profile['market_value_calculation'], render(result))
        self.assertIn(profile['market_value_inputs']['price']['source'], render(result))
        historical = copy.deepcopy(profile)
        historical['market_value_inputs'].update(announced_at='2026-09-04T08:00:00-04:00',
            sessions=[dict(date=f'2026-09-0{i}', open='09:30', close='16:00') for i in (2,3,4,7)])
        verify_profile(historical, self.deal)
        historical['market_value_inputs']['announced_at'] = '2026-09-03T08:00:00-04:00'
        with self.assertRaisesRegex(GateError, 'pre-news session'): verify_profile(historical, self.deal)
        for field, value in [('close', 6), ('date', '2026-09-02'), ('ticker', 'OTHER')]:
            bad = copy.deepcopy(profile)
            bad['market_value_inputs']['price'][field] = value
            with self.assertRaises(GateError): verify_profile(bad, self.deal)
        bad = copy.deepcopy(profile); bad['market_value'] = 2000000000
        with self.assertRaises(GateError): verify_profile(bad, self.deal)
        inventory = Path(profile['market_value_inputs']['inventory_sources'][0]['source'])
        data = json.loads(inventory.read_text())
        data['filings']['recent'] = dict(accessionNumber=['new'], filingDate=['2026-09-03'], form=['10-Q'], primaryDocument=['new.htm'])
        inventory.write_text(json.dumps(data))
        with self.assertRaisesRegex(GateError, 'latest SEC'): verify_profile(profile, self.deal)

    def test_disease_competitor_and_unscoped_product_sentences_fail(self):
        profile = self.profile(); profile.pop('market_value_inputs')
        for text in ('There are no approved products for the treatment of this disease.',
                     'No products are approved for commercial sale.',
                     'Our competitor has no approved products.'):
            Path(profile['source']).write_text(text)
            with self.assertRaises(GateError): verify_profile(profile, self.deal)
        Path(profile['source']).write_text('We have no FDA-approved products.')
        verify_profile(profile, self.deal)

    def test_split_adjustment_matches_and_real_discrepancy_reaches_review_command(self):
        from refclass.__main__ import main
        data = bundle()
        e = data['events'][0]; e['action_date'] = e['announced_at'][:10]
        p = data['prices'][0]; p['close'] = 100; p['adjusted_close'] = 10
        check = dict(p, close=10, source='synthetic IBKR')
        data['ibkr_checks'] = [check]
        db = self.root / 'db.sqlite'
        result = build(db, data, ROOT / 'knowledge')
        row = next(r for r in result['ibkr_comparisons'] if r.get('ticker') == p['ticker'])
        self.assertEqual(row['status'], 'matched')
        self.assertEqual(row['matched_convention'], 'split_adjusted')
        check['close'] = 11
        build(db, data, ROOT / 'knowledge')
        output = io.StringIO()
        with redirect_stdout(output), patch('refclass.review.pending_reviews', return_value=iter([])):
            self.assertEqual(main(['review', '--db', str(db)]), 0)
        self.assertIn('Price difference requires review', output.getvalue())
        self.assertIn('synthetic IBKR', output.getvalue())
        self.assertIn('massive_adjusted_close', output.getvalue())

    def test_conflicting_update_is_atomic_and_equal_check_deduplicates(self):
        data = bundle()
        data['ibkr_checks'] = [dict(ticker='XBI', date='2026-09-03', close=100, source='synthetic')]
        db = self.root / 'db.sqlite'; build(db, data, ROOT / 'knowledge')
        before = db.read_bytes()
        update = dict(as_of=data['as_of'], ibkr_checks=[dict(data['ibkr_checks'][0], close=101)])
        with self.assertRaisesRegex(ValueError, 'Conflicting ibkr_checks'):
            build(db, update, ROOT / 'knowledge', update=True)
        self.assertEqual(db.read_bytes(), before)
        update['ibkr_checks'][0]['close'] = 100
        result = build(db, update, ROOT / 'knowledge', update=True)
        self.assertEqual(len(result['ibkr_checks']), 1)

    def test_old_disagreements_visible_diff_only_and_registry_supersedes(self):
        folder = self.root / 'reviews/old'; folder.mkdir(parents=True)
        one = dict(decision='include', reason='reviewed', event_json=json.dumps(dict(
            drug='same drug', tags=[dict(feature='first_product', value='yes'), dict(feature='orphan', value='yes')])))
        two = copy.deepcopy(one)
        two['event_json'] = two['event_json'].replace('"first_product", "value": "yes"', '"first_product", "value": "no"')
        with (folder / 'disagreements.csv').open('w') as f:
            writer = csv.DictWriter(f, fieldnames=['candidate_id','review_one','review_two','reason'])
            writer.writeheader(); writer.writerow(dict(candidate_id='c',review_one=json.dumps(one),review_two=json.dumps(two)))
        listing = '\n'.join(pending_reviews(self.root / 'reviews'))
        self.assertIn('first_product', listing)
        self.assertNotIn('orphan', listing)
        self.assertNotIn('same drug', listing)
        new = self.root / 'reviews/new'; new.mkdir()
        (new / 'disagreements.csv').write_text('candidate_id,review_one,review_two,reason\n')
        (self.root / 'reviews/active-reviews.json').write_text(json.dumps({'c':str(new)}))
        self.assertEqual(list(pending_reviews(self.root / 'reviews')), [])

    def test_long_history_uses_one_pair_per_ticker(self):
        client = Mock(cache=self.raw)
        client.get.side_effect = lambda ticker, since, until, adjusted: (dict(
            ticker=ticker, adjusted=adjusted, status='OK', results=[]), {})
        massive.collect(client, tickers=['OLD'], since='2015-01-01', until='2026-10-04',
                        history_years=20, today=date(2026,10,4))
        self.assertEqual(client.get.call_count, 4)  # OLD and XBI, two conventions.
        self.assertTrue(all(c.args[1:3] == ('2015-01-01','2026-10-04') for c in client.get.call_args_list))

    def test_collect_dispatches_background_by_default_and_foreground_explicitly(self):
        from refclass.background import launch
        script = (ROOT / 'run.sh').read_text()
        start = script.index('  refclass)\n', script.index('case "${1:-help}"'))
        end = script.index('  help|-h|--help)', start)
        shell = 'PYTHON=echo\ncase "$1" in\n' + script[start:end] + '\nesac\n'
        args = ['collect', 'massive', '--tickers', 'KALV', '--output', 'collection.json']
        for foreground in (False, True):
            command = args + (['--foreground'] if foreground else [])
            result = subprocess.run(['bash', '-c', shell, 'test', 'refclass', *command],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            module = 'refclass' if foreground else 'refclass.background'
            self.assertEqual(result.stdout.strip(), '-m ' + module + ' ' + ' '.join(args))
        with patch('refclass.background.Path.home', return_value=self.root), \
                patch('refclass.background.subprocess.Popen') as popen:
            popen.return_value.pid = 123
            pid, log = launch(args + ['--db', str(self.root / 'db.sqlite')], ROOT)
            self.assertEqual(log.parent, self.root / 'special-sits-kit-logs')
            self.assertTrue(log.exists())
            self.assertTrue(popen.call_args.kwargs['start_new_session'])
            self.assertTrue(popen.call_args.kwargs['pass_fds'])

    def test_live_resume_across_dates_refresh_and_paid_rate(self):
        cache = self.raw / 'massive/2026-10-04'
        shutil.copytree(ROOT / 'tests/fixtures/massive/2026-10-04', cache)
        settings = self.root / 'settings.env'; settings.write_text('MASSIVE_API_KEY=synthetic-test-secret\n')
        opener = Mock(side_effect=AssertionError('Network forbidden'))
        next_cache = cache.parent / '2026-10-05'
        client = massive.Client(next_cache, settings=settings, opener=opener, calls_per_minute=60,
                                rate_path=self.root / 'rate.json', sleep=Mock(), clock=Mock(return_value=1000))
        result = massive.collect(client, tickers=['KALV'], since='2025-07-01', until='2025-07-10', today=date(2026,10,4))
        self.assertTrue(result['complete'], result['gaps'])
        opener.assert_not_called()
        self.assertEqual(client.interval, 1.1)
        client.throttle(); client.throttle()
        self.assertAlmostEqual(client.sleep.call_args.args[0], 1.1)
        client.refresh = True
        with self.assertRaises(AssertionError): client.get('KALV', '2025-07-01', '2025-07-10', False)
        manifest = json.loads((cache / 'manifest.json').read_text())
        (cache / manifest[0]['file']).write_text('{}')
        client.refresh = False
        with self.assertRaisesRegex(ValueError, 'checksum'):
            client.get('KALV', '2025-07-01', '2025-07-10', False)


if __name__ == '__main__':
    unittest.main()
