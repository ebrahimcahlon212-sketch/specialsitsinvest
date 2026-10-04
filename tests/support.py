import csv
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


def comparables():
    with (FIXTURES / "savara-comparables.csv").open() as handle:
        return list(csv.DictReader(handle))


def bundle():
    """Synthetic metadata and benchmark, historical company raw-price fixtures."""
    events, prices, sessions = [], [], {}
    for row in comparables():
        event = dict(event_id=row["ticker"], company=row["company"], ticker=row["ticker"],
                     drug="fixture", application="NDA", original=True, listed_us=True,
                     event_type="approval", announced_at=row["announced_at"], goal_date=None,
                     source=row["source"], locator="fixture", first_product=True,
                     shares=10000000, shares_as_of="2024-01-01", shares_source="synthetic filing",
                     same_day_news=False, offering_dates=[], offering_coverage_through="2026-10-04")
        events.append(event)
        for i, field in enumerate(("pre", "day1", "day2")):
            day = row[field + "_date"]
            sessions[day] = dict(date=day, open="09:30", close="16:00")
            prices.append(dict(ticker=row["ticker"], date=day, close=row[field + "_close"],
                               adjusted_close=row[field + "_close"], source=row["source"]))
            prices.append(dict(ticker="XBI", date=day, close=[100, 102, 101][i],
                               adjusted_close=[100, 102, 101][i], source="SYNTHETIC XBI"))
    return dict(as_of="2026-10-04", fixture=True, events=events, prices=prices,
                sessions=sorted(sessions.values(), key=lambda x: x["date"]),
                coverage={"drugs_at_fda": "fixture only", "openfda_crl": "fixture only",
                          "edgar": "fixture only", "massive": "fixture only"})


def massive_prices(root, closes):
    """Synthetic paired HTTP responses, saved only under temporary primary folders."""
    import hashlib
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from refclass.collectors.massive import Client, collect
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    records = []
    dates = sorted({r['date'] for r in closes})
    for ticker in sorted({r['ticker'] for r in closes}):
        for flag, field in ((False, 'close'), (True, 'adjusted_close')):
            payload = dict(ticker=ticker, adjusted=flag, status='OK', results=[
                dict(t=int(datetime.fromisoformat(r['date']).replace(tzinfo=ZoneInfo('America/New_York')).timestamp()*1000), c=r[field])
                for r in closes if r['ticker'] == ticker])
            raw = json.dumps(payload).encode()
            name = f'{ticker}-{flag}.json'
            (root / name).write_bytes(raw)
            url = (f'https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{dates[0]}/{dates[-1]}'
                   f'?adjusted={str(flag).lower()}&sort=asc&limit=50000')
            records.append(dict(url=url, file=name, sha256=hashlib.sha256(raw).hexdigest(), status=200,
                                downloaded_at='synthetic, not downloaded'))
    (root / 'manifest.json').write_text(json.dumps(records))
    from datetime import date
    return collect(Client(root, offline=True), tickers=sorted({r['ticker'] for r in closes}),
                   since=dates[0], until=dates[-1], today=date(2026, 10, 4))['prices']
