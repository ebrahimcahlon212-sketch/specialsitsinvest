"""Conservative checks for the fields that select a deal's nested class."""
from datetime import date
from decimal import Decimal
import re
from .quality import source_excerpt, require


def verify_profile(profile, root):
    date.fromisoformat(profile['as_of'])
    text = source_excerpt(profile, deal_root=root)
    if profile.get('first_product') is True:
        require(bool(re.search(r'\b(?:we have no|has no|no) (?:FDA[- ]approved|approved|commercial) products\b|\bfirst (?:US |U\.S\. )?(?:approved|commercial) product\b', text, re.I)),
                'Deal profile source does not establish first-product status.')
    if profile.get('market_value') is not None:
        ev = profile['market_value_evidence']
        text = source_excerpt(ev, deal_root=root)
        require(ev.get('currency') == 'USD' and ev.get('as_of') == profile['as_of'],
                'Market value needs USD and matching as-of date.')
        require(profile['as_of'] in text and bool(re.search(r'\bUSD\b|US\$', text)),
                'Market value source needs explicit currency and date.')
        # Exact numeric tokens, including scientific notation. No substring match.
        numbers = [Decimal(n.replace(',', '')) for n in re.findall(
            r'(?<![\w.])\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.])', text)]
        require(Decimal(str(profile['market_value'])) in numbers,
                'Deal profile source does not establish market value in USD.')
