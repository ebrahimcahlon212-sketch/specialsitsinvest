"""Offline renderer workload, runnable against a separate pre-phase-one lib tree."""
from contextlib import redirect_stdout
import datetime
import io
import json
from pathlib import Path
import sys
import tempfile


def outputs(lib):
    sys.path.insert(0, str(lib))
    import calc, biotech, finder, ukevents, valuation
    class FixedDate(datetime.date):
        @classmethod
        def today(cls): return cls(2026, 10, 4)
    datetime.date = FixedDate
    calc.TODAY = biotech.TODAY = FixedDate.today()
    with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
        p = Path(tmp); out = p / '2026-10-04'; out.mkdir()
        finder.STATE = str(p / 'finder-state.json'); finder.FINDER = tmp; finder.KIT = tmp
        ukevents.STATE = str(p / 'uk-state.json')
        row = dict(id='BIO-TEST', ticker='TEST', company='Test biotech', decision_date='2026-11-20',
                   approx=False, otc=False, market_cap=100000000, cash_per_share=2.5, price=5,
                   runway_months=18, context='Saved test context', source='https://source.invalid/filing',
                   url='https://source.invalid/filing', filing={'url': 'https://source.invalid/filing'})
        (out / 'biotech.json').write_text(json.dumps(dict(rows=[row])))
        cards = p / 'bio.txt'; cards.write_text(json.dumps(dict(id='BIO-TEST', score=4, drug='Testdrug', indication='Test use')))
        biotech.cmd_cards(str(out), [str(cards)]); biotech.cmd_render(str(out))
        events = p / 'uk.txt'; events.write_text(json.dumps(dict(company='Test UK plc', ticker='TEST', event='tender',
                      date='2026-11-20', url='https://source.invalid/uk', cash_per_share=137, score=4)))
        ukevents.cmd_ingest(str(out), str(events))
        finder.cmd_render(str(out))
        v = dict(price_currency='GBX', reporting_currency='GBP', shares_diluted_m=10, net_debt_m=5,
                 undisturbed_price=100, offer_price=150,
                 history=[dict(year=2024, revenue_m=20, ebitda_m=4, fcf_m=2),
                          dict(year=2025, revenue_m=25, ebitda_m=5, fcf_m=3)],
                 forward=dict(ebitda_m=6))
        result = valuation.compute(v, {'today': 120})
        names = ('biotech.json', 'biotech.md', 'biotech.html', 'shortlist.md', 'shortlist.html',
                 'uk_events.json', 'uk-events-tickers.txt')
        return dict(files={name: (out / name).read_text().replace(tmp, '<TEMP>') for name in names},
                    valuation=result, valuation_md=valuation.md(result, v, {'today': 120}))


if __name__ == '__main__':
    print(json.dumps(outputs(Path(sys.argv[1])), sort_keys=True, indent=2))
