"""Round-six regressions. Artificial inputs, no live broker or census claims."""
import copy
import csv
from datetime import date
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from refclass.acceptance import compare
from refclass.bars import capability_gaps, request, transcript_bars
from refclass.collectors import fda, ibkr
from refclass.engine import build
from refclass.profile import verify_profile
from refclass.publication import check
from refclass.quality import GateError, publication_numbers
from refclass.review import prepare, reconcile, verify_event_review
from tests.support import ROOT


class ReviewFiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.deal = self.root / 'deals/test'
        (self.deal / 'filings').mkdir(parents=True)
        self.source = self.deal / 'filings/evidence.txt'
        self.source.write_text('Private sponsor excluded.\nPrivate sponsor not listed.\n')
        self.ev = dict(source=str(self.source), line_start=1, line_end=1)

    def reviews(self, decisions=('exclude', 'exclude'), evidence_diff=False):
        candidate = dict(candidate_id='fda:one', event_type='approval', application='NDA123456',
                         source=str(self.source), locator='L.1', action_date='2026-09-01', company='Company')
        collected = self.root / 'collected.json'
        collected.write_text(json.dumps(dict(source='drugs_at_fda', complete=True, candidates=[candidate])))
        folder = self.root / 'review'
        snapshot = prepare([collected], folder)
        event = dict(snapshot['event_drafts'][0], review_evidence=self.ev,
                     drug='Drug Name', press_release_conflict=False)
        paths = [folder / 'claude.csv', folder / 'codex.csv']
        for index, path in enumerate(paths):
            payload = copy.deepcopy(event)
            if index and evidence_diff:
                payload['review_evidence']['line_end'] = 2
                payload['drug'] = 'drug-name'
            self.write_review(path, decisions[index], payload)
        return folder, paths, event

    def write_review(self, path, decision, event):
        with path.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['candidate_id', 'decision', 'event_json', 'reason'])
            writer.writeheader()
            writer.writerow(dict(candidate_id='fda:one', decision=decision,
                                 event_json=json.dumps(event), reason='Reviewed primary exclusion evidence'))

    def test_excluded_private_sponsor_without_ticker_or_8k_builds_and_rechecks(self):
        folder, paths, _ = self.reviews(evidence_diff=True)
        self.assertEqual(reconcile(folder / 'candidates.json', paths, folder), 0)
        snapshot = json.loads((folder / 'reviewed.json').read_text())
        event = snapshot['events'][0]
        self.assertNotIn('ticker', event)
        self.assertIsNone(event['announced_at'])
        self.assertEqual(len(event['review_observations']), 2)
        db = self.root / 'db'
        result = build(db, snapshot, ROOT / 'knowledge')
        self.assertEqual((result['excluded'], result['pending_candidates']), (1, []))
        check(db, result)
        self.source.write_text('Changed primary record')
        with self.assertRaises(GateError):
            check(db, result)

    def test_reviewed_candidates_survive_adding_bar_collection(self):
        from refclass.pipeline import assemble
        folder, paths, _ = self.reviews()
        reconcile(folder / 'candidates.json', paths, folder)
        snapshot = json.loads((folder / 'reviewed.json').read_text())
        bars = self.root / 'bars.json'
        bars.write_text(json.dumps(dict(source='ibkr', complete=False, prices=[], gaps=['Unavailable'])))
        combined = assemble(snapshot, [bars])
        self.assertEqual(combined['pending_candidates'], [])
        self.assertEqual(len(combined['candidates']), 1)
        self.assertEqual(len(combined['events']), 1)

    def test_human_resolution_preserves_reviews_and_reason(self):
        folder, paths, event = self.reviews(('include', 'exclude'))
        original = [p.read_bytes() for p in paths]
        self.assertEqual(reconcile(folder / 'candidates.json', paths, folder), 1)
        resolution = folder / 'human.csv'
        self.write_review(resolution, 'exclude', event)
        self.assertEqual(reconcile(folder / 'candidates.json', paths, folder, resolution), 0)
        accepted = json.loads((folder / 'reviewed.json').read_text())['events'][0]
        self.assertEqual(accepted['event_resolution']['resolved_by'], 'Ebrahim')
        self.assertEqual([r['decision'] for r in accepted['review_observations']], ['include', 'exclude'])
        verify_event_review(accepted)
        self.assertEqual([p.read_bytes() for p in paths], original)
        event['action_date'] = '2026-01-01'
        self.write_review(resolution, 'exclude', event)
        with self.assertRaises(GateError):
            reconcile(folder / 'candidates.json', paths, folder, resolution)

    def test_substantive_tag_disagreement_remains_pending(self):
        folder, paths, event = self.reviews()
        for path, value in zip(paths, ('yes', 'no')):
            event['tags'] = [dict(self.ev, feature='first_product', value=value, locator='L.1')]
            self.write_review(path, 'exclude', event)
        self.assertEqual(reconcile(folder / 'candidates.json', paths, folder), 1)

    def test_bare_review_lists_without_required_arguments(self):
        from refclass.__main__ import main
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['review']), 0)
        self.assertTrue(output.getvalue().strip())

    def test_profile_real_wording_scale_and_date(self):
        profile = dict(self.ev, first_product=True, as_of='2026-06-30', market_value=1200000000,
                       market_value_evidence=dict(self.ev, currency='USD', as_of='2026-06-30'))
        self.source.write_text('We have no products approved for commercial sale. Market value $1.2 billion as of June 30, 2026.')
        verify_profile(profile, self.deal)
        for value in (120000000, 12000000000):
            with self.assertRaises(GateError): verify_profile(dict(profile, market_value=value), self.deal)
        self.source.write_text(self.source.read_text().replace('$', 'C$'))
        with self.assertRaises(GateError): verify_profile(profile, self.deal)

    def test_false_first_product_needs_positive_evidence(self):
        profile = dict(self.ev, as_of='2026-06-30', first_product=False)
        with self.assertRaises(GateError): verify_profile(profile, self.deal)
        self.source.write_text('We market Drug in the United States.')
        verify_profile(profile, self.deal)

    def test_split_comparables_match_as_traded_and_both_returns(self):
        target = dict(ticker='TEST', close_convention='as_traded', return_convention='split_only',
                      pre_date='2026-01-01', day1_date='2026-01-02', day2_date='2026-01-05',
                      pre_close=100, day1_close=110, day2_close=120, day1_raw=.1, day2_raw=.2)
        reaction = {k: v for k, v in target.items() if k.endswith('_date') or k.endswith('_raw')}
        for key in ('pre', 'day1', 'day2'):
            reaction[key + '_unadjusted_close'] = target[key + '_close']
            reaction[key + '_close'] = target[key + '_close'] / 10
        compare(reaction, target)
        for field in ('pre_close', 'day1_raw', 'day2_raw'):
            broken = dict(target); broken[field] += .1
            with self.assertRaises(GateError): compare(reaction, broken)
        target.pop('day2_raw')
        with self.assertRaises(GateError): compare(reaction, target)

    def test_broker_ohlcv_and_error_results_retained_as_gaps(self):
        payload = {'bars': [{'date': '2026-09-01', 'close': 10, 'open': 9, 'high': 11, 'low': 8, 'volume': 100}]}
        transcript = self.deal / 'filings/transcript.jsonl'
        transcript.write_text('\n'.join(json.dumps(dict(message=dict(content=[block]))) for block in [
            dict(type='tool_use', id='history', name='mcp__ibkr__get_price_history',
                 input=dict(contract_id=1234, period='FIVE_YEARS')),
            dict(type='tool_result', tool_use_id='history', content=json.dumps(payload))]))
        bars = transcript_bars(transcript, 'ibkr')
        self.assertEqual(bars[0]['broker_response'], payload)
        self.assertNotIn('adjusted_close', bars[0])
        self.assertIn('OHLCV', bars[0]['error'])
        self.source.write_text('\n'.join(map(json.dumps, bars)))
        result = ibkr.collect(self.source, tickers=['TEST'], since='2026-09-01', until='2026-09-02')
        self.assertFalse(result['complete'])
        self.assertEqual(result['prices'], [])

    def test_broker_five_year_limit_cannot_be_paginated(self):
        query = request(['TEST'], '2015-01-01', '2026-10-04')
        self.assertIn('no end-date', capability_gaps(query, date(2026, 10, 4))[0])
        self.assertEqual(capability_gaps(request(['TEST'], '2025-01-01', '2026-10-04'), date(2026, 10, 4)), [])

    def test_broker_sessions_have_exact_read_only_tool_allowlists(self):
        # Execute the actual shell function with a recording stub, no broker connection.
        shell = (ROOT / 'run.sh').read_text()
        function = shell[shell.index('call_claude() {'):shell.index('\ncall_codex() {')]
        prompt = self.root / 'prompt'; prompt.write_text('Offline test')
        for mode in ('ibkr', 'ibkr-bars'):
            output, log = self.root / 'args', self.root / 'log'
            script = f'KIT={ROOT}\nPYTHON={sys.executable}\n' + function + '\nenv() { printf "%s\\n" "$@"; }\nIBKR_SERVER=ibkr\nCLAUDE_MODEL=\ncall_claude "$1" "$2" "$3" "$4"\n'
            proc = subprocess.run(['bash', '-c', script, 'test', str(prompt), str(output), str(log), mode], capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            args = output.read_text().splitlines()
            allowed = args[args.index('--allowedTools') + 1].split(',')
            self.assertNotIn('mcp__ibkr', allowed)
            self.assertEqual(args[args.index('--tools') + 1], 'Read,Glob,Grep')
            self.assertIn('--setting-sources', args)
            self.assertIn('PreToolUse', args[args.index('--settings') + 1])
            self.assertFalse(any(any(x in tool for x in ('order', 'delete', 'watchlist', 'alert')) for tool in allowed))

    def test_broker_hook_denies_all_mutation_and_unknown_tools(self):
        from lib.ibkr_readonly import allowed
        command = [sys.executable, str(ROOT / 'lib/ibkr_readonly.py'), '--server', 'ibkr', '--mode', 'ibkr-bars']
        for tool in ('mcp__ibkr__create_order_instruction', 'mcp__ibkr__delete_watchlist',
                     'mcp__ibkr__create_alert', 'mcp__other__get_price_history', 'Bash', 'Write',
                     'mcp__ibkr__unknown_future_tool', *allowed('ibkr', 'ibkr-bars')):
            result = subprocess.run(command, input=json.dumps(dict(tool_name=tool)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0 if tool in allowed('ibkr', 'ibkr-bars') else 2, tool)

    def test_fda_conflicting_window_rejected_before_fetch(self):
        client = unittest.mock.Mock()
        with self.assertRaisesRegex(ValueError, 'conflict'):
            fda.collect(client, 'drugs_at_fda', since='2015-01-01', until='2026-10-04',
                        search='submissions.submission_status_date:[20250101 TO 20261004]')
        client.json.assert_not_called()

    def test_prose_numbers_cannot_be_omitted_from_arithmetic_list(self):
        self.source.write_text('Inputs 100 and 120. Extra sourced fact 9.')
        text = 'Return 20%. Extra 9.'
        evidence = dict(arithmetic=[dict(kind='return', reported=.2, inputs=dict(pre=100, post=120))],
                        numeric_claims=[dict(start=7, end=10, computation=0,
                            input_evidence={'/pre': self.ev, '/post': self.ev})])
        with self.assertRaisesRegex(GateError, 'without source'):
            publication_numbers(text, evidence)
        evidence['numeric_claims'].append(dict(start=18, end=19, evidence=self.ev))
        self.assertEqual(publication_numbers(text, evidence), 2)
        with self.assertRaises(GateError): publication_numbers(text.replace('20%', '30%'), evidence)
        evidence['numeric_claims'][0]['input_evidence'].pop('/post')
        with self.assertRaises(GateError): publication_numbers(text, evidence)

    def test_strict_extraction_rechecks_actual_prose_and_preserves_existing_output(self):
        from tests.test_review_fixes import evidence
        raw, out = self.root / 'raw', self.root / 'report'
        out.write_text('Existing report')
        raw.write_text('<<<BEGIN OUTPUT>>>\nUnchecked return 999%.\n<<<END OUTPUT>>>\n'
                       '<<<BEGIN QUALITY>>>\n' + json.dumps(evidence()) + '\n<<<END QUALITY>>>\n')
        proc = subprocess.run([sys.executable, str(ROOT / 'lib/extract_output.py'), str(raw), str(out), 'publication'],
                              capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('numeric claims', proc.stderr)
        self.assertEqual(out.read_text(), 'Existing report')


if __name__ == '__main__':
    unittest.main()
