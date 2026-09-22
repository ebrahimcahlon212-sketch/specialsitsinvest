"""BUILD_PLAN section 8 hypothetical examples and clearly synthetic invalid inputs."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.calc import (Claim, Quantity, SpinoffInputs, TenderInputs, expected_profit,
                      format_gbp, format_percentage, format_price,
                      spinoff_valuation, tender_scenario)


def quantity(value, unit, currency=None, *, context=False):
    return Quantity(value=Decimal(value) if value is not None else None, unit=unit,
                    currency=currency, entity="Hypothetical SpinCo" if context else None,
                    period="Hypothetical pro forma period" if context else None)


def money(value):
    return quantity(value, "million_currency_units", "USD", context=True)


def ratio(value):
    return quantity(value, "unitless")


def worksheet():
    return SpinoffInputs(
        profit=money("50"), profit_measure="ebitda", multiple_measure="ebitda",
        multiples={"low": ratio("6"), "base": ratio("8"), "high": ratio("10")},
        net_debt=money("100"), net_debt_includes_parent_payment=True,
        other_claims=[Claim(name="pension deficit", amount=money("20"), already_counted_elsewhere=False)],
        other_assets=money("0"), diluted_shares=quantity("20", "million_shares", context=True),
        lease_treatment_consistent=True,
        current_price=quantity("10.00", "currency_units_per_share", "USD", context=True),
        price_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def tender(shares, fraction, withholding, residual, exit_costs):
    return TenderInputs(
        shares=quantity(shares, "shares"),
        purchase_price=quantity("18.40", "currency_units_per_share", "USD"),
        entry_fx=quantity("0.7900", "gbp_per_currency_unit", "USD"),
        entry_costs=quantity("3.00", "currency_units", "GBP"),
        tender_price=quantity("20.00", "currency_units_per_share", "USD"),
        accepted_fraction=ratio(fraction), withholding_rate=ratio(withholding),
        residual_value=quantity(residual, "currency_units_per_share", "USD") if residual is not None else None,
        exit_fx=quantity("0.7800", "gbp_per_currency_unit", "USD"),
        cash_distributions=quantity("0", "currency_units", "GBP"),
        exit_costs=quantity(exit_costs, "currency_units", "GBP"),
    )


@pytest.mark.parametrize("name,enterprise,equity,price,difference", [
    ("low", "300", "180", "9.00", "-10.0%"),
    ("base", "400", "280", "14.00", "40.0%"),
    ("high", "500", "380", "19.00", "90.0%"),
])
def test_supplied_spinoff_example(name, enterprise, equity, price, difference):
    result = spinoff_valuation(worksheet())[name]
    assert result["enterprise_value"].value == Decimal(enterprise)
    assert result["equity_value"].value == Decimal(equity)
    assert format_price(result["value_per_share"], 2) == price
    assert format_percentage(result["difference"], 1) == difference
    assert result["value_per_share"].currency == "USD"
    assert result["value_per_share"].entity == "Hypothetical SpinCo"
    assert result["value_per_share"].period == "Hypothetical pro forma period"


@pytest.mark.parametrize("shares,fraction,withholding,residual,costs,initial,accepted,proceeds,profit,rate", [
    ("99", "1", ".15", None, "3.00", "1442.06", "99", "1309.74", "-132.32", "-9.18%"),
    ("99", "1", "0", None, "3.00", "1442.06", "99", "1541.40", "99.34", "6.89%"),
    ("250", ".403", ".15", "17.50", "6.00", "3637.00", "100", "3367.50", "-269.50", "-7.41%"),
    ("250", "0", ".15", "16.80", "3.00", "3637.00", "0", "3273.00", "-364.00", "-10.01%"),
], ids=["A1", "A2", "B", "C"])
def test_supplied_tender_examples(shares, fraction, withholding, residual, costs,
                                  initial, accepted, proceeds, profit, rate):
    result = tender_scenario(tender(shares, fraction, withholding, residual, costs))
    assert format_gbp(result["initial_cost"]) == initial
    assert result["accepted_shares"].value == Decimal(accepted)
    assert format_gbp(result["scenario_proceeds"]) == proceeds
    assert format_gbp(result["scenario_profit"]) == profit
    assert format_percentage(result["scenario_return"], 2) == rate
    if shares == "99":
        assert result["initial_cost"].value == Decimal("1442.064")
    if accepted == "0":
        assert result["withholding_amount"].value == Decimal("0")


def test_supplied_expected_profit():
    b = tender_scenario(tender("250", ".403", ".15", "17.50", "6.00"))
    c = tender_scenario(tender("250", "0", ".15", "16.80", "3.00"))
    result = expected_profit([(ratio(".8"), b["scenario_profit"]), (ratio(".2"), c["scenario_profit"])])
    assert result.value == Decimal("-288.40")
    assert format_gbp(result) == "-288.40"


def test_parent_payment_already_in_net_debt_is_not_deducted_twice():
    inputs = worksheet().model_copy(update={"parent_payment": money("30")})
    assert spinoff_valuation(inputs)["base"]["equity_value"].value == Decimal("280")
    inputs.net_debt_includes_parent_payment = False
    assert spinoff_valuation(inputs)["base"]["equity_value"].value == Decimal("250")


def test_claim_already_counted_is_not_deducted_twice():
    inputs = worksheet()
    inputs.other_claims[0].already_counted_elsewhere = True
    assert spinoff_valuation(inputs)["base"]["equity_value"].value == Decimal("300")


@pytest.mark.parametrize("price", [None, quantity(None, "currency_units_per_share", "USD", context=True)])
def test_unknown_price_keeps_supported_valuation(price):
    result = spinoff_valuation(worksheet().model_copy(update={"current_price": price}))["base"]
    assert result["value_per_share"].value == Decimal("14")
    assert result["difference"].value is None


@pytest.mark.parametrize("field,value,error", [
    ("profit", money(None), "profit is unknown"),
    ("net_debt_includes_parent_payment", None, "net_debt_includes_parent_payment is unknown"),
    ("other_claims", None, "other_claims is unknown"),
    ("diluted_shares", quantity("0", "million_shares", context=True), "diluted_shares.*zero denominator"),
    ("current_price", quantity("0", "currency_units_per_share", "USD", context=True), "current_price.*zero denominator"),
    ("profit_measure", "net_income", "profit_measure must support enterprise value"),
    ("multiple_measure", "operating_income", "multiple_measure does not match"),
    ("lease_treatment_consistent", False, "lease_treatment_consistent must be confirmed"),
    ("lease_treatment_consistent", None, "lease_treatment_consistent must be confirmed"),
    ("price_observed_at", None, "price_observed_at is unknown"),
    ("net_debt", quantity("100", "currency_units", "USD", context=True), "net_debt must use million_currency_units"),
    ("diluted_shares", quantity("20", "shares", context=True), "diluted_shares must use million_shares"),
    ("other_assets", quantity("0", "million_currency_units", "GBP", context=True), "other_assets currency"),
])
def test_spinoff_invalid_or_unknown_input(field, value, error):
    with pytest.raises(ValueError, match="cannot calculate: " + error):
        spinoff_valuation(worksheet().model_copy(update={field: value}))


@pytest.mark.parametrize("field,value", [("entity", "Hypothetical Parent"), ("period", "Different period")])
def test_mixed_entity_or_period_rejected(field, value):
    inputs = worksheet()
    inputs.net_debt = inputs.net_debt.model_copy(update={field: value})
    with pytest.raises(ValueError, match=f"net_debt {field} does not match"):
        spinoff_valuation(inputs)


def test_unknown_parent_payment_required_when_not_already_included():
    inputs = worksheet().model_copy(update={"net_debt_includes_parent_payment": False})
    with pytest.raises(ValueError, match="parent_payment is unknown"):
        spinoff_valuation(inputs)


def test_claim_inclusion_requires_explicit_answer():
    inputs = worksheet()
    inputs.other_claims[0].already_counted_elsewhere = None
    with pytest.raises(ValueError, match="pension deficit already_counted_elsewhere is unknown"):
        spinoff_valuation(inputs)


@pytest.mark.parametrize("field,value,error", [
    ("shares", quantity("-1", "shares"), "shares must be non-negative"),
    ("shares", quantity("99.5", "shares"), "shares must be whole"),
    ("shares", quantity("0", "shares"), "shares for return must be positive"),
    ("purchase_price", quantity("0", "currency_units_per_share", "USD"), "purchase_price.*zero denominator"),
    ("entry_fx", quantity("0", "gbp_per_currency_unit", "USD"), "entry_fx.*zero denominator"),
    ("withholding_rate", ratio(None), "withholding_rate is unknown"),
    ("accepted_fraction", ratio("1.01"), "accepted_fraction must be between"),
    ("accepted_fraction", ratio("-.01"), "accepted_fraction must be between"),
    ("withholding_rate", ratio("1.01"), "withholding_rate must be between"),
    ("withholding_rate", ratio("-.01"), "withholding_rate must be between"),
    ("exit_costs", quantity(None, "currency_units", "GBP"), "exit_costs is unknown"),
    ("entry_costs", quantity("300", "pence", "GBP"), "entry_costs must use currency_units"),
    ("purchase_price", quantity("1840", "pence_per_share", "GBP"), "purchase_price must use currency_units_per_share"),
    ("tender_price", quantity("20", "currency_units_per_share", "GBP"), "tender_price currency must be USD"),
])
def test_tender_invalid_or_unknown_input(field, value, error):
    inputs = tender("99", "1", ".15", None, "3.00").model_copy(update={field: value})
    with pytest.raises(ValueError, match="cannot calculate: " + error):
        tender_scenario(inputs)


def test_unknown_residual_required_only_with_remaining_shares():
    with pytest.raises(ValueError, match="residual_value is unknown"):
        tender_scenario(tender("250", ".403", ".15", None, "6.00"))
    assert tender_scenario(tender("99", "1", ".15", None, "3.00"))["remaining_shares"].value == 0


@pytest.mark.parametrize("probabilities,error", [
    ([".8", ".3"], "probabilities must sum to one"),
    ([".8", ".1"], "probabilities must sum to one"),
    (["-.1", "1.1"], "probability_1 must be between"),
    ([None, "1"], "probability_1 is unknown"),
    ([], "probabilities must sum to one"),
])
def test_invalid_probabilities(probabilities, error):
    with pytest.raises(ValueError, match="cannot calculate: " + error):
        expected_profit([(ratio(p), quantity("-100", "currency_units", "GBP")) for p in probabilities])


def test_display_uses_half_up_without_changing_decimal_input():
    amount = quantity("-1.005", "currency_units", "GBP")
    assert format_gbp(amount) == "-1.01"
    assert amount.value == Decimal("-1.005")


def test_float_financial_input_rejected():
    with pytest.raises(ValueError, match="never a float"):
        Quantity(value=0.1, unit="currency_units", currency="GBP")
