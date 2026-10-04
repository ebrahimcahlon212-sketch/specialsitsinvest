"""Pure calculations. Returns are fractions, never percentages."""
import math
from decimal import Decimal
from statistics import NormalDist


def finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("A finite number is required")
    return value


def positive(value):
    value = finite(value)
    if value <= 0:
        raise ValueError("A positive number is required")
    return value


def posterior(base, likelihood_ratios):
    base = finite(base)
    if not 0 <= base <= 1:
        raise ValueError("Probability must be between zero and one")
    ratios = [positive(x) for x in likelihood_ratios]
    if base in (0, 1):
        return base
    log_odds = math.log(base) - math.log1p(-base) + sum(map(math.log, ratios))
    if log_odds >= 0:
        return 1 / (1 + math.exp(-log_odds))
    exp_odds = math.exp(log_odds)
    return exp_odds / (1 + exp_odds)


def wilson(successes, total, confidence=0.90):
    if type(total) is not int or type(successes) is not int or not 0 <= successes <= total:
        raise ValueError("Counts must be integers with 0 <= successes <= total")
    if not 0 < confidence < 1:
        raise ValueError("Confidence must be between zero and one")
    if total == 0:
        return None
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0, centre - half), min(1, centre + half)


def raw_return(pre, post):
    return positive(post) / positive(pre) - 1


def abnormal_return(pre, post, xbi_pre, xbi_post):
    """Cumulative company simple return minus XBI simple return on identical dates."""
    return raw_return(pre, post) - raw_return(xbi_pre, xbi_post)


def convert(value, source_unit, target_unit, fx=None):
    """fx maps (source currency, target currency) to target units per source unit.

    No inferred currencies or inverted quotes. GBp and GBX mean pence.
    """
    units = {"USD": ("USD", "1"), "GBP": ("GBP", "1"),
             "GBp": ("GBP", ".01"), "GBX": ("GBP", ".01"), "EUR": ("EUR", "1")}
    if isinstance(fx, list):
        pairs = {}
        for row in fx:
            pair = (row["from"], row["to"])
            if pair in pairs:
                raise ValueError("Duplicate FX currency pair")
            pairs[pair] = row["rate"]
        fx = pairs
    if source_unit not in units or target_unit not in units:
        raise ValueError("Unknown currency or unit")
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("A finite amount is required")
    source, source_scale = units[source_unit]
    target, target_scale = units[target_unit]
    rate = Decimal(1)
    if source != target:
        try:
            rate = Decimal(str((fx or {})[(source, target)]))
        except KeyError as exc:
            raise ValueError("Missing explicit FX rate") from exc
        if not rate.is_finite() or rate <= 0:
            raise ValueError("FX rate must be positive and finite")
    return amount * Decimal(source_scale) * rate / Decimal(target_scale)
