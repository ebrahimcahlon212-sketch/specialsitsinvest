"""Regression cases from docs/build/review-1.md. All inputs are offline test data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tests.support import ROOT, bundle
from refclass.background import launch
from refclass.engine import build, report
from refclass.jobs import job_key
from refclass.locking import job_lock
from refclass.quality import GateError, listing, validate

sys.path.insert(0, str(ROOT / "lib"))
import calc
import catalysts
import upgrade


def evidence():
    return {k: {"not_applicable": "No such metric in this test document"} for k in
            ("units", "staleness", "listing", "attribution", "date_type", "arithmetic", "partial_tender")}


class ReviewFixes(unittest.TestCase):
    def test_rounded_percent_passes_but_material_error_fails(self):
        data = evidence()
        data["arithmetic"] = [dict(kind="return", inputs=dict(pre=35.89, post=43.51), reported=.2123)]
        validate(data)
        data["arithmetic"][0]["reported"] = .2124
        with self.assertRaises(GateError):
            validate(data)
        data = evidence()
        data["partial_tender"] = dict(price=100, tender_price=137, entitlement=.12345,
                                      residual_price=90, headline_return=-.0420)
        validate(data)  # -0.0419785 rounded to two decimal percentage points.
        data["partial_tender"]["headline_return"] = -.0419
        with self.assertRaises(GateError):
            validate(data)

    def test_default_blocks_publication_but_allows_research_and_produced_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            raw, final = path / "raw.txt", path / "report.md"
            raw.write_text("<<<BEGIN OUTPUT>>>\nResearch\n<<<END OUTPUT>>>\n")
            final.write_text("Existing\n")
            env = dict(os.environ)
            env.pop("QUALITY_GATES", None)
            cmd = [sys.executable, str(ROOT / "lib/extract_output.py"), str(raw), str(final)]
            blocked = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual(final.read_text(), "Existing\n")
            research = subprocess.run(cmd + ["research"], env=env, capture_output=True, text=True)
            self.assertEqual(research.returncode, 0, research.stderr)
            raw.write_text(raw.read_text() + "<<<BEGIN QUALITY>>>\n" + json.dumps(evidence()) + "\n<<<END QUALITY>>>\n")
            published = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertEqual(published.returncode, 0, published.stderr)
            self.assertEqual(final.read_text(), "Research\n")
            self.assertTrue(Path(str(final) + ".quality.json").exists())
            raw.write_text(raw.read_text().replace(json.dumps(evidence()), "{}"))
            self.assertNotEqual(subprocess.run(cmd, env=env, capture_output=True).returncode, 0)
            self.assertEqual(final.read_text(), "Research\n")

    def test_partial_tender_requires_explicit_expectation_and_respects_residual(self):
        terms = dict(target_ticker="ABC", cash_per_share=137, currency="USD",
                     tender=dict(price=137, shares_sought=10, shares_outstanding=100,
                                 back_end_prices={"down": 80, "flat": 100}))
        result, warnings = calc.compute(terms, {"ABC": {"price": 100}})
        self.assertNotIn("headline_return", result["tender"])
        self.assertIn("expected_entitlement", " ".join(warnings))
        terms["tender"]["expected_entitlement"] = .2
        result, warnings = calc.compute(terms, {"ABC": {"price": 100}})
        self.assertNotIn("headline_return", result["tender"])
        terms["tender"]["back_end_prices"] = {"down": 80}
        result, _ = calc.compute(terms, {"ABC": {"price": 100}})
        self.assertAlmostEqual(result["tender"]["headline_return"], -.086)
        terms["tender"]["expected_residual_price"] = 90
        result, _ = calc.compute(terms, {"ABC": {"price": 100}})
        self.assertAlmostEqual(result["tender"]["headline_return"], -.006)

    def test_lock_is_per_job_and_reads_are_unlocked(self):
        self.assertEqual(job_key(["savara"]), job_key(["savara", "run"]))
        self.assertNotEqual(job_key(["savara"]), job_key(["uncy"]))
        for args in (["savara", "ask"], ["savara", "view"], ["savara", "ledger", "verify"], ["knowledge"]):
            self.assertIsNone(job_key(args))
        with tempfile.TemporaryDirectory() as tmp:
            with job_lock(Path(tmp) / job_key(["savara"])):
                with job_lock(Path(tmp) / job_key(["uncy"])):
                    pass

    def test_upgrade_seeds_rules_without_overwriting_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kit = root / "kit"
            (kit / "knowledge").mkdir(parents=True)
            existing = kit / "knowledge/refclass-rules.md"
            existing.write_text("Investor's versioned rules")
            archive = root / "kit.zip"
            with zipfile.ZipFile(archive, "w") as z:
                for name in upgrade.SEED_ONLY:
                    z.writestr("special-sits-kit/" + name, "New bundled content")
                z.writestr("special-sits-kit/knowledge/research-standards.md", "Do not install")
            upgrade.install(str(kit), str(archive))
            self.assertEqual(existing.read_text(), "Investor's versioned rules")
            self.assertEqual((kit / "knowledge/refclass-features.md").read_text(), "New bundled content")
            self.assertFalse((kit / "knowledge/research-standards.md").exists())

    def test_catalyst_render_keeps_other_records_and_flags_bad_record(self):
        good = dict(id="one", company="Test", ticker="TEST", anchor_value=10, anchor_currency="GBP",
                    price=800, currency="GBp", date="2026-11-20")
        bad = dict(good, id="two", anchor_currency="JPY")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(catalysts, "preflight"), patch.object(catalysts, "load_state", return_value={}), \
                 patch.object(catalysts, "open_items", return_value=[good, bad]):
                catalysts.cmd_render(tmp)
            markdown = (Path(tmp) / "catalysts.md").read_text()
            page = (Path(tmp) / "catalysts.html").read_text()
            self.assertIn("20%", markdown)
            self.assertIn("JPY", markdown)
            self.assertIn("Calculation blocked", page)

    def test_background_launcher_logs_and_holds_lock_without_starting_a_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "events.sqlite"
            args = ["build", "--db", str(db)]
            with job_lock(str(db) + ".job.lock"):
                with self.assertRaisesRegex(ValueError, "already running"):
                    launch(args, root, root / "logs")
            def mock_start(*args, **kwargs):
                fd = kwargs["pass_fds"][0]
                self.assertGreaterEqual(os.fstat(fd).st_size, 0)
                with self.assertRaises(ValueError):
                    with job_lock(str(db) + ".job.lock"):
                        pass
                self.assertTrue(kwargs["start_new_session"])
                return type("Process", (), {"pid": 123})()
            with patch("refclass.background.subprocess.Popen", side_effect=mock_start):
                pid, log = launch(args, root, root / "logs")
                self.assertEqual(pid, 123)
                self.assertTrue(log.exists())
            with job_lock(str(db) + ".job.lock"):
                pass

    def test_profiles_select_different_classes_without_changing_fixed_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "knowledge", root / "knowledge")
            for name, first in (("one", True), ("two", False)):
                folder = root / "deals" / name
                folder.mkdir(parents=True)
                (folder / "refclass.json").write_text(json.dumps(dict(first_product=first, market_value=1000000,
                    source="test filing", locator="L.1", as_of="2026-10-04")))
            db = root / "events.sqlite"
            build(db, bundle(), root / "knowledge")
            self.assertEqual(report(db, "one", root / "knowledge")["selected_class"], "C")
            self.assertEqual(report(db, "two", root / "knowledge")["selected_class"], "A")
            self.assertIsNotNone(report(db, "missing", root / "knowledge")["profile_gap"])

    def test_synthetic_benchmark_cannot_be_labelled_production(self):
        data = bundle()
        data["fixture"] = False
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Synthetic"):
                build(Path(tmp) / "events.sqlite", data, ROOT / "knowledge")

    def test_q_suffix_uses_fifth_character_and_venue_and_has_review(self):
        listing("NDAQ", "2026-01-01", "2026-10-04", [])
        listing("ABCDQ", "2026-01-01", "2026-10-04", [], venue="NASDAQ")
        with self.assertRaises(GateError):
            listing("ABCDQ", "2026-01-01", "2026-10-04", [], venue="OTC")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "notice.txt"
            source.write_text("ABCDQ listing notice")
            review = dict(source=str(source), line_start=1, line_end=1, reason="Investor reviewed notice")
            listing("ABCDQ", "2026-01-01", "2026-10-04", [], venue="OTC", suffix_review=review)
            with self.assertRaises(GateError):
                listing("ABCDQ", "2026-01-01", "2026-10-04", [{"date": "2026-05-01", "items": ["1.03"]}],
                        venue="OTC", suffix_review=review)

    def test_production_evidence_is_reread_and_latest_supplied_share_filing_selected(self):
        from refclass.provenance import eligibility_gap, shares_verified
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "filing.txt"
            source.write_text("TEST listed on NASDAQ.\nSponsor is the applicant for Drug.\nSponsor has 10,000,000 shares outstanding.\n")
            event = dict(ticker="TEST", company="Sponsor", applicant="Sponsor", drug="Drug", announced_at="2025-01-01",
                         listing_evidence=dict(source=str(source), line_start=1, line_end=1, venue="NASDAQ",
                                               valid_from="2024-01-01", valid_through="2025-02-01"),
                         applicant_evidence=dict(source=str(source), line_start=2, line_end=2),
                         shares=10000000, shares_as_of="2024-06-30", shares_source=str(source),
                         share_filings=[dict(source=str(source), line_start=3, line_end=3, filed_at="2024-08-01",
                                             as_of="2024-06-30", shares=10000000)])
            self.assertIsNone(eligibility_gap(event))
            self.assertTrue(shares_verified(event))
            event["share_filings"].append(dict(event["share_filings"][0], filed_at="2024-11-01", as_of="2024-09-30"))
            self.assertFalse(shares_verified(event))
            event["applicant"] = "Competitor"
            self.assertIsNotNone(eligibility_gap(event))
            event["applicant"] = "Sponsor"
            source.write_text("TEST listed on London Stock Exchange.\nSponsor is applicant for Drug.\nWrong count.\n")
            self.assertIsNotNone(eligibility_gap(event))
            self.assertFalse(shares_verified(event))
