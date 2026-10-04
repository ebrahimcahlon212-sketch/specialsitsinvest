import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from refclass.math import abnormal_return, convert, posterior, raw_return, wilson
from refclass.quality import (GateError, arithmetic, attribution, decision_date,
                             discount, freshness, listing, runway, validate, whole_holding)
from refclass.locking import job_lock


class MathTests(unittest.TestCase):
    def test_odds_not_probability_multiplication(self):
        self.assertAlmostEqual(posterior(.8, [2, .5, 3]), 12 / 13)
        self.assertEqual(posterior(0, [2]), 0)
        self.assertEqual(posterior(1, [2]), 1)

    def test_wilson_90_percent(self):
        low, high = wilson(5, 10)
        self.assertAlmostEqual(low, .2692718211)
        self.assertAlmostEqual(high, .7307281789)
        self.assertIsNone(wilson(0, 0))
        self.assertAlmostEqual(wilson(0, 10)[0], 0)
        for counts in ((11, 10), (-1, 10), (1.5, 10)):
            with self.assertRaises(ValueError):
                wilson(*counts)

    def test_returns_and_bad_numbers(self):
        self.assertAlmostEqual(raw_return(10, 12), .2)
        self.assertAlmostEqual(abnormal_return(10, 12, 100, 105), .15)
        for bad in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                raw_return(bad, 12)

    def test_currency_and_units(self):
        self.assertEqual(convert(100, "GBp", "GBP"), Decimal("1"))
        self.assertEqual(convert(10, "USD", "GBp", {("USD", "GBP"): ".8"}), Decimal("800"))
        with self.assertRaises(ValueError):
            convert(10, "USD", "GBP")

    def test_json_fx_rates(self):
        self.assertEqual(convert(10, "USD", "GBp", [{"from": "USD", "to": "GBP", "rate": ".8"}]), Decimal("800"))
        with self.assertRaises(ValueError):
            convert(10, "USD", "GBP", [{"from": "USD", "to": "GBP", "rate": ".8"},
                                         {"from": "USD", "to": "GBP", "rate": ".7"}])


class QualityTests(unittest.TestCase):
    def test_discount_converts_and_flags_extremes(self):
        self.assertAlmostEqual(discount(10, "GBP", 800, "GBp"), .2)
        for price in (1, 151):
            with self.assertRaises(GateError):
                discount(100, "USD", price, "USD")

    def test_stale_cash_and_shares(self):
        freshness("2026-06-30", "2026-08-01", "2026-06-30")
        for cash, shares in (("2019-12-31", "2026-07-01"), ("2026-06-30", "2026-03-31")):
            with self.assertRaises(GateError):
                freshness(cash, shares, "2026-06-30")

    def test_listing_suffix_and_bankruptcy(self):
        listing("ABC", "2026-01-01", "2026-10-04", [])
        for ticker, filings in (("ABCDQ", []), ("ABC", [{"date": "2026-08-01", "items": ["1.03"]}])):
            with self.assertRaises(GateError):
                listing(ticker, "2026-01-01", "2026-10-04", filings)

    def test_attribution_requires_locator(self):
        attribution("Sponsor", "Sponsor")
        attribution("Sponsor", "Partner", {"source": "contract", "locator": "L.1"})
        for source in (None, "vague claim", {"source": "contract"}):
            with self.assertRaises(GateError):
                attribution("Sponsor", "Competitor", source)

    def test_date_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "deals/test/filings/announcement.txt"
            source.parent.mkdir(parents=True)
            source.write_text("FDA approved the drug on 2026-10-04.\nThe PDUFA goal date is 2026-11-20.\nSubmitted on 2026-10-01.")
            evidence = dict(source=str(source), line_start=1, line_end=3)
            decision_date("fda_action", "2026-10-04", evidence)
            decision_date("fda_goal", "2026-11-20", evidence)
            with self.assertRaises(GateError):
                decision_date("fda_goal", "2026-10-01", evidence)
            with self.assertRaises(GateError):
                decision_date("fda_goal")
        for kind in ("submission", "readout", "expected_acceptance"):
            with self.assertRaises(GateError):
                decision_date(kind)

    def test_arithmetic_includes_all_securities(self):
        self.assertEqual(runway(10, 20, 30, 5), 12)
        arithmetic(12, runway(10, 20, 30, 5))
        with self.assertRaises(GateError):
            arithmetic(6, runway(10, 20, 30, 5))

    def test_structured_arithmetic_recomputes_returns_and_expected_values(self):
        evidence = {key: {"not_applicable": "test"} for key in
                    ("units", "staleness", "listing", "attribution", "date_type", "partial_tender")}
        evidence["arithmetic"] = [
            {"kind": "return", "inputs": {"pre": 100, "post": 120}, "reported": .2},
            {"kind": "annualized_return", "inputs": {"pre": 100, "post": 120,
             "as_of": "2026-01-01", "payout": "2027-01-01"}, "reported": .2},
            {"kind": "expected_value", "inputs": {"outcomes": [
                {"probability": .8, "value": 12}, {"probability": .2, "value": 2}]}, "reported": 10}]
        self.assertEqual(validate(evidence)["arithmetic"], "passed")
        evidence["arithmetic"][2]["inputs"]["outcomes"][1]["probability"] = .3
        with self.assertRaises(GateError):
            validate(evidence)

    def test_partial_tender_is_whole_holding(self):
        self.assertAlmostEqual(whole_holding(100, 137, .1, 100), .037)
        evidence = {key: {"not_applicable": "test"} for key in
                    ("units", "staleness", "listing", "attribution", "date_type", "arithmetic")}
        evidence["arithmetic"] = [dict(kind="return", inputs=dict(pre=100, post=137), reported=.37)]
        evidence["partial_tender"] = dict(price=100, tender_price=137, entitlement=.1,
                                          residual_price=100, headline_return=.37)
        with self.assertRaises(GateError):
            validate(evidence)
        evidence["partial_tender"]["headline_return"] = .037
        self.assertAlmostEqual(validate(evidence)["partial_tender"], .037)

    def test_missing_evidence_blocks(self):
        with self.assertRaises(GateError):
            validate({})

    def test_lock_refuses_duplicate_and_releases_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "job.lock"
            with self.assertRaisesRegex(RuntimeError, "test"):
                with job_lock(lock):
                    with self.assertRaisesRegex(ValueError, "already running"):
                        with job_lock(lock):
                            self.fail("duplicate accepted")
                    raise RuntimeError("test")
            with job_lock(lock):
                self.assertTrue(lock.exists())
