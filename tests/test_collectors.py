"""Real-response replay and failure cases. Tests never call a live service."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from refclass.collectors import fda, edgar
from refclass.collectors.http import Client, CollectionError, saved_contact
from tests.support import ROOT

CACHE = ROOT / 'tests/fixtures/collectors'
QUERY = 'application_number:NDA* AND submissions.submission_status_date:[20250101 TO 20261004]'


def fixture_client():
    client = Client(CACHE, offline=True, opener=lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Network attempted')))
    return client


class RealResponseTests(unittest.TestCase):
    def test_all_saved_responses_are_dated_and_checksums_match(self):
        client = fixture_client()
        for record in client.records:
            with self.subTest(record['url']):
                raw, source = client.get(record['url'])
                self.assertTrue(source['downloaded_at'].startswith('2026-10-04'))
                self.assertEqual(len(raw), source['bytes'])
                self.assertLess(len(raw), 1_000_000)
                self.assertNotIn('User-Agent', source)

    def test_drugsfda_original_actions_not_supplements_or_search_match_dates(self):
        with self.assertRaises(CollectionError):
            fda.collect(fixture_client(), 'drugs_at_fda', page_size=2, search=QUERY, until='2026-10-04')
        result = fda.collect(fixture_client(), 'drugs_at_fda', since='2025-01-01', page_size=2, search=QUERY, until='2026-10-04')
        self.assertFalse(result['complete'])
        self.assertGreater(result['gap_count'], 0)
        for candidate in result['candidates']:
            self.assertTrue(candidate['original'])
            self.assertIsNone(candidate['announced_at'])
            self.assertEqual(candidate['status'], 'pending')
        # Replay the historical conflicting request only to test action parsing.
        client = fixture_client()
        record = next(r for r in client.records if '20250101' in r['url'] and '20150101' in r['url'])
        data, origin = client.json(record['url'])
        rows = [c for i, r in enumerate(data['results']) for c in fda.approvals(r, origin, i)]
        self.assertIn('2020-08-04', [r['action_date'] for r in rows])

    def test_crl_retains_letter_not_later_approval_and_excludes_supplement(self):
        result = fda.collect(fixture_client(), 'openfda_crl', page_size=2, until='2026-10-04')
        self.assertEqual(result['excluded'], 1)
        self.assertEqual(result['candidate_count'], 1)
        row = result['candidates'][0]
        self.assertEqual((row['event_type'], row['application'], row['action_date']), ('crl', 'BLA761082', '2019-06-11'))
        self.assertIn('COMPLETE RESPONSE', row['text'])
        self.assertIsNone(row['original'])
        self.assertIsNone(row['announced_at'])

    def test_edgar_primary_and_real_exhibit_and_separate_filing_timestamp(self):
        result = edgar.collect(fixture_client(), '1160308', since='2025-10-30', until='2025-10-30', max_history=0, max_exhibits=1)
        self.assertEqual(result['gaps'], [])
        self.assertTrue(result['complete'])
        self.assertEqual(result['filing_count'], 1)
        row = result['filings'][0]
        self.assertEqual(row['accessionNumber'], '0001193125-25-258629')
        self.assertEqual([d['form'] for d in row['documents']], ['8-K', 'EX-99.1'])
        self.assertTrue(row['acceptanceDateTime'])
        self.assertEqual(row['announced_at'], row['acceptanceDateTime'])
        for doc in row['documents']:
            for signal in doc['signals']:
                self.assertEqual(doc['text'].splitlines()[signal['line'] - 1], signal['text'])
        self.assertIn('offering', {k for d in row['documents'] for s in d['signals'] for k in s['kinds']})

    def test_edgar_limits_and_empty_window_are_explicit(self):
        result = edgar.collect(fixture_client(), '1160308', since='2026-09-01', until='2026-10-04', max_history=0)
        self.assertEqual(result['filing_count'], 0)
        self.assertTrue(result['complete'])
        result = edgar.collect(fixture_client(), '1160308', since='2025-01-01', until='2026-10-04', max_filings=0, max_history=0)
        self.assertGreater(result['inventory_count'], 0)
        self.assertGreater(result['gap_count'], 0)
        self.assertFalse(result['complete'])
        result = edgar.collect(fixture_client(), '1160308', since='2025-10-30', until='2025-10-30', max_history=0, max_exhibits=0)
        self.assertIn('Exhibit bound', ' '.join(result['gaps']))

    def test_offline_cli_writes_staging_and_reports_partial_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'collected.json'
            cache = Path(tmp) / 'cache'
            shutil.copytree(CACHE, cache, ignore=shutil.ignore_patterns('*.lock'))
            result = subprocess.run([sys.executable, '-m', 'refclass', 'collect', 'drugs_at_fda',
                                     '--offline', '--cache', str(cache), '--output', str(out),
                                     '--page-size', '2', '--search', QUERY, '--since', '2025-01-01', '--until', '2026-10-04'],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            data = json.loads(out.read_text())
            self.assertEqual(data['stage'], 'source_candidates_not_verified_events')
            self.assertGreaterEqual(data['candidate_count'], 0)
            self.assertNotIn('missing from offline', ' '.join(data['gaps']))
            result = subprocess.run([sys.executable, '-m', 'refclass', 'collect', 'edgar', '--offline',
                                     '--cache', str(cache), '--output', str(out), '--cik', '1160308',
                                     '--since', '2025-10-30', '--until', '2025-10-30', '--max-history', '0', '--max-exhibits', '1'],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(out.read_text())['filing_count'], 1)


class Response:
    status = 200
    headers = {'Content-Type': 'application/json'}
    def __init__(self, raw): self.raw = raw
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit): return self.raw[:limit]


class TransportTests(unittest.TestCase):
    def test_saved_contact_literal_and_sec_user_agent_rate_limit(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SEC_CONTACT': ''}):
            settings = Path(tmp) / 'settings.env'
            settings.write_text('SEC_CONTACT="Analyst $literal analyst@test.invalid"\n')
            contact = saved_contact(settings)
            self.assertIn('$literal', contact)
            requests, sleeps = [], []
            def open_(request, timeout):
                requests.append(request)
                return Response(b'{}')
            client = Client(tmp, contact=contact, opener=open_, sleep=sleeps.append, clock=lambda: 10)
            client.get('https://data.sec.gov/submissions/CIK0001160308.json')
            client.get('https://www.sec.gov/Archives/test.txt')
            self.assertEqual([r.get_header('User-agent') for r in requests], [contact, contact])
            self.assertEqual(sleeps, [.25])
            self.assertNotIn(contact, (Path(tmp) / 'manifest.json').read_text())

    def test_missing_contact_no_request_and_bad_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = Client(tmp, opener=lambda *a, **kw: self.fail('Network attempted'))
            for url in ('https://data.sec.gov/submissions/CIK0001160308.json', 'https://evil.test/', 'http://api.fda.gov/', 'https://api.fda.gov:444/'):
                with self.assertRaises(CollectionError): client.get(url)

    def test_bounded_response_not_saved_and_corrupt_cache_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = Client(tmp, max_bytes=2, opener=lambda *a, **kw: Response(b'123'))
            with self.assertRaisesRegex(CollectionError, 'byte limit'):
                client.get('https://api.fda.gov/drug/drugsfda.json')
            self.assertFalse((Path(tmp) / 'manifest.json').exists())
            client = Client(tmp, opener=lambda *a, **kw: Response(b'{}'))
            url = 'https://api.fda.gov/drug/drugsfda.json'
            _, origin = client.get(url)
            Path(origin['source']).write_text('corrupt')
            with self.assertRaisesRegex(CollectionError, 'checksum'):
                Client(tmp, offline=True).get(url)

    def test_rate_limit_retry_and_http_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempts, sleeps = [], []
            def open_(req, timeout):
                attempts.append(req)
                if len(attempts) == 1:
                    raise urllib.error.HTTPError(req.full_url, 429, 'rate limit', {'Retry-After': '1'}, io.BytesIO())
                return Response(b'{}')
            client = Client(tmp, opener=open_, sleep=sleeps.append, clock=lambda: 10)
            client.get('https://api.fda.gov/drug/drugsfda.json')
            self.assertEqual(len(attempts), 2)
            self.assertEqual(sleeps, [1, .25])
            def forbidden(req, timeout):
                raise urllib.error.HTTPError(req.full_url, 403, 'forbidden', {}, io.BytesIO())
            client.opener = forbidden
            result = fda.collect(client, 'openfda_crl')
            self.assertGreater(result['gap_count'], 0)
            self.assertIn('403', ' '.join(result['gaps']))


class ParserFailures(unittest.TestCase):
    def test_pagination_dedup_parse_errors_and_empty_response(self):
        original = fda.collect(fixture_client(), 'drugs_at_fda', since='2025-01-01', page_size=2, search=QUERY, until='2026-10-04')
        origin = original['responses'][0]
        data = json.loads(Path(origin['source']).read_text())
        row = data['results'][1]
        class Fake:
            calls = 0
            def json(self, url):
                self.calls += 1
                return {'meta': {'results': {'total': 2}}, 'results': [row]}, origin
        fake = Fake()
        result = fda.collect(fake, 'drugs_at_fda', page_size=1, max_pages=2, until='2026-10-04')
        self.assertEqual(fake.calls, 2)
        self.assertEqual(result['candidate_count'], 1)
        self.assertTrue(result['complete'])
        with patch.object(fake, 'json', return_value=({'results': [{}], 'meta': {'results': {'total': 1}}}, origin)):
            self.assertGreater(fda.collect(fake, 'drugs_at_fda')['gap_count'], 0)
        with patch.object(fake, 'json', return_value=({'error': {'code': 'NOT_FOUND'}}, origin)):
            self.assertTrue(fda.collect(fake, 'drugs_at_fda')['complete'])
        with patch.object(fake, 'json', return_value=({'unexpected': []}, origin)):
            self.assertGreater(fda.collect(fake, 'drugs_at_fda')['gap_count'], 0)

    def test_edgar_history_is_paged_and_failures_counted(self):
        real = fixture_client()
        url = 'https://data.sec.gov/submissions/CIK0001160308.json'
        data, origin = real.json(url)
        old = copy.deepcopy(data['filings']['recent'])
        data = copy.deepcopy(data)
        data['filings']['recent'] = {k: [] for k in old}
        data['filings']['files'] = [dict(name='CIK0001160308-submissions-001.json', filingFrom='2025-01-01', filingTo='2026-01-01')]
        class Fake:
            def json(self, wanted): return (data if wanted == url else old), origin
            def get(self, wanted): return real.get(wanted)
        result = edgar.collect(Fake(), '1160308', since='2025-10-30', until='2025-10-30', max_exhibits=1)
        self.assertEqual(result['filing_count'], 1)
        self.assertEqual(result['gaps'], [])
        data['filings']['files'][0]['name'] = '../../secrets'
        self.assertGreater(edgar.collect(Fake(), '1160308')['gap_count'], 0)
        with self.assertRaises(CollectionError): edgar.inventory({'form': []})
        with self.assertRaises(CollectionError): edgar.inventory(dict(form=[], accessionNumber=['x'], filingDate=[], primaryDocument=[]))
        with self.assertRaises(CollectionError): edgar.cik_number('../1')
