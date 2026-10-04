"""Check saved event evidence before admitting production records to classes.

These checks do not establish completeness of the supplied filing inventory.
Missing or ambiguous evidence keeps an event out of the eligible classes.
"""
from datetime import date
import re

from .quality import source_excerpt


def words(text, value):
    return bool(value) and str(value).casefold() in text.casefold()


def eligibility_gap(event):
    try:
        listing = event["listing_evidence"]
        text = source_excerpt(listing)
        if listing["venue"].upper() not in {"NASDAQ", "NYSE", "NYSE AMERICAN"}:
            return "US exchange listing is not supported"
        when = event["announced_at"][:10]
        if not listing["valid_from"] <= when <= listing["valid_through"]:
            return "Listing evidence does not cover the event date"
        for field in ("valid_from", "valid_through"):
            date.fromisoformat(listing[field])
        if not words(text, event["ticker"]) or not words(text, listing["venue"]):
            return "Listing source does not support ticker and exchange"
        applicant = event["applicant"]
        text = source_excerpt(event["applicant_evidence"])
        if not words(text, applicant) or not words(text, event["drug"]):
            return "Applicant source does not identify applicant and drug"
        if applicant.casefold().strip() != event["company"].casefold().strip():
            text = source_excerpt(event["economics_evidence"])
            if not all(words(text, value) for value in (applicant, event["company"], event["drug"])) or not re.search(
                    r"royalt|profit.shar|commercial.{0,30}rights", text, re.I):
                return "Partner economics are not supported by the saved source"
    except (KeyError, TypeError, ValueError, OSError):
        return "Listing or applicant evidence is missing or unreadable"
    return None


def shares_verified(event):
    try:
        filings = event["share_filings"]
        before = [f for f in filings if date.fromisoformat(f["filed_at"]) < date.fromisoformat(event["announced_at"][:10])]
        latest = max(before, key=lambda f: f["filed_at"])
        if latest["source"] != event["shares_source"] or latest["as_of"] != event["shares_as_of"]:
            return False
        if float(latest["shares"]) != float(event["shares"]):
            return False
        text = source_excerpt(latest)
        numbers = [float(x.replace(",", "")) for x in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w.])", text)]
        return float(event["shares"]) in numbers and bool(re.search(r"shares.{0,60}outstanding|outstanding.{0,60}shares", text, re.I))
    except (KeyError, TypeError, ValueError, OSError):
        return False
