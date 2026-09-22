"""Pure Decimal calculations for the section 8 worksheets; no storage or services."""

from datetime import datetime
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from pydantic import BaseModel, field_validator


class Quantity(BaseModel):
    value: Decimal | None
    unit: str
    currency: str | None = None
    entity: str | None = None
    period: str | None = None

    @field_validator("value", mode="before")
    @classmethod
    def reject_float(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("Use Decimal or decimal text, never a float or boolean")
        return value


class Claim(BaseModel):
    name: str
    amount: Quantity
    already_counted_elsewhere: bool | None


class SpinoffInputs(BaseModel):
    profit: Quantity
    profit_measure: str
    multiple_measure: str
    multiples: dict[str, Quantity]
    net_debt: Quantity
    net_debt_includes_parent_payment: bool | None
    parent_payment: Quantity | None = None
    other_claims: list[Claim] | None
    other_assets: Quantity
    diluted_shares: Quantity
    lease_treatment_consistent: bool | None
    current_price: Quantity | None = None
    price_observed_at: datetime | None = None


class TenderInputs(BaseModel):
    shares: Quantity
    purchase_price: Quantity
    entry_fx: Quantity
    entry_costs: Quantity
    tender_price: Quantity
    accepted_fraction: Quantity
    withholding_rate: Quantity
    residual_value: Quantity | None = None
    exit_fx: Quantity
    cash_distributions: Quantity
    exit_costs: Quantity


def _value(quantity: Quantity | None, name: str, unit: str,
           currency: str | None = None, reference: Quantity | None = None) -> Decimal:
    if quantity is None or quantity.value is None:
        raise ValueError(f"cannot calculate: {name} is unknown")
    if not quantity.value.is_finite():
        raise ValueError(f"cannot calculate: {name} must be finite")
    if quantity.unit != unit:
        raise ValueError(f"cannot calculate: {name} must use {unit}, not {quantity.unit}")
    if quantity.currency != currency:
        raise ValueError(f"cannot calculate: {name} currency must be {currency or 'none'}")
    if reference is not None:
        if quantity.entity != reference.entity:
            raise ValueError(f"cannot calculate: {name} entity does not match profit")
        if quantity.period != reference.period:
            raise ValueError(f"cannot calculate: {name} period does not match profit")
    return quantity.value


def _nonnegative(value: Decimal, name: str) -> Decimal:
    if value < 0:
        raise ValueError(f"cannot calculate: {name} must be non-negative")
    return value


def _positive(value: Decimal, name: str) -> Decimal:
    if value <= 0:
        raise ValueError(f"cannot calculate: {name} must be positive (zero denominator)")
    return value


def _fraction(quantity: Quantity | None, name: str) -> Decimal:
    value = _value(quantity, name, "unitless")
    if not 0 <= value <= 1:
        raise ValueError(f"cannot calculate: {name} must be between zero and one")
    return value


def _output(value: Decimal | None, unit: str, currency: str | None = None,
            reference: Quantity | None = None) -> Quantity:
    return Quantity(value=value, unit=unit, currency=currency,
                    entity=reference.entity if reference else None,
                    period=reference.period if reference else None)


def spinoff_valuation(inputs: SpinoffInputs) -> dict[str, dict[str, Quantity]]:
    """Amounts and shares use millions; excluded claims are not deducted again.

    The caller must explicitly confirm consistent lease treatment. An omitted
    price leaves only the difference unknown. Invalid required inputs raise a
    named ValueError; the caller can present its 'cannot calculate' message.
    """
    reference = inputs.profit
    currency = reference.currency
    if not currency:
        raise ValueError("cannot calculate: profit currency is unknown")
    if not reference.entity or not reference.period:
        raise ValueError("cannot calculate: profit entity or period is unknown")
    if inputs.profit_measure not in ("operating_income", "ebitda"):
        raise ValueError("cannot calculate: profit_measure must support enterprise value")
    if inputs.multiple_measure != inputs.profit_measure:
        raise ValueError("cannot calculate: multiple_measure does not match profit_measure")
    if inputs.lease_treatment_consistent is not True:
        raise ValueError("cannot calculate: lease_treatment_consistent must be confirmed")
    if set(inputs.multiples) != {"low", "base", "high"}:
        raise ValueError("cannot calculate: multiples must contain low, base and high")

    profit = _value(reference, "profit", "million_currency_units", currency, reference)
    net_debt = _value(inputs.net_debt, "net_debt", "million_currency_units", currency, reference)
    if inputs.net_debt_includes_parent_payment is None:
        raise ValueError("cannot calculate: net_debt_includes_parent_payment is unknown")
    if not inputs.net_debt_includes_parent_payment:
        net_debt += _nonnegative(_value(inputs.parent_payment, "parent_payment",
                                       "million_currency_units", currency, reference), "parent_payment")
    if inputs.other_claims is None:
        raise ValueError("cannot calculate: other_claims is unknown")
    claims = Decimal("0")
    for claim in inputs.other_claims:
        if not claim.name.strip():
            raise ValueError("cannot calculate: other_claims item name is unknown")
        if claim.already_counted_elsewhere is None:
            raise ValueError(f"cannot calculate: {claim.name} already_counted_elsewhere is unknown")
        amount = _nonnegative(_value(claim.amount, claim.name, "million_currency_units",
                                     currency, reference), claim.name)
        if not claim.already_counted_elsewhere:
            claims += amount
    assets = _nonnegative(_value(inputs.other_assets, "other_assets", "million_currency_units",
                                 currency, reference), "other_assets")
    shares = _positive(_value(inputs.diluted_shares, "diluted_shares", "million_shares",
                              reference=reference), "diluted_shares")
    price = None
    if inputs.current_price is not None and inputs.current_price.value is not None:
        price = _positive(_value(inputs.current_price, "current_price", "currency_units_per_share",
                                 currency, reference), "current_price")
        if inputs.price_observed_at is None:
            raise ValueError("cannot calculate: price_observed_at is unknown")

    results = {}
    for name in ("low", "base", "high"):
        multiple = _nonnegative(_value(inputs.multiples[name], f"{name}_multiple", "unitless"),
                                f"{name}_multiple")
        enterprise_value = profit * multiple
        equity_value = enterprise_value - net_debt - claims + assets
        per_share = equity_value / shares
        results[name] = {
            "enterprise_value": _output(enterprise_value, "million_currency_units", currency, reference),
            "equity_value": _output(equity_value, "million_currency_units", currency, reference),
            "value_per_share": _output(per_share, "currency_units_per_share", currency, reference),
            "difference": _output(per_share / price - 1 if price is not None else None,
                                  "unitless", reference=reference),
        }
    return results


def tender_scenario(inputs: TenderInputs) -> dict[str, Quantity]:
    """One settlement and exit FX rate; withholding applies to gross tender proceeds.

    Rates are GBP per one trading-currency unit. Costs/distributions are net GBP.
    Withholding is a required supplied assumption, not a tax determination.
    Accepted shares alone are floored; all monetary intermediate values remain
    unrounded. A positive purchase is required for this function's return output.
    """
    currency = inputs.purchase_price.currency
    if not currency:
        raise ValueError("cannot calculate: purchase_price currency is unknown")
    shares = _nonnegative(_value(inputs.shares, "shares", "shares"), "shares")
    if shares != shares.to_integral_value():
        raise ValueError("cannot calculate: shares must be whole shares")
    price = _positive(_value(inputs.purchase_price, "purchase_price", "currency_units_per_share",
                             currency), "purchase_price")
    entry_fx = _positive(_value(inputs.entry_fx, "entry_fx", "gbp_per_currency_unit", currency), "entry_fx")
    exit_fx = _positive(_value(inputs.exit_fx, "exit_fx", "gbp_per_currency_unit", currency), "exit_fx")
    entry_costs = _nonnegative(_value(inputs.entry_costs, "entry_costs", "currency_units", "GBP"), "entry_costs")
    exit_costs = _nonnegative(_value(inputs.exit_costs, "exit_costs", "currency_units", "GBP"), "exit_costs")
    distributions = _nonnegative(_value(inputs.cash_distributions, "cash_distributions",
                                        "currency_units", "GBP"), "cash_distributions")
    fraction = _fraction(inputs.accepted_fraction, "accepted_fraction")
    withholding = _fraction(inputs.withholding_rate, "withholding_rate")
    tender_price = _nonnegative(_value(inputs.tender_price, "tender_price", "currency_units_per_share",
                                       currency), "tender_price")
    accepted = (shares * fraction).to_integral_value(rounding=ROUND_FLOOR)
    remaining = shares - accepted
    residual = Decimal("0")
    if remaining:
        residual = _nonnegative(_value(inputs.residual_value, "residual_value", "currency_units_per_share",
                                       currency), "residual_value")
    initial_cost = shares * price * entry_fx + entry_costs
    _positive(shares, "shares for return")
    _positive(initial_cost, "initial_cost")
    accepted_proceeds = accepted * tender_price * (1 - withholding)
    proceeds = accepted_proceeds * exit_fx + remaining * residual * exit_fx + distributions - exit_costs
    profit = proceeds - initial_cost
    return {
        "initial_cost": _output(initial_cost, "currency_units", "GBP"),
        "accepted_shares": _output(accepted, "shares"),
        "remaining_shares": _output(remaining, "shares"),
        "accepted_proceeds": _output(accepted_proceeds, "currency_units", currency),
        "withholding_amount": _output(accepted * tender_price * withholding, "currency_units", currency),
        "scenario_proceeds": _output(proceeds, "currency_units", "GBP"),
        "scenario_profit": _output(profit, "currency_units", "GBP"),
        "scenario_return": _output(profit / initial_cost, "unitless"),
    }


def expected_profit(scenarios: list[tuple[Quantity | None, Quantity]]) -> Quantity:
    """Combine (owner probability, scenario profit) pairs only when probabilities sum to one."""
    probabilities = [_fraction(probability, f"probability_{index + 1}")
                     for index, (probability, _) in enumerate(scenarios)]
    if sum(probabilities, Decimal("0")) != 1:
        raise ValueError("cannot calculate: probabilities must sum to one")
    profits = [_value(profit, f"scenario_profit_{index + 1}", "currency_units", "GBP")
               for index, (_, profit) in enumerate(scenarios)]
    return _output(sum((probability * profit for probability, profit in zip(probabilities, profits)),
                       Decimal("0")), "currency_units", "GBP")


def _format(value: Decimal, decimal_places: int) -> str:
    if not isinstance(decimal_places, int) or isinstance(decimal_places, bool) or decimal_places < 0:
        raise ValueError("decimal_places must be a non-negative integer")
    return format(value.quantize(Decimal("1").scaleb(-decimal_places), rounding=ROUND_HALF_UP), "f")


def format_gbp(quantity: Quantity) -> str:
    return _format(_value(quantity, "GBP amount", "currency_units", "GBP"), 2)


def format_price(quantity: Quantity, decimal_places: int) -> str:
    if not quantity.currency:
        raise ValueError("cannot calculate: price currency is unknown")
    return _format(_value(quantity, "price", "currency_units_per_share", quantity.currency), decimal_places)


def format_percentage(quantity: Quantity, decimal_places: int) -> str:
    return _format(_value(quantity, "percentage", "unitless") * 100, decimal_places) + "%"
