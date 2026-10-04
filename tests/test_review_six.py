"""Round-seven offline regressions. Synthetic cases are labelled separately from saved HTTP samples."""
import copy
import csv
from datetime import date
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

from tests.support import ROOT, bundle, massive_prices
from refclass.collectors import massive
from refclass.crosscheck import compare_bars
from refclass.engine import reaction
from refclass.publication import price_evidence
from refclass.quality import GateError


class RoundSevenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / 'deals/test/filings/massive/2026-10-04'
        self.raw.mkdir(parents=True)

    def test_real_legacy_tools_permitted_and_orders_denied(self):
        from lib.ibkr_readonly import allowed
        expected = {'get_price_snapshot', 'get_account_positions', 'get_account_balances',
                    'search_contracts', 'get_account_summary'}
        self.assertEqual(set(allowed('ibkr', 'ibkr')) - {'Read', 'Glob', 'Grep'},
                         {'mcp__ibkr__' + t for t in expected})
        for tool in expected | {'create_order_instruction', 'get_stock_price'}:
            proc = subprocess.run([sys.executable, str(ROOT / 'lib/ibkr_readonly.py'),
                '--server', 'ibkr', '--mode', 'ibkr'], input=json.dumps({'tool_name': 'mcp__ibkr__' + tool}),
                text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0 if tool in expected else 2)

    def test_free_float_launched_product_and_unrelated_dollars_rejected(self):
        from refclass.profile import verify_profile
        folder = self.root / 'deals/test/filings'
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / 'profile.txt'
        ev = dict(source=str(source), line_start=1, line_end=1)
        profile = dict(ev, first_product=True, as_of='2026-06-30', market_value=1200000000,
                       market_value_evidence=dict(ev, currency='USD', as_of='2026-06-30'))
        good = 'We have no approved products. Market capitalization at the pre-news close $1.2 billion as of June 30, 2026.'
        source.write_text(good)
        verify_profile(profile, folder.parent)
        for text in (good.replace('We have no approved products', 'Our first commercial product, X, launched'),
                     good.replace('Market capitalization', 'Aggregate market value held by non-affiliates'),
                     good.replace('at the pre-news close ', ''),
                     good.replace('$1.2 billion', '$2 billion') + ' Cash $1.2 billion.'):
            source.write_text(text)
            with self.assertRaises(GateError):
                verify_profile(profile, folder.parent)

    def test_saved_real_massive_samples_both_conventions_and_tamper(self):
        fixture = ROOT / 'tests/fixtures/massive/2026-10-04'
        shutil.copytree(fixture, self.raw, dirs_exist_ok=True)
        client = massive.Client(self.raw, offline=True, opener=Mock(side_effect=AssertionError('Network forbidden')))
        result = massive.collect(client, tickers=['KALV'], since='2025-07-01', until='2025-07-10', today=date(2026,10,4))
        self.assertTrue(result['complete'], result['gaps'])
        self.assertEqual(len(result['prices']), 14)
        self.assertEqual({r['ticker'] for r in result['prices']}, {'KALV', 'XBI'})
        for row in result['prices']:
            self.assertEqual(price_evidence(row)['provider'], 'Massive')
        row = result['prices'][0]
        with self.assertRaises(GateError):
            price_evidence(dict(row, adjusted_close=row['adjusted_close'] + 1))
        bar = price_evidence(row)
        Path(bar['raw_evidence'][0]['source']).write_text('{}')
        with self.assertRaises(GateError):
            price_evidence(row)

    def test_split_returns_as_traded_cap_and_primary_request_conventions(self):
        from refclass.engine import market_value
        sessions = [dict(date=f'2026-09-0{i}', open='09:30', close='16:00') for i in (1,2,3)]
        rows = [dict(ticker=ticker, date=s['date'], close=close, adjusted_close=adjusted)
                for ticker in ('DELISTED', 'XBI') for s, close, adjusted in zip(sessions,
                    (100, 55, 60) if ticker == 'DELISTED' else (100,100,100),
                    (50,55,60) if ticker == 'DELISTED' else (100,100,100))]
        prices = massive_prices(self.raw, rows)
        event = dict(event_id='e', ticker='DELISTED', announced_at='2026-09-02T08:00:00-04:00',
                     action_date='2026-09-02', shares=10, shares_as_of='2026-08-01', shares_source='filing')
        r = reaction(event, prices, sessions)
        self.assertAlmostEqual(r['day1_raw'], .1)
        self.assertAlmostEqual(r['day2_abnormal'], .2)
        self.assertEqual(r['pre_unadjusted_close'], 100)
        self.assertEqual(market_value(event, prices, sessions), 1000)
        for p in prices:
            price_evidence(p)
        p = prices[0]
        path = Path(p['source'].split('#L')[0])
        bars = [json.loads(line) for line in path.read_text().splitlines()]
        bars[0]['raw_evidence'].reverse()
        path.write_text(''.join(json.dumps(b)+'\n' for b in bars))
        with self.assertRaises(GateError):
            price_evidence(p)

    def test_free_history_gap_without_dropping_candidates_and_upgrade(self):
        client = Mock()
        old = massive.collect(client, tickers=['OLD'], since='2015-01-01', until='2015-01-10', today=date(2026,10,4))
        self.assertFalse(old['complete'])
        self.assertIn('plan history gap', old['gaps'][0])
        client.get.assert_not_called()
        client.get.side_effect = ValueError('saved entitlement failure')
        upgraded = massive.collect(client, tickers=['OLD'], since='2015-01-01', until='2015-01-10',
                                   history_years=20, today=date(2026,10,4))
        self.assertEqual(client.get.call_count, 2)  # OLD and XBI, each fails its first request.
        self.assertFalse(upgraded['complete'])
        from refclass.pipeline import assemble
        path = self.root / 'old.json'; path.write_text(json.dumps(old))
        candidate = dict(candidate_id='old', company='Delisted')
        result = assemble(dict(events=[], candidates=[candidate]), [path])
        self.assertEqual(result['candidates'], [candidate])
        self.assertEqual(result['pending_candidates'], ['old'])

    def client(self, opener, clock=None):
        settings = self.root / 'settings.env'
        settings.write_text('MASSIVE_API_KEY="synthetic-test-secret"\n')
        clock = clock or Mock(return_value=1000)
        def sleep(delay):
            clock.return_value += delay
        return massive.Client(self.raw, settings=settings, opener=opener, clock=clock, sleep=sleep,
                              rate_path=self.root / 'rate.json')

    def test_persistent_rate_limiter_and_header_only_key(self):
        response = Mock(status=200)
        response.read.return_value = b'{"status":"OK"}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock(return_value=response)
        clock = Mock(return_value=1000)
        times = []
        for _ in range(6):
            client = self.client(opener, clock)
            client.get('XBI', '2025-07-01', '2025-07-10', False)
            times.append(clock.return_value)
        self.assertGreater(times[-1] - times[0], 60)
        for call in opener.call_args_list:
            req = call.args[0]
            self.assertNotIn('synthetic-test-secret', req.full_url)
            self.assertEqual(req.get_header('Authorization'), 'Bearer synthetic-test-secret')
        self.assertNotIn('synthetic-test-secret', ''.join(p.read_text() for p in self.raw.iterdir() if p.is_file()))

    def test_error_responses_and_transport_exceptions_do_not_leak_key(self):
        for status in (403, 429):
            opener = Mock(side_effect=urllib.error.HTTPError('secret-url', status, 'synthetic-test-secret', {},
                                                            io.BytesIO(b'synthetic-test-secret')))
            client = self.client(opener)
            with self.assertRaisesRegex(ValueError, 'HTTP ' + str(status)) as exc:
                client.get('XBI', '2025-07-01', '2025-07-10', False)
            self.assertNotIn('synthetic-test-secret', str(exc.exception))
        opener = Mock(side_effect=urllib.error.URLError('synthetic-test-secret'))
        with self.assertRaises(ValueError) as exc:
            self.client(opener).get('XBI', '2025-07-01', '2025-07-10', False)
        self.assertNotIn('synthetic-test-secret', str(exc.exception))
        self.assertNotIn('synthetic-test-secret', ''.join(p.read_text() for p in self.raw.iterdir() if p.is_file()))

    def test_missing_adjustment_wrong_ticker_pagination_and_duplicates_fail(self):
        for payload in ({'ticker':'WRONG', 'adjusted':False}, {'ticker':'XBI'},
                        {'ticker':'XBI','adjusted':False,'status':'OK','next_url':'url'},
                        {'ticker':'XBI','adjusted':False,'status':'ERROR'}):
            with self.assertRaises(ValueError):
                massive.unpack(payload, 'XBI', False, '2025-07-01', '2025-07-10')

    def test_ibkr_threshold_missing_and_five_year_scope(self):
        data = bundle()
        e = data['events'][0]; e['action_date'] = e['announced_at'][:10]
        pre = reaction(e, data['prices'], data['sessions'])['pre_date']
        p = next(r for r in data['prices'] if r['ticker']==e['ticker'] and r['date']==pre)
        from decimal import Decimal
        for diff, status in (('.01','matched'), ('.0101','review')):
            b = dict(p, close=str(Decimal(str(p['close']))+Decimal(diff)))
            results = compare_bars([e], data['prices'], data['sessions'], [b], '2026-10-04')
            self.assertEqual(results[0]['status'], status)
            self.assertEqual(results[0]['difference'], str(Decimal(diff)))
            self.assertEqual(sum(r['status']=='missing' for r in results), 5)
        e['action_date'] = '2020-10-03'
        self.assertEqual(compare_bars([e], data['prices'], data['sessions'], [], '2026-10-04'), [])

    def test_real_tool_plain_ohlcv_saved_for_independent_checks_only(self):
        from refclass.bars import transcript_bars
        from refclass.collectors.ibkr import collect
        from refclass.pipeline import assemble
        transcript = self.raw / 'broker.jsonl'
        blocks = [dict(type='tool_use', id='s', name='mcp__ibkr__search_contracts', input={'symbol':'TEST'}),
                  dict(type='tool_result', tool_use_id='s', content=json.dumps([dict(contract_id=42,symbol='TEST')])),
                  dict(type='tool_use', id='h', name='mcp__ibkr__get_price_history', input=dict(contract_id=42,period='FIVE_YEARS')),
                  dict(type='tool_result', tool_use_id='h', content=json.dumps(dict(bars=[dict(date='2026-09-01',close=10)])))]
        transcript.write_text('\n'.join(json.dumps(dict(message=dict(content=[b]))) for b in blocks))
        rows = transcript_bars(transcript, 'ibkr')
        self.assertEqual(rows[0]['ticker'], 'TEST')
        self.assertNotIn('adjusted_close', rows[0])
        path = self.raw / 'broker-bars.jsonl'; path.write_text('\n'.join(map(json.dumps, rows)))
        result = collect(path, tickers=['TEST'], since='2026-09-01', until='2026-09-03')
        self.assertEqual(len(result['ibkr_checks']), 1)
        self.assertEqual(result['prices'], [])
        output = self.root / 'broker.collection.json'; output.write_text(json.dumps(result))
        joined = assemble({'events':[]}, [output])
        self.assertEqual(joined['prices'], [])
        self.assertEqual(len(joined['ibkr_checks']), 1)
        transcript.write_text(transcript.read_text().replace('10', '11'))
        from refclass.crosscheck import verify_check
        with self.assertRaises(GateError): verify_check(result['ibkr_checks'][0])

    def test_acceptance_missing_xbi_fails_despite_price_partition_waiver(self):
        from refclass.acceptance import evaluate
        data = bundle()
        target_rows = []
        events = []
        for e in data['events']:
            e['action_date'] = e['announced_at'][:10]
            target_rows.append(dict(ticker=e['ticker'], action_date=e['action_date']))
            events.append(dict(event=e, reaction=reaction(e, data['prices'], data['sessions'])))
        missing = events[0]['reaction']['day1_date']
        prices = [p for p in data['prices'] if (p['ticker'],p['date']) != ('XBI',missing)]
        events[0]['reaction'] = reaction(events[0]['event'], prices, data['sessions'])
        result = dict(as_of='2026-10-04', candidate_count=4, pending_candidates=[], events=events,
            coverage={name:[dict(complete=name!='massive', scope=dict(since='2015-01-01',until='2026-10-04'))]
                      for name in ('drugs_at_fda','openfda_crl','edgar','massive')})
        targets = self.raw / 'targets.json'; targets.write_text(json.dumps(target_rows))
        with patch('refclass.acceptance.report', return_value=result), patch('refclass.acceptance.check'):
            with self.assertRaisesRegex(GateError, 'Comparable is unpriced'):
                evaluate('unused', ROOT / 'knowledge', targets)

    def test_bad_reviews_isolated_resolutions_preserved_and_current_listing(self):
        from refclass.review import prepare, reconcile, pending_reviews, verify_event_review
        source = self.raw / 'evidence.txt'; source.write_text('Private sponsors, not listed.\n')
        ev = dict(source=str(source), line_start=1, line_end=1)
        candidates = [dict(candidate_id=k, company=k, source=str(source), locator='L.1') for k in ('bad','resolved','tags')]
        collection = self.root/'collection.json'
        collection.write_text(json.dumps(dict(source='drugs_at_fda',complete=True,candidates=candidates)))
        folder = self.root / 'prepare'; prepared = prepare([collection], folder)
        paths = [self.root/'one.csv', self.root/'two.csv']
        def write(path, rows):
            with path.open('w',newline='') as f:
                w=csv.DictWriter(f, fieldnames=['candidate_id','decision','event_json','reason']);w.writeheader();w.writerows(rows)
        base = []
        for e in prepared['event_drafts']:
            e.update(review_evidence=ev, press_release_conflict=False)
            base.append(dict(candidate_id=e['candidate_id'], decision='exclude', event_json=json.dumps(e), reason='Source reviewed'))
        human = self.root/'human.csv';write(human,[base[1]])
        for i,path in enumerate(paths):
            rows=copy.deepcopy(base)
            event=json.loads(rows[0]['event_json']);event.pop('review_evidence');rows[0]['event_json']=json.dumps(event)
            rows[1]['event_json']='invalid JSON from model'
            event=json.loads(rows[2]['event_json']);event['tags']=[dict(ev,feature='first_product',value=bool(i))]
            rows[2]['event_json']=json.dumps(event);write(path,rows)
        registry = self.root/'registry'
        with patch('refclass.review.REVIEW_ROOT', registry):
            old=self.root/'old';new=self.root/'new'
            self.assertEqual(reconcile(folder/'candidates.json',paths,old,human),2)
            result=json.loads((old/'reviewed.json').read_text())
            self.assertEqual(result['events'][0]['candidate_id'],'resolved')
            verify_event_review(result['events'][0])
            listing='\n'.join(pending_reviews(registry))
            self.assertIn('first_product',listing);self.assertIn('false',listing);self.assertIn('true',listing)
            # Missing primary file is also a candidate disagreement, not a global failure.
            bad=json.loads(base[0]['event_json']);bad['review_evidence']=dict(ev,source=str(self.raw/'missing.txt'))
            rows=copy.deepcopy(base);rows[0]['event_json']=json.dumps(bad)
            for path in paths:write(path,rows)
            self.assertEqual(reconcile(folder/'candidates.json',paths,new,human),1)
            self.assertNotIn('tags |', '\n'.join(pending_reviews(registry)))
            for path in paths:write(path,base)
            self.assertEqual(reconcile(folder/'candidates.json',paths,new,human),0)
            self.assertEqual(list(pending_reviews(registry)),[])
            self.assertTrue((old/'disagreements.csv').exists())

    def test_overlapping_benchmark_collections_deduplicate_or_fail_on_conflict(self):
        from refclass.pipeline import assemble
        row = dict(ticker='XBI', date='2026-09-01', close=100, adjusted_close=100, source='primary')
        paths=[]
        for i in range(2):
            path=self.root/f'part{i}.json'
            path.write_text(json.dumps(dict(source='massive', complete=True, prices=[row])))
            paths.append(path)
        result=assemble(dict(events=[]), paths)
        self.assertEqual(len(result['prices']),1)
        row['adjusted_close']=50
        paths[1].write_text(json.dumps(dict(source='massive', complete=True, prices=[row])))
        with self.assertRaisesRegex(ValueError,'Conflicting prices'):
            assemble(dict(events=[]), paths)
