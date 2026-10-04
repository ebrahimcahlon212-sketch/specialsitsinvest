"""Fail-closed quality checks for structured evidence, before publication.

These checks verify supplied evidence, not the completeness of an SEC search.
The caller must obtain the source documents and dates first.
"""
from datetime import date
from pathlib import Path
import re
from .math import abnormal_return, convert, finite, positive, raw_return


class GateError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise GateError(message)


def discount(nav, nav_unit, price, price_unit, fx=None):
    nav = positive(convert(nav, nav_unit, price_unit, fx))
    result = 1 - positive(price) / nav
    require(-0.50 <= result <= 0.90, "Units and currency gate failed. Discount is outside -50% to 90%.")
    return result


def freshness(cash_as_of, shares_as_of, latest_10q_period):
    latest = date.fromisoformat(latest_10q_period)
    for label, value in (("cash", cash_as_of), ("shares", shares_as_of)):
        require(date.fromisoformat(value) >= latest, f"Staleness gate failed. {label} predates the latest 10-Q period.")


def listing(ticker, as_of, checked_through, filings, venue=None, suffix_review=None):
    start, end = date.fromisoformat(as_of), date.fromisoformat(checked_through)
    require(end >= start, "Listing gate failed. Filing coverage ends before the as-of date.")
    suspect = len(ticker) == 5 and ticker.upper().endswith("Q") and (venue is None or venue.upper() in {"OTC", "OTCQB", "OTCQX", "PINK"})
    if suspect:
        require(bool(suffix_review), "Listing gate failed. Fifth-letter Q suffix needs source-backed review.")
        excerpt = source_excerpt(suffix_review)
        require(ticker.upper() in excerpt.upper() and bool(suffix_review.get("reason")),
                "Listing suffix review needs ticker evidence and a reason.")
    for filing in filings:
        when = date.fromisoformat(filing["date"])
        require(not (start <= when <= end and "1.03" in filing["items"]),
                "Listing gate failed. An 8-K Item 1.03 needs review.")


def attribution(company, applicant, economics_source=None):
    require(bool(company) and bool(applicant), "Attribution gate failed. Company and applicant are required.")
    sourced = (isinstance(economics_source, dict) and bool(economics_source.get("source"))
               and bool(economics_source.get("locator")))
    require(company.casefold().strip() == applicant.casefold().strip() or sourced,
            "Attribution gate failed. Partner economics need a source and locator.")


def source_excerpt(evidence):
    """Re-read an exact, bounded line range in a saved primary document."""
    require(isinstance(evidence, dict), "Source evidence needs a saved document and line range.")
    path = Path(evidence["source"])
    lines = path.read_text().splitlines()
    start, end = evidence["line_start"], evidence["line_end"]
    require(isinstance(start, int) and isinstance(end, int) and 1 <= start <= end <= len(lines)
            and end - start < 50, "Source line range is invalid or too broad.")
    return " ".join(lines[start - 1:end])


def decision_date(kind, value=None, evidence=None):
    require(kind in {"fda_action", "fda_goal"}, "Date type gate failed. Expected an FDA action or goal date.")
    require(value is not None and evidence is not None, "Date type gate needs the date and primary-source evidence.")
    day = date.fromisoformat(value)
    excerpt = source_excerpt(evidence)
    # Evaluate the sentence containing the date, not a label or a neighbouring goal date.
    forms = (value, f"{day.strftime('%B')} {day.day}, {day.year}", f"{day.strftime('%b')} {day.day}, {day.year}")
    sentences = re.split(r"(?<=[.!?])\s+", excerpt)
    matches = [s for s in sentences if any(form.casefold() in s.casefold() for form in forms)]
    pattern = (r"(?:PDUFA|target action date|goal date|action date)" if kind == "fda_goal"
               else r"(?:FDA.{0,100}(?:approved|approval|complete response|rejected)|complete response letter)")
    require(any(re.search(pattern, s, re.I) and not re.search(
        r"(?:expect|plan|anticipat|intend|submit|readout)", s, re.I) for s in matches),
        "Date type gate failed. Source does not unambiguously support this FDA date; review required.")


def arithmetic(reported, recomputed, tolerance=0.005):
    require(abs(finite(reported) - finite(recomputed)) <= tolerance,
            "Arithmetic gate failed. Reported number does not match recomputation.")


def runway(cash, short_term_securities, long_term_securities, monthly_burn):
    amounts = [finite(x) for x in (cash, short_term_securities, long_term_securities)]
    require(all(x >= 0 for x in amounts), "Arithmetic gate failed. Cash and securities cannot be negative.")
    return sum(amounts) / positive(monthly_burn)


def whole_holding(price, tender_price, entitlement, residual_price):
    entitlement = finite(entitlement)
    require(0 <= entitlement <= 1, "Partial tender gate failed. Entitlement must be between zero and one.")
    residual = finite(residual_price)
    require(residual >= 0, "Partial tender gate failed. Residual value cannot be negative.")
    return (entitlement * positive(tender_price) + (1 - entitlement) * residual) / positive(price) - 1


def annualized_return(pre, post, as_of, payout):
    days = (date.fromisoformat(payout) - date.fromisoformat(as_of)).days
    require(days > 0, "Arithmetic gate failed. Payout must follow the price date.")
    return raw_return(pre, post) * 365 / days


def expected_value(outcomes):
    require(bool(outcomes), "Arithmetic gate failed. Outcomes are required.")
    probs = [finite(row["probability"]) for row in outcomes]
    require(all(0 <= p <= 1 for p in probs) and abs(sum(probs) - 1) < 1e-9,
            "Arithmetic gate failed. Outcome probabilities must sum to one.")
    return sum(p * finite(row["value"]) for p, row in zip(probs, outcomes))


def validate(evidence):
    """Run all applicable sections. Every gate must be present or explicitly N/A.

    N/A is {"not_applicable": "reason"}. A missing section is never a pass.
    """
    checks = {"units": discount, "staleness": freshness, "listing": listing,
              "attribution": attribution, "date_type": decision_date,
              "arithmetic": arithmetic, "partial_tender": whole_holding}
    results = {}
    for name, check in checks.items():
        require(name in evidence, f"Quality gate evidence missing. {name}")
        fields = evidence[name]
        if isinstance(fields, dict) and fields.get("not_applicable"):
            results[name] = {"not_applicable": fields["not_applicable"]}
            continue
        if name == "partial_tender":
            fields = dict(fields)
            reported = fields.pop("headline_return")
            results[name] = check(**fields)
            arithmetic(reported, results[name], tolerance=0.00005 + 1e-12)
        elif name == "arithmetic":
            require(bool(fields), "Arithmetic gate failed. Supply at least one computation.")
            computations = {"runway": runway, "return": raw_return, "abnormal_return": abnormal_return,
                            "annualized_return": annualized_return, "expected_value": expected_value,
                            "whole_holding": whole_holding, "discount": discount}
            for row in fields:
                if row.get("kind") not in computations:
                    raise GateError("Arithmetic gate failed. Unsupported computation kind.")
                arithmetic(row["reported"], computations[row["kind"]](**row["inputs"]),
                           tolerance=.005 if row["kind"] in ("runway", "expected_value") else 0.00005 + 1e-12)
            results[name] = "passed"
        else:
            results[name] = check(**fields)
    return results
