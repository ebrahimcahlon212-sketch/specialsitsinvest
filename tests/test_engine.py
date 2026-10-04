import copy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from refclass.engine import build, reaction, report, session_dates, reconcile_tags
from tests.support import ROOT, bundle, comparables


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.sessions = [dict(date=d, open="09:30", close="16:00") for d in
                         ("2025-07-03", "2025-07-07", "2025-07-08", "2025-07-09")]
        self.sessions[0]["close"] = "13:00"

    def test_premarket_holiday_and_weekend(self):
        for time in ("2025-07-07T08:00:00-04:00", "2025-07-05T12:00:00-04:00"):
            self.assertEqual(session_dates(time, self.sessions)[:3],
                             ("2025-07-03", "2025-07-07", "2025-07-08"))

    def test_intraday_uses_previous_close_but_next_day_one(self):
        self.assertEqual(session_dates("2025-07-07T12:00:00-04:00", self.sessions)[:3],
                         ("2025-07-03", "2025-07-08", "2025-07-09"))

    def test_after_close_unknown_and_timezone(self):
        for time in ("2025-07-07", "2025-07-07T20:30:00+00:00"):
            self.assertEqual(session_dates(time, self.sessions)[:3],
                             ("2025-07-07", "2025-07-08", "2025-07-09"))
        self.assertTrue(session_dates("2025-07-07", self.sessions)[3])
        with self.assertRaisesRegex(ValueError, "timezone"):
            session_dates("2025-07-07T12:00:00", self.sessions)

    def test_early_close(self):
        self.assertEqual(session_dates("2025-07-03T14:00:00-04:00", self.sessions)[:3],
                         ("2025-07-03", "2025-07-07", "2025-07-08"))


