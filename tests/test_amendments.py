"""Offline regression contracts for amendments 1, 2, 3 and 6."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.support import ROOT
from refclass.quality import GateError, decision_date, source_excerpt, validate
sys.path.insert(0, str(ROOT / 'lib'))
import biotech
import calc
import catalysts
import finder
import ukevents
import valuation
from quality_gate import preflight


class AmendmentTests(unittest.TestCase):
    def test_pre_phase_one_numbers_and_markdown_match_saved_baseline(self):
        import datetime
        baseline = json.loads((ROOT / 'tests/fixtures/legacy-baseline.json').read_text())
        for row in baseline['cases']:
            module = calc if row['module'] == 'calc' else catalysts
            with self.subTest(row['label']), patch.object(module, 'TODAY', datetime.date(2026, 10, 4)):
                if module is calc:
                    result = module.compute(row['input'], row['prices'])
                    self.assertEqual(json.loads(json.dumps(result)), row['result'])
                    self.assertEqual(module.to_markdown(*result, row['input']), row['markdown'])
                else:
                    self.assertEqual(module.numbers(row['input']), row['result'])

    def test_legacy_missing_bad_and_invalid_evidence_warns_even_with_old_strict_env(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, QUALITY_GATES='strict'):
            p = Path(tmp)
            for content in (None, '{}', '{bad', '[]'):
                if content is not None:
                    (p / 'quality.json').write_text(content)
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    self.assertIsNone(preflight(p))
                if content is None:
                    self.assertEqual(stderr.getvalue(), '')
                else:
                    self.assertIn('Warning.', stderr.getvalue())
                with self.assertRaises(GateError):
                    preflight(p, strict=True)

    def test_research_ignores_bad_quality_without_writing_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            for body in ('{}', '{invalid', json.dumps({'date_type': {'source': '/no/such/file'}})):
                (p / 'raw').write_text('<<<BEGIN OUTPUT>>>\nAnswer\n<<<END OUTPUT>>>\n'
                                      '<<<BEGIN QUALITY>>>\n' + body + '\n<<<END QUALITY>>>\n')
                result = subprocess.run([sys.executable, str(ROOT / 'lib/extract_output.py'),
                                         str(p / 'raw'), str(p / 'answer'), 'research'], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((p / 'answer').read_text(), 'Answer\n')
                self.assertFalse((p / 'answer.quality.json').exists())

    def test_all_model_step_labels_preserve_prompts_and_extract_answers(self):
        # Exercise the actual shell function with model stand-ins, without starting any CLIs.
        script = (ROOT / 'run.sh').read_text()
        function = script[script.index('run_step() {'):script.index('\nreviewers() {')]
        labels = ['draft', 'review', 'fund-draft', 'fund-review', 'gather-web', 'valuation',
                  'check-claude', 'ask-123', 'angles', 'explain', 'sizing', 'idea-triage',
                  'map', 'terms', 'quotes', 'ukquotes', 'remember', 'feedback', 'bio-cards-1',
                  'catalysts', 'uk-events', 'final', 'fund-final', 'biotech', 'competition']
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'raw').mkdir(); (p / 'logs').mkdir()
            prompt = p / 'prompt'; prompt.write_text('Original instructions\n')
            shell = '''set -u
KIT="$1"; OUT="$2"; PYTHON="$3"
say() { :; }
warn() { echo "$*" >&2; }
rel() { echo "$1"; }
call_codex() {
  cat "$1" > "$OUT/seen-$label"
  printf '<<<BEGIN OUTPUT>>>\\nAnswer\\n<<<END OUTPUT>>>\\n<<<BEGIN QUALITY>>>\\n{bad\\n<<<END QUALITY>>>\\n' > "$2"
}
'''+function+'\nshift 3\nfor label in "$@"; do run_step codex "$OUT/prompt" "$label" "$OUT/$label.md" || exit 1; done\n'
            result = subprocess.run(['bash', '-c', shell, 'test', str(ROOT), tmp, sys.executable, *labels],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for label in labels:
                self.assertEqual((p / ('seen-' + label)).read_text(), 'Original instructions\n')
                self.assertEqual((p / (label + '.md')).read_text(), 'Answer\n')
            self.assertEqual(prompt.read_text(), 'Original instructions\n')

    def test_real_legacy_renderers_and_calculators_without_mocking_gates(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            p = Path(tmp); out = p / 'out'; out.mkdir()
            (out / 'quality.json').write_text('{}')
            (out / 'biotech.json').write_text(json.dumps({'rows': []}))
            cards = p / 'cards'; cards.write_text('{}\n')
            biotech.cmd_cards(str(out), [str(cards)])
            biotech.cmd_render(str(out))
            with patch.object(finder, 'STATE', str(p / 'finder-state.json')), patch.object(finder, 'FINDER', tmp):
                finder.cmd_render(str(out))
            with patch.object(ukevents, 'STATE', str(p / 'uk-state.json')):
                ukevents.cmd_ingest(str(out), str(cards))
            with patch.object(catalysts, 'STATE', str(p / 'catalyst-state.json')):
                catalysts.cmd_render(str(out))
            (out / 'valuation.json').write_text('{}')
            valuation.cmd_compute(str(p))
            (out / 'terms.txt').write_text(json.dumps({'target_ticker': 'ABC', 'cash_per_share': 12, 'currency': 'USD'}))
            (out / 'terms.txt.quality.json').write_text('{broken sidecar')
            calc.cmd_terms(str(p))
            with patch.object(calc, 'load_prices', return_value={'ABC': {'price': 10}}):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    calc.cmd_deal(str(p))
            self.assertIn('property name', stderr.getvalue())  # Reads terms.txt sidecar, not shared {}.
            result = json.loads((out / 'calc.json').read_text())
            self.assertAlmostEqual(result['results']['spread_pct'], .2)
            for name in ('biotech.html', 'shortlist.html', 'uk_events.json', 'catalysts.html', 'valuation.md', 'calc.md'):
                self.assertTrue((out / name).exists(), name)

    def test_strict_gate_cannot_publish_with_all_not_applicable(self):
        evidence = {key: {'not_applicable': 'test'} for key in
                    ('units', 'staleness', 'listing', 'attribution', 'date_type', 'arithmetic', 'partial_tender')}
        with self.assertRaisesRegex(GateError, 'requires computations'):
            validate(evidence)

    def test_foreground_flag_anywhere_uses_foreground_dispatch(self):
        script = (ROOT / 'run.sh').read_text()
        start = script.index('  refclass)\n', script.index('case "${1:-help}"'))
        end = script.index('  help|-h|--help)', start)
        branch = script[start:end]
        shell = 'PYTHON=echo\ncase "$1" in\n' + branch + '\nesac\n'
        for args in (['refclass', 'build', '--foreground', '--input', 'sample.json'],
                     ['refclass', 'build', '--input', 'sample.json', '--foreground']):
            result = subprocess.run(['bash', '-c', shell, 'test', *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '-m refclass build --input sample.json')

    def test_sources_reject_output_traversal_cross_deal_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'deals/test'
            for folder in ('work', 'filings', 'out', '../other/filings'):
                (root / folder).mkdir(parents=True)
            for name in ('work/a.txt', 'filings/a.txt', 'out/draft.md', '../other/filings/a.txt'):
                (root / name).write_text('FDA source text')
            (root / 'work/link').symlink_to(root / 'out/draft.md')
            for name in ('work/a.txt', 'filings/a.txt'):
                self.assertEqual(source_excerpt(dict(source=name, line_start=1, line_end=1), root), 'FDA source text')
            for name in ('out/draft.md', 'work/../out/draft.md', '../other/filings/a.txt', 'work/link'):
                with self.assertRaises(GateError, msg=name):
                    source_excerpt(dict(source=name, line_start=1, line_end=1), root)

    def test_goal_date_wording_and_other_date_in_same_sentence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'deals/test/filings/source.txt'; p.parent.mkdir(parents=True)
            ev = dict(source=str(p), line_start=1, line_end=1)
            for sentence in ('The FDA assigned a PDUFA target action date of November 20, 2026 for the NDA submitted in March.',
                             'The FDA set a goal date of Nov. 20, 2026.', 'The action date is 20 November 2026.'):
                p.write_text(sentence)
                decision_date('fda_goal', '2026-11-20', ev)
            p.write_text('Submitted on November 20, 2026 for a PDUFA goal date of March 20, 2027.')
            with self.assertRaises(GateError):
                decision_date('fda_goal', '2026-11-20', ev)
