"""Conservative checks for the fields that select a deal's nested class."""
from datetime import date
from decimal import Decimal
import re
from .quality import source_excerpt, require


def verify_profile(profile, root):
    when = date.fromisoformat(profile['as_of'])
    text = source_excerpt(profile, deal_root=root)
    absent = bool(re.search(
        r'\b(?:we have no|has no|no) (?:FDA[- ]approved|approved|commercial) products\b|'
        r'\bno products (?:have been |are )?approved for commercial sale\b|'
        r'\bfirst (?:US |U\.S\. )?(?:approved|commercial) product\b', text, re.I))
    if profile.get('first_product') is True:
        require(absent, 'Deal profile source does not establish first-product status.')
    elif profile.get('first_product') is False:
        marketed = re.search(
            r'\b(?:we|the company) (?:currently )?(?:market|markets|sell|sells|commercialize|commercializes)\b'
            r'[^.;]{1,160}\b(?:in the (?:United States|US)|in the U\.S\.)', text, re.I)
        require(not absent and bool(marketed),
                'Deal profile source does not establish an existing US marketed product.')
    else:
        require(profile.get('first_product') is None, 'First-product status must be true, false or null.')
    if profile.get('market_value') is not None:
        ev = profile['market_value_evidence']
        text = source_excerpt(ev, deal_root=root)
        require(ev.get('currency') == 'USD' and ev.get('as_of') == profile['as_of'],
                'Market value needs USD and matching as-of date.')
        dates = [when.isoformat(), f'{when:%B} {when.day}, {when.year}',
                 f'{when.day} {when:%B} {when.year}']
        require(any(d.casefold() in text.casefold() for d in dates),
                'Market value source needs a matching date.')
        # Bind the amount and its scale to the currency token, rather than
        # matching any number in a passage (such as a share count or a date).
        amounts = []
        for match in re.finditer(
                r'(?<![\w$])(?:USD\s*|US\$\s*|\$\s*)'
                r'(\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)(?!\w|[.,]\d)'
                r'(?:\s*(billion|million|thousand)\b)?', text, re.I):
            amount = Decimal(match[1].replace(',', ''))
            scale = {None: 1, 'thousand': 1000, 'million': 1000000, 'billion': 1000000000}
            amounts.append(amount * scale[match[2].lower() if match[2] else None])
        value = Decimal(str(profile['market_value']))
        require(value.is_finite() and value > 0 and value in amounts
                and bool(re.search(r'\bmarket (?:value|capitalization)\b', text, re.I)),
                'Deal profile source does not establish market value in USD.')
