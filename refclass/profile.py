"""Conservative checks for the fields that select a deal's nested class."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import re
from zoneinfo import ZoneInfo
from .quality import source_excerpt, require
from .collectors.edgar import acceptance_datetime


def available_at_close(filing, when):
    filed = date.fromisoformat(filing['filingDate'])
    if filed != when:
        return filed < when
    accepted = filing.get('acceptanceDateTime')
    if not accepted or 'T' not in accepted:
        return False
    instant = acceptance_datetime(accepted)
    eastern = ZoneInfo('America/New_York')
    return instant < datetime.combine(when, time(16), eastern)


def verify_profile(profile, root):
    when = date.fromisoformat(profile['as_of'])
    text = source_excerpt(profile, deal_root=root)
    absent = bool(re.search(
        r'\b(?:we have|the company has) no (?:FDA[- ]approved|approved|commercial) products\b|'
        r'\b(?:we have|the company has) no products (?:that (?:have been |are ))?approved for commercial sale\b|'
        r'\b(?:we do not|the company does not) have (?:any )?products (?:that (?:are |have been ))?approved for (?:commercial )?sale\b', text, re.I))
    company = re.escape(profile.get('company') or root.name)
    absent |= bool(re.search(
        rf'\b(?:we have|(?:the company|{company}) has) not obtained any regulatory approvals for a product candidate\b',
        text, re.I))
    # Bind named products to the profile or explicit ownership in the excerpt.
    products = [profile['drug']] if profile.get('drug') else []
    products.extend(re.findall(
        rf'\b(\w+) is a trademark of {company}(?: Inc\.)?\b', text, re.I))
    for product in products:
        subject = re.escape(product)
        absent |= bool(re.search(
            rf'\b{subject} (?:is not approved in any indication\b|'
            rf'is the proposed trade name for (?:\b(?:Inc|Ltd|Corp|Co)\.|[^.])+\.\s*It is not approved in any indication\b)',
            text, re.I))
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
    if profile.get('market_value_inputs') is not None:
        from .publication import price_evidence
        from .provenance import shares_verified
        from .inventory import verify as verify_inventory
        from .engine import session_dates
        inputs = profile['market_value_inputs']
        require(inputs.get('currency') == 'USD', 'Profile market value needs USD.')
        bar = inputs['price']
        require(bar['ticker'] == inputs['ticker'] and bar['date'] == profile['as_of'],
                'Profile price ticker and as-of date must match.')
        require(price_evidence(bar).get('provider') == 'Massive', 'Profile price needs Massive evidence.')
        if inputs.get('announced_at'):
            require(session_dates(inputs['announced_at'], inputs['sessions'])[0] == bar['date'],
                    'Profile price is not the pre-news session.')
        # Check same-day availability against the saved SEC acceptance time.
        # The date-only share verifier then sees only available filings.
        event = dict(inputs, announced_at=(when + timedelta(days=1)).isoformat())
        for filing in inputs['share_filings']:
            source_excerpt(filing, deal_root=root)
        latest = verify_inventory(event, filing_available=lambda row: available_at_close(row, when))
        event['share_filings'] = [f for f in inputs['share_filings']
                                 if date.fromisoformat(f['filed_at']) < when
                                 or f.get('accessionNumber') == latest['accessionNumber']]
        require(shares_verified(event), 'Profile share evidence failed.')
        require(date.fromisoformat(inputs['shares_as_of']) <= when,
                'Profile shares postdate the valuation close.')
        from .math import positive
        positive(bar['close'])
        positive(inputs['shares'])
        value = Decimal(str(bar['close'])) * Decimal(str(inputs['shares']))
        require(value.is_finite() and value > 0, 'Profile market value must be positive.')
        if profile.get('market_value') is not None:
            require(Decimal(str(profile['market_value'])) == value, 'Profile market value calculation mismatch.')
        profile['market_value'] = str(value)
        profile['market_value_calculation'] = f"{bar['close']} * {inputs['shares']} = {value} USD"
    elif profile.get('market_value') is not None:
        ev = profile['market_value_evidence']
        text = source_excerpt(ev, deal_root=root)
        require(ev.get('currency') == 'USD' and ev.get('as_of') == profile['as_of'],
                'Market value needs USD and matching as-of date.')
        require(not re.search(r'non[- ]affiliates|public float|enterprise value', text, re.I),
                'Market value must cover all common shares, not free float or enterprise value.')
        require(bool(re.search(r'pre[- ]news close', text, re.I)),
                'Market value must be measured at the pre-news close.')
        dates = [when.isoformat(), f'{when:%B} {when.day}, {when.year}',
                 f'{when.day} {when:%B} {when.year}']
        require(any(d.casefold() in text.casefold() for d in dates),
                'Market value source needs a matching date.')
        # Bind the amount and its scale to the currency token, rather than
        # matching any number in a passage (such as a share count or a date).
        amounts = []
        for match in re.finditer(
                r'\b(?:total (?:equity )?market value|market capitalization)\b'
                r'[^$\n.;]{0,80}?(?<![\w$])(?:USD\s*|US\$\s*|\$\s*)'
                r'(\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)(?!\w|[.,]\d)'
                r'(?:\s*(billion|million|thousand)\b)?', text, re.I):
            amount = Decimal(match[1].replace(',', ''))
            scale = {None: 1, 'thousand': 1000, 'million': 1000000, 'billion': 1000000000}
            amounts.append(amount * scale[match[2].lower() if match[2] else None])
        value = Decimal(str(profile['market_value']))
        require(value.is_finite() and value > 0 and value in amounts
                and bool(re.search(r'\b(?:total (?:equity )?market value|market capitalization)\b', text, re.I)),
                'Deal profile source does not establish market value in USD.')
