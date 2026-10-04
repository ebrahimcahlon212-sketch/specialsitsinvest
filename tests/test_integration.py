import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.support import ROOT

sys.path.insert(0, str(ROOT / "lib"))
import calc
import catalysts
from refclass.locking import job_lock


class IntegrationTests(unittest.TestCase):
    def test_publication_gate_stops_before_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "raw.txt").write_text("<<<BEGIN OUTPUT>>>\nNew report\n<<<END OUTPUT>>>\n")
            (path / "report.md").write_text("Existing report\n")
            (path / "quality.json").write_text("{}")
            proc = subprocess.run([sys.executable, str(ROOT / "lib/extract_output.py"),
                                   str(path / "raw.txt"), str(path / "report.md")],
                                  capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("Quality gate", proc.stderr)
            self.assertEqual((path / "report.md").read_text(), "Existing report\n")

    def test_legacy_extractor_and_strict_missing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "raw.txt").write_text("<<<BEGIN OUTPUT>>>\nReport\n<<<END OUTPUT>>>\n")
            cmd = [sys.executable, str(ROOT / "lib/extract_output.py"), str(path / "raw.txt"), str(path / "report.md")]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  env={**os.environ, "QUALITY_GATES": "legacy"})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual((path / "report.md").read_text(), "Report\n")
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  env={**os.environ, "QUALITY_GATES": "strict"})
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("missing", proc.stderr)

    def test_run_sh_duplicate_refused_before_any_job(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            kit = Path(tmp)
            shutil.copy2(ROOT / "run.sh", kit / "run.sh")
            shutil.copytree(ROOT / "refclass", kit / "refclass")
            with job_lock(kit / ".locks" / "run.lock"):
                proc = subprocess.run(["bash", str(kit / "run.sh"), "savara"], capture_output=True, text=True)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("already running", proc.stderr)
                self.assertFalse((kit / "knowledge").exists())

    def test_currency_gate_at_existing_catalyst_calculator(self):
        record = dict(anchor_value=10, anchor_currency="GBP", price=800, currency="GBp", date="2026-11-20")
        self.assertAlmostEqual(catalysts.numbers(record)["discount"], .2)
        self.assertAlmostEqual(catalysts.numbers(record)["upside"], .25)
        with self.assertRaises(ValueError):
            catalysts.numbers(dict(record, anchor_currency="GBp"))

    def test_legacy_merger_calculation(self):
        res, warnings = calc.compute({"target_ticker": "ABC", "cash_per_share": 12, "currency": "USD"},
                                     {"ABC": {"price": 10}})
        self.assertEqual(res["deal_value"], 12)
        self.assertAlmostEqual(res["spread_pct"], .2)

    def test_partial_tender_headline_is_whole_holding(self):
        terms = {"target_ticker": "ABC", "cash_per_share": 137, "currency": "USD",
                 "tender": {"price": 137, "shares_sought": 10, "shares_outstanding": 100,
                            "back_end_prices": {"current": 100}}}
        result, warnings = calc.compute(terms, {"ABC": {"price": 100}})
        self.assertAlmostEqual(result["tender"]["headline_return"], .037)
        markdown = calc.to_markdown(result, warnings, terms)
        self.assertIn("Whole-holding return at expected entitlement", markdown)
        self.assertIn("3.70%", markdown)

    def test_upgrades_include_new_package(self):
        import upgrade
        self.assertIn("refclass/", upgrade.PROGRAM)
        self.assertIn("tests/", upgrade.PROGRAM)
