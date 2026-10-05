"""Round-nine regressions for filing attribution, availability and stale reviews."""
import copy
import csv
import io
import json
from pathlib import Path
import shutil
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch

from tests import test_review_seven
from tests.support import ROOT, bundle
from refclass.__main__ import main
from refclass.engine import build
from refclass.profile import verify_profile
from refclass.quality import GateError


class ReviewEightTests(unittest.TestCase):
    setUp = test_review_seven.ReviewSevenTests.setUp
    profile = test_review_seven.ReviewSevenTests.profile

    def test_exact_savara_filing_lines_establish_first_product(self):
        # Exact text from the line tags cited in docs/build/review-8.md.
        lines = {
            '10-K L.1287': 'We are a clinical development-stage biopharmaceutical company, and we have not been profitable since we commenced operations and may not ever achieve profitability. In addition, we have limited history as an organization and have not yet demonstrated an ability to successfully overcome many of the risks and uncertainties frequently encountered by companies in new and rapidly evolving fields, particularly in the biopharmaceutical industry. Drug development is a highly speculative undertaking and involves a substantial degree of risk. We have not obtained any regulatory approvals for a product candidate, commercialized a product candidate, or generated any product revenue. We have devoted significant resources to research and development and other expenses related to our ongoing clinical trials and operations, in addition to acquiring product candidates.',
            '10-Q L.1701': '[1] MOLBREEVI is the proposed trade name for molgramostim inhalation solution. It is not approved in any indication. MOLBREEVI is a trademark of Savara Inc.',
        }
        profile = self.profile()
        profile.pop('market_value_inputs')
        profile['company'] = 'Savara'
        for locator, text in lines.items():
            with self.subTest(locator=locator):
                Path(profile['source']).write_text(text)
                verify_profile(profile, self.deal)
        profile['drug'] = 'MOLBREEVI'
        Path(profile['source']).write_text('MOLBREEVI is not approved in any indication.')
        verify_profile(profile, self.deal)
        for text in ('There are no approved therapies for autoimmune PAP.',
                     'Autoimmune PAP is not approved in any indication.',
                     'OTHERDRUG is not approved in any indication.',
                     'Our competitor has not obtained any regulatory approvals for a product candidate.'):
            with self.subTest(text=text):
                Path(profile['source']).write_text(text)
                with self.assertRaisesRegex(GateError, 'first-product'):
                    verify_profile(profile, self.deal)

    def test_same_day_share_filing_requires_acceptance_before_close(self):
        profile = self.profile()
        inputs = profile['market_value_inputs']
        inputs['share_filings'][0]['filed_at'] = profile['as_of']
        inventory = Path(inputs['inventory_sources'][0]['source'])
        data = json.loads(inventory.read_text())
        recent = data['filings']['recent']
        recent['filingDate'] = [profile['as_of']]
        for accepted, available in (
                ('2026-09-03T15:59:59-04:00', True),
                ('2026-09-03T19:59:59Z', True),
                ('2026-09-03T15:59:59', True),
                ('2026-09-03T16:00:00-04:00', False),
                ('2026-09-03T20:01:00Z', False),
                ('2026-09-03T17:00:00-04:00', False),
                (None, False)):
            with self.subTest(accepted=accepted):
                if accepted is None:
                    recent.pop('acceptanceDateTime', None)
                else:
                    recent['acceptanceDateTime'] = [accepted]
                inventory.write_text(json.dumps(data))
                if available:
                    verify_profile(copy.deepcopy(profile), self.deal)
                else:
                    with self.assertRaisesRegex(GateError, 'pre-event share filing'):
                        verify_profile(copy.deepcopy(profile), self.deal)

    def test_after_close_filing_does_not_displace_prior_filing(self):
        profile = self.profile()
        inventory = Path(profile['market_value_inputs']['inventory_sources'][0]['source'])
        data = json.loads(inventory.read_text())
        recent = data['filings']['recent']
        for key, value in dict(accessionNumber='new', filingDate=profile['as_of'],
                               form='10-Q', primaryDocument='new.htm').items():
            recent[key].append(value)
        for accepted in ('2026-09-03T17:00:00-04:00', None):
            recent['acceptanceDateTime'] = [None, accepted]
            inventory.write_text(json.dumps(data))
            verify_profile(copy.deepcopy(profile), self.deal)
        recent['acceptanceDateTime'][1] = '2026-09-03T15:00:00-04:00'
        inventory.write_text(json.dumps(data))
        with self.assertRaisesRegex(GateError, 'latest SEC'):
            verify_profile(profile, self.deal)

    def test_bare_review_prints_disagreements_with_stale_database(self):
        knowledge = self.root / 'knowledge'
        shutil.copytree(ROOT / 'knowledge', knowledge)
        folder = self.root / 'data/refclass/review'
        folder.mkdir(parents=True)
        one = dict(decision='include', reason='first reading', event_json='{"first_product": true}')
        two = dict(decision='include', reason='second reading', event_json='{"first_product": false}')
        with (folder / 'disagreements.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['candidate_id', 'review_one', 'review_two', 'reason'])
            writer.writeheader()
            writer.writerow(dict(candidate_id='disputed', review_one=json.dumps(one), review_two=json.dumps(two)))
        db = self.root / 'db.sqlite'
        for name, change_version in (('refclass-rules.md', True), ('refclass-features.md', True),
                                     ('refclass-rules.md', False), ('refclass-features.md', False)):
            with self.subTest(name=name, change_version=change_version):
                build(db, bundle(), knowledge)
                source = knowledge / name
                original = source.read_text()
                changed = (original.replace('version 4', 'version 5').replace('version 1', 'version 2')
                           if change_version else original + '\nChanged convention.\n')
                source.write_text(changed)
                output = io.StringIO()
                with patch('refclass.__main__.__file__', str(self.root / 'refclass/__main__.py')), \
                        patch.dict('os.environ', REFCLASS_DB=str(db)), redirect_stdout(output):
                    self.assertEqual(main(['review']), 0)
                lines = output.getvalue().splitlines()
                self.assertEqual(sum('Price review skipped' in line for line in lines), 1)
                self.assertIn('refclass build must be rerun', output.getvalue())
                self.assertIn('disputed | assertions.first_product true -> false', output.getvalue())
                source.write_text(original)


if __name__ == '__main__':
    unittest.main()
