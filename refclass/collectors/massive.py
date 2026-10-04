"""Massive daily aggregates, paired split-adjusted and as-traded responses.

Only the standard library is used. Authorization is a header, never a URL.
Offline replay needs no key. All live requests share a persisted rate limiter.
"""
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from .http import CollectionError
from ..bars import request as validate_request
from ..locking import job_lock
from ..math import positive

ROOT = Path(__file__).resolve().parents[2]
EASTERN = ZoneInfo('America/New_York')


def years_before(day, years):
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def api_key(settings):
    for line in Path(settings).read_text().splitlines():
        name, sep, value = line.strip().partition('=')
        if sep and name == 'MASSIVE_API_KEY':
            value = value.strip().strip('\"\'')
            if value and not any(c.isspace() for c in value):
                return value
    raise CollectionError('MASSIVE_API_KEY is missing from settings.env.')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise CollectionError('Massive redirects are not permitted.')


class Client:
    def __init__(self, cache, *, settings=None, offline=False, opener=None,
                 sleep=time.sleep, clock=time.time, rate_path=None):
        self.cache = Path(cache)
        self.offline = offline
        self.key = None if offline else api_key(settings or ROOT / 'settings.env')
        self.opener = opener or urllib.request.build_opener(NoRedirect()).open
        self.sleep, self.clock = sleep, clock
        self.rate_path = Path(rate_path or ROOT / '.locks/massive-rate.json')

    def throttle(self):
        self.rate_path.parent.mkdir(parents=True, exist_ok=True)
        with job_lock(str(self.rate_path) + '.lock'):
            last = json.loads(self.rate_path.read_text()) if self.rate_path.exists() else 0
            delay = max(0, last + 12.1 - self.clock())
            self.sleep(delay)
            self.rate_path.write_text(json.dumps(self.clock()))

    def get(self, ticker, since, until, adjusted):
        url = (f'https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{since}/{until}'
               f'?adjusted={str(adjusted).lower()}&sort=asc&limit=50000')
        manifest = self.cache / 'manifest.json'
        records = json.loads(manifest.read_text()) if manifest.exists() else []
        record = next((r for r in reversed(records) if r['url'] == url), None)
        if self.offline:
            if record is None:
                raise CollectionError('Massive response missing from offline cache.')
            path = (self.cache / record['file']).resolve()
            if not path.is_relative_to(self.cache.resolve()):
                raise CollectionError('Massive cache path escapes its directory.')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != record['sha256']:
                raise CollectionError('Massive cached response checksum mismatch.')
        else:
            self.throttle()
            req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self.key})
            try:
                with self.opener(req, timeout=30) as response:
                    raw, status = response.read(2_000_001), response.status
            except urllib.error.HTTPError as exc:
                status = exc.code
                # Error bodies may echo credentials. Save only status and the keyless request.
                exc.close()
                raw = json.dumps({'status': 'HTTP_ERROR', 'http_status': status}).encode()
            except (urllib.error.URLError, OSError):
                raise CollectionError('Massive request failed; credentials and transport details withheld.') from None
            if len(raw) > 2_000_000:
                raise CollectionError('Massive response exceeds the saved sample size limit.')
            if self.key.encode() in raw:
                raise CollectionError('Massive response echoed credentials; response was not saved.')
            digest = hashlib.sha256(raw).hexdigest()
            name = hashlib.sha256(url.encode()).hexdigest()[:16] + '-' + digest[:12] + '.json'
            self.cache.mkdir(parents=True, exist_ok=True)
            (self.cache / name).write_bytes(raw)
            record = dict(url=url, file=name, sha256=digest, status=status,
                          downloaded_at=datetime.now(timezone.utc).isoformat())
            with job_lock(self.cache / '.manifest.lock'):
                records = json.loads(manifest.read_text()) if manifest.exists() else []
                records.append(record)
                manifest.write_text(json.dumps(records, indent=2) + '\n')
            path = (self.cache / name).resolve()
        if record['status'] != 200:
            code = record['status']
            reason = 'History unavailable under the current plan or entitlement' if code in (401, 403) else 'Request failed'
            raise CollectionError(f'Massive {reason}. HTTP {code}. [{path}]')
        try:
            return json.loads(raw), dict(source=str(path), manifest=str(manifest.resolve()), url=url)
        except (ValueError, UnicodeError):
            raise CollectionError('Massive returned invalid JSON.') from None


