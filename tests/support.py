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
                          "edgar": "fixture only", "ibkr": "fixture only"})