class EngineTests(unittest.TestCase):
    def test_report_fixture_arithmetic_with_synthetic_benchmark(self):
        data = bundle()
        for row, event in zip(comparables(), data["events"]):
            with self.subTest(company=row["company"]):
                r = reaction(event, data["prices"], data["sessions"])
                for name in ("pre", "day1", "day2"):
                    self.assertEqual(f'{r[name + "_close"]:.2f}', row[name + "_close"])
                for day in ("day1", "day2"):
                    self.assertEqual(f'{100 * r[day + "_raw"]:.2f}', row[day + "_percent"])
                self.assertAlmostEqual(r["day1_abnormal"], r["day1_raw"] - .02)
                self.assertAlmostEqual(r["day2_abnormal"], r["day2_raw"] - .01)

    def test_adjusted_prices_not_raw_prices_drive_returns(self):
        data = bundle()
        data["prices"][0]["close"] = 146.9
        self.assertAlmostEqual(reaction(data["events"][0], data["prices"], data["sessions"])["day1_raw"],
                               15.44 / 14.69 - 1)

    def test_missing_bar_does_not_shift_session(self):
        data = bundle()
        data["prices"] = [p for p in data["prices"] if not (p["ticker"] == "VRNA" and p["date"] == "2024-06-27")]
        result = reaction(data["events"][0], data["prices"], data["sessions"])
        self.assertEqual(result["status"], "unpriced")
        self.assertIn("2024-06-27", result["reason"])

    def test_missing_benchmark_and_unknown_time(self):
        data = bundle()
        r = reaction(data["events"][0], [p for p in data["prices"] if p["ticker"] != "XBI"], data["sessions"])
        self.assertEqual(r["status"], "unpriced")
        self.assertTrue(r["unknown_time"])

    def test_nested_counts_exclusions_unpriced_and_updates(self):
        data = bundle()
        data["events"][1]["first_product"] = False
        data["events"][2]["shares"] = 100000000
        missing = dict(data["events"][0], event_id="delisted", ticker="OLD", event_type="crl")
        excluded = dict(missing, event_id="supplement", original=False)
        data["events"] += [missing, excluded]
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "refclass.sqlite"
            build(db, data, ROOT / "knowledge")
            result = report(db, "savara", ROOT / "knowledge")
            self.assertEqual(result["found"], 6)
            self.assertEqual(result["excluded"], 1)
            self.assertEqual(result["unpriced"], 1)
            self.assertEqual([c["count"] for c in result["classes"]], [5, 4, 2])
            self.assertEqual(result["classes"][0]["crl"]["count"], 1)
            self.assertIn("rules_sha256", result)
            self.assertTrue(result["fixture"])
            build(db, data, ROOT / "knowledge")
            self.assertEqual(report(db, "savara", ROOT / "knowledge")["found"], 6)
            with closing(sqlite3.connect(db)) as connection:
                for table in ("events", "prices", "tags", "reactions"):
                    connection.execute("SELECT * FROM " + table)

    def test_market_value_strict_boundary_and_missing_shares(self):
        data = bundle()
        data["events"] = data["events"][:1]
        data["events"][0]["shares"] = 3000000000 / 14.69
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "r.sqlite"
            build(db, data, ROOT / "knowledge")
            self.assertEqual(report(db, "savara", ROOT / "knowledge")["classes"][2]["count"], 0)
            data["events"][0]["shares"] = None
            build(db, data, ROOT / "knowledge")
            self.assertEqual(report(db, "savara", ROOT / "knowledge")["classes"][2]["count"], 0)

    def test_confounder_sensitivity_and_thin_class(self):
        data = bundle()
        data["events"][0]["same_day_news"] = True
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "r.sqlite"
            build(db, data, ROOT / "knowledge")
            result = report(db, "savara", ROOT / "knowledge")
            broad = result["classes"][0]
            self.assertTrue(broad["thin"])
            self.assertEqual(broad["approval"]["day2_abnormal"]["n"], 4)
            self.assertEqual(broad["without_same_day_news"]["approval"]["day2_abnormal"]["n"], 3)

    def test_rule_changes_require_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for name in ("refclass-rules.md", "refclass-features.md"):
                (path / name).write_text((ROOT / "knowledge" / name).read_text())
            db = path / "r.sqlite"
            build(db, bundle(), path)
            with (path / "refclass-rules.md").open("a") as handle:
                handle.write("\nChanged rules\n")
            with self.assertRaisesRegex(ValueError, "changed"):
                report(db, "savara", path)

    def test_failed_import_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "r.sqlite"
            build(db, bundle(), ROOT / "knowledge")
            invalid = bundle()
            invalid["events"][0]["announced_at"] = "bad"
            with self.assertRaises(ValueError):
                build(db, invalid, ROOT / "knowledge")
            self.assertEqual(report(db, "savara", ROOT / "knowledge")["found"], 4)

    def test_missing_sources_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "r.sqlite"
            build(db, {"as_of": "2026-10-04", "events": [], "prices": [], "sessions": []}, ROOT / "knowledge")
            self.assertEqual(len(report(db, "savara", ROOT / "knowledge")["gaps"]), 4)

    def test_incremental_update_keeps_unpriced_delisted_and_fixture_label(self):
        data = bundle()
        missing = dict(data["events"][0], event_id="old", ticker="OLD", event_type="crl")
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "r.sqlite"
            build(db, data, ROOT / "knowledge")
            build(db, {"as_of": "2026-10-04", "events": [missing]}, ROOT / "knowledge", update=True)
            result = report(db, "savara", ROOT / "knowledge")
            self.assertEqual((result["found"], result["unpriced"]), (5, 1))
            self.assertTrue(result["fixture"])

    def test_offering_five_sessions_and_unknown_coverage(self):
        data = bundle()
        event = data["events"][1]
        sessions = [dict(date=d, open="09:30", close="16:00") for d in
                    ("2025-07-03", "2025-07-07", "2025-07-08", "2025-07-09", "2025-07-10", "2025-07-11", "2025-07-14")]
        event["offering_dates"] = ["2025-07-11"]
        self.assertTrue(reaction(event, data["prices"], sessions)["offering_within_5d"])
        event["offering_dates"] = ["2025-07-14"]
        self.assertFalse(reaction(event, data["prices"], sessions)["offering_within_5d"])
        event.pop("offering_coverage_through")
        self.assertIsNone(reaction(event, data["prices"], sessions)["offering_within_5d"])

    def test_real_tags_cannot_be_self_certified(self):
        data = bundle()
        data["fixture"] = False
        data["prices"] = []  # These tests concern tags, not broker provenance.
        for event in data["events"]:
            event["tags"] = [{"feature": "first_product", "value": "yes", "tagger": "reader-one",
                              "locator": "filing L.1", "agreed": True}]
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "r.sqlite"
            build(db, data, ROOT / "knowledge")
            result = report(db, "savara", ROOT / "knowledge")
            self.assertEqual(result["classes"][1]["count"], 0)
            self.assertEqual(result["excluded"], 4)
            self.assertTrue(all(reconcile_tags(e)["first_product"] is None for e in data["events"]))

    def test_agreed_tags_and_disagreement(self):
        data = bundle()
        data["fixture"] = False
        data["prices"] = []  # These tests concern tags, not broker provenance.
        for event in data["events"]:
            event["tags"] = [{"feature": "first_product", "value": value, "tagger": who,
                              "locator": "filing L.1"} for who, value in (("one", "yes"), ("two", "yes"))]
        data["events"][0]["tags"][1]["value"] = "no"
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "r.sqlite"
            build(db, data, ROOT / "knowledge")
            result = report(db, "savara", ROOT / "knowledge")
            self.assertEqual(result["excluded"], 4)
            self.assertEqual(sum(reconcile_tags(e)["first_product"] is True for e in data["events"]), 3)

    def test_parser_gaps_are_retained(self):
        data = bundle()
        data["gaps"] = ["openfda_crl. One saved response failed parsing"]
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "r.sqlite"
            build(db, data, ROOT / "knowledge")
            self.assertEqual(report(db, "savara", ROOT / "knowledge")["gaps"], data["gaps"])


class CLITests(unittest.TestCase):
    def test_missing_input_records_gap_without_erasing_existing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "r.sqlite"
            missing = Path(tmp) / "missing.json"
            command = ["python3", "-m", "refclass", "build", "--db", str(db), "--input", str(missing)]
            proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertTrue(db.exists())
            result = report(db, "savara", ROOT / "knowledge")
            self.assertEqual(result["found"], 0)
            self.assertGreaterEqual(len(result["gaps"]), 4)
            build(db, bundle(), ROOT / "knowledge")
            subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(report(db, "savara", ROOT / "knowledge")["found"], 4)

    def test_build_show_and_legacy_help_version_offline(self):
        # A temporary kit prevents run.sh's legacy knowledge seeding touching the real notebook.
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            kit = Path(tmp)
            for name in ("run.sh", "VERSION"):
                shutil.copy2(ROOT / name, kit / name)
            for name in ("refclass", "lib", "knowledge"):
                shutil.copytree(ROOT / name, kit / name)
            (kit / "deals" / "savara").mkdir(parents=True)
            source = kit / "fixture.json"
            source.write_text(json.dumps(bundle()))
            for args in (("help",), ("version",), ("refclass", "build", "--foreground", "--input", str(source)),
                         ("refclass", "show", "savara")):
                proc = subprocess.run(["bash", str(kit / "run.sh"), *args], capture_output=True, text=True,
                                      timeout=20, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                if args[0] == "refclass":
                    self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
                    self.assertIn("synthetic fixture", proc.stderr)
                    self.assertEqual(proc.stdout, "")
                else:
                    self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