def unpack(payload, ticker, adjusted, since, until):
    if payload.get('ticker') != ticker or payload.get('adjusted') is not adjusted:
        raise CollectionError('Massive ticker or adjustment does not match the request.')
    if payload.get('status') not in ('OK', 'DELAYED') or payload.get('next_url'):
        raise CollectionError('Massive response failed or is paginated; narrow the date window.')
    rows = {}
    for index, bar in enumerate(payload.get('results', [])):
        day = datetime.fromtimestamp(bar['t'] / 1000, EASTERN).date().isoformat()
        if not since <= day <= until or day in rows:
            raise CollectionError('Massive duplicate or out-of-range session.')
        rows[day] = (positive(bar['c']), index)
    return rows


def collect(client, *, tickers, since, until, history_years=2, today=None):
    query = validate_request(tickers, since, until)
    if history_years < 1:
        raise ValueError('History years must be positive.')
    today = today or date.today()
    earliest = years_before(today, history_years).isoformat()
    result = dict(source='massive', scope=dict(query, history_years=history_years), prices=[], gaps=[])
    if since < earliest:
        result['gaps'].append(f'Massive plan history gap. Requested {since} through {min(until, earliest)}; '
                              f'configured history begins {earliest}. Events remain in the census.')
    start = max(since, earliest)
    if until > today.isoformat():
        result['gaps'].append('Massive future bars are unavailable.')
    stop = min(until, today.isoformat())
    for ticker in query['tickers']:
        cursor = date.fromisoformat(start)
        while cursor.isoformat() <= stop:
            # Bound each response below the daily-aggregate limit, including a full census after upgrade.
            end = min(date(cursor.year, 12, 31).isoformat(), stop)
            try:
                pair = [client.get(ticker, cursor.isoformat(), end, adjusted) for adjusted in (False, True)]
                maps = [unpack(data, ticker, flag, cursor.isoformat(), end)
                        for (data, _), flag in zip(pair, (False, True))]
                if set(maps[0]) != set(maps[1]):
                    result['gaps'].append(f'{ticker}. Adjusted and as-traded sessions differ in {cursor} through {end}.')
                if not maps[0] or not maps[1]:
                    result['gaps'].append(f'{ticker}. No paired Massive bars for {cursor} through {end}.')
                bars = []
                for day in sorted(set(maps[0]) & set(maps[1])):
                    bars.append(dict(provider='Massive', ticker=ticker, date=day,
                        close=maps[0][day][0], adjusted_close=maps[1][day][0], adjustment='split_only',
                        raw_evidence=[dict(origin, index=values[day][1]) for (_, origin), values in zip(pair, maps)]))
                name = f'{ticker}_{cursor}_{end}.bars.jsonl'
                output = client.cache / name
                content = ''.join(json.dumps(bar, sort_keys=True) + '\n' for bar in bars)
                if output.exists() and output.read_text() != content:
                    raise CollectionError('Saved Massive bars differ; preserve this download and use a new directory.')
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(content)
                result['prices'].extend(dict(ticker=b['ticker'], date=b['date'], close=b['close'],
                    adjusted_close=b['adjusted_close'], source=f'{output.resolve()}#L{n}') for n, b in enumerate(bars, 1))
            except (ValueError, KeyError, TypeError, OSError) as exc:
                result['gaps'].append(f'{ticker} {cursor} through {end}. {exc}')
            cursor = date(cursor.year + 1, 1, 1)
    result.update(complete=not result['gaps'], gap_count=len(result['gaps']),
                  coverage_gaps=['Daily bars do not establish complete exchange sessions; event windows check missing bars.'])
    return result


def verify(bar):
    """Re-read both primary responses and keyless request metadata at publication."""
    from ..quality import primary_path, require
    for evidence, adjusted, field in zip(bar['raw_evidence'], (False, True), ('close', 'adjusted_close')):
        path = primary_path(evidence['source'])
        raw = path.read_bytes()
        records = json.loads(primary_path(evidence['manifest']).read_text())
        record = next((r for r in records if r['url'] == evidence['url'] and r['file'] == path.name
                       and r['sha256'] == hashlib.sha256(raw).hexdigest()), None)
        require(record is not None and record['status'] == 200, 'Massive request evidence mismatch.')
        from urllib.parse import urlsplit, parse_qs
        url = urlsplit(evidence['url'])
        parts = url.path.split('/')
        require(url.scheme == 'https' and url.netloc == 'api.massive.com' and
                parts[:4] == ['', 'v2', 'aggs', 'ticker'] and parts[4] == bar['ticker'] and
                parts[5:8] == ['range', '1', 'day'] and
                parse_qs(url.query).get('adjusted') == [str(adjusted).lower()], 'Massive request convention mismatch.')
        payload = json.loads(raw)
        rows = unpack(payload, bar['ticker'], adjusted, parts[8], parts[9])
        require(rows[bar['date']] == (bar[field], evidence['index']), 'Massive primary close mismatch.')
    require(len(bar['raw_evidence']) == 2, 'Massive needs both close conventions.')
