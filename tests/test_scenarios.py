"""Offline persistence checks using only supplied hypothetical calculation data."""

import json
from decimal import Decimal

import pytest

from app import cases, db
from test_calc import ratio, tender, worksheet


@pytest.fixture
def saved_case(tmp_path):
    db.initialize(tmp_path)
    record = cases.create_case(tmp_path, "Hypothetical calculation case")
    return tmp_path, record["id"]


def tender_row(inputs, probability=None):
    return {"name": "Hypothetical scenario", "inputs": inputs.model_dump(mode="json"),
            "probability": ratio(probability).model_dump(mode="json") if probability is not None else None,
            "duration_days": "30", "withholding_basis": "Supplied hypothetical assumption",
            "broker_confirmation": ""}


def assert_decimal_text(value):
    if isinstance(value, dict):
        if "value" in value:
            assert value["value"] is None or isinstance(value["value"], str)
        for item in value.values():
            assert_decimal_text(item)
    elif isinstance(value, list):
        for item in value:
            assert_decimal_text(item)


def test_new_saved_calculation_preserves_old_inputs_and_outputs(saved_case, monkeypatch):
    folder, case_id = saved_case
    inputs = worksheet().model_dump(mode="json")
    first = cases.save_scenario(folder, case_id, "Hypothetical valuation", "spinoff", inputs)
    original = json.loads(json.dumps(first))
    inputs["profit"]["value"] = "60"
    second = cases.save_scenario(folder, case_id, "Hypothetical valuation", "spinoff", inputs)
    assert first["id"] != second["id"]
    assert Decimal(first["outputs"]["base"]["value_per_share"]["value"]) == Decimal("14")
    assert Decimal(second["outputs"]["base"]["value_per_share"]["value"]) == Decimal("18")
    # Reading persisted results must not recompute them after calculator changes.
    monkeypatch.setattr(cases, "calculate_scenario", lambda *_: pytest.fail("Saved records were recalculated"))
    reopened = cases.list_scenarios(folder, case_id)
    assert next(record for record in reopened if record["id"] == first["id"]) == original
    assert_decimal_text(reopened)


def test_tender_precision_and_assumptions_survive_reopening(saved_case):
    folder, case_id = saved_case
    row = tender_row(tender("99", "1", ".15", None, "3.00"))
    saved = cases.save_scenario(folder, case_id, "Hypothetical A1", "tender", {"scenarios": [row]})
    reopened = cases.list_scenarios(folder, case_id)[0]
    assert reopened == saved
    assert Decimal(reopened["outputs"]["0"]["initial_cost"]["value"]) == Decimal("1442.064")
    assert reopened["display"]["0"]["scenario_profit"] == "GBP -132.32"
    assert reopened["display"]["0"]["scenario_return"] == "-9.18%"
    assert reopened["inputs"]["scenarios"][0]["withholding_basis"] == row["withholding_basis"]
    assert reopened["inputs"]["scenarios"][0]["duration_days"] == "30"
    assert "expected" not in reopened["outputs"]
    assert "probability_1 is unknown" in reopened["warning"]
    assert_decimal_text(reopened)


def test_expected_profit_uses_supplied_examples():
    rows = [tender_row(tender("250", ".403", ".15", "17.50", "6.00"), ".8"),
            tender_row(tender("250", "0", ".15", "16.80", "3.00"), ".2")]
    result = cases.calculate_scenario("tender", {"scenarios": rows})
    assert Decimal(result["outputs"]["expected"]["expected_profit"]["value"]) == Decimal("-288.40")
    assert result["display"]["expected"]["expected_profit"] == "GBP -288.40"
    rows[1]["probability"] = ratio(".1").model_dump(mode="json")
    invalid = cases.calculate_scenario("tender", {"scenarios": rows})
    assert "expected" not in invalid["outputs"]
    assert "probabilities must sum to one" in invalid["warning"]
    assert invalid["outputs"]["0"] == result["outputs"]["0"]
    assert invalid["outputs"]["1"] == result["outputs"]["1"]


def test_unknown_required_input_does_not_save_a_false_result(saved_case):
    folder, case_id = saved_case
    inputs = worksheet().model_dump(mode="json")
    inputs["profit"]["value"] = None
    with pytest.raises(ValueError, match="cannot calculate: profit is unknown"):
        cases.save_scenario(folder, case_id, "Unknown hypothetical profit", "spinoff", inputs)
    assert cases.list_scenarios(folder, case_id) == []


def test_numeric_quantity_rejected_before_calculation():
    inputs = worksheet().model_dump(mode="json")
    inputs["current_price"]["value"] = 10.0
    with pytest.raises(ValueError, match="Decimal inputs must be text"):
        cases.calculate_scenario("spinoff", inputs)
