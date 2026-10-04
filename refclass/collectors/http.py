"""Small, dated response cache and deterministic offline replay. Standard library only."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from ..locking import job_lock

HOSTS = {'api.fda.gov', 'data.sec.gov', 'www.sec.gov'}


class CollectionError(ValueError):
    pass


def saved_contact(settings=None):
    """Read the existing plain-text kit setting without executing shell content."""
    contact = os.environ.get('SEC_CONTACT', '').strip()
    if not contact and settings:
        for line in Path(settings).read_text().splitlines():
            if line.startswith('SEC_CONTACT='):
                contact = line.split('=', 1)[1].strip()
                if len(contact) >= 2 and contact[0] == contact[-1] and contact[0] in '\"\'':
                    contact = contact[1:-1]
    if not re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+', contact) or 'example.com' in contact or '\n' in contact or '\r' in contact:
        raise CollectionError('A saved SEC_CONTACT name and email is required for EDGAR requests.')
    return contact


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        if urllib.parse.urlsplit(req.full_url).hostname != urllib.parse.urlsplit(newurl).hostname:
            raise CollectionError('Cross-host redirects require review.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.port not in (None, 443):
        raise CollectionError('Collector URL must use an approved primary-source HTTPS host.')


class Client:
    def __init__(self, cache, *, contact=None, max_bytes=1_000_000, offline=False,
                 opener=None, sleep=time.sleep, clock=time.monotonic):
        self.cache = Path(cache)
        self.contact = contact
        self.max_bytes = max_bytes
        self.offline = offline
        self.opener = opener or urllib.request.build_opener(SafeRedirect()).open
        self.sleep, self.clock = sleep, clock
        self.last = None
        manifest = self.cache / 'manifest.json'
        self.records = json.loads(manifest.read_text()) if manifest.exists() else []

    def get(self, url):
        check_url(url)
        previous = next((r for r in reversed(self.records) if r['url'] == url), None)
        if self.offline:
            if not previous:
                raise CollectionError('Response missing from offline fixture cache. ' + url)
            path = (self.cache / previous['file']).resolve()
            if not path.is_relative_to(self.cache.resolve()):
                raise CollectionError('Cache path escapes its directory.')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != previous['sha256']:
                raise CollectionError('Cached response checksum mismatch.')
            return raw, dict(previous, source=str(path))
        sec = urllib.parse.urlsplit(url).hostname.endswith('sec.gov')
        if sec and not self.contact:
            raise CollectionError('SEC contact is required before any EDGAR request.')
        headers = {'User-Agent': self.contact if sec else 'special-sits-kit FDA reference-class research',
                   'Accept-Encoding': 'identity'}
        request = urllib.request.Request(url, headers=headers)
        for attempt in range(3):
            if self.last is not None:
                self.sleep(max(0, .25 - (self.clock() - self.last)))
            self.last = self.clock()
            try:
                with self.opener(request, timeout=30) as response:
                    raw = response.read(self.max_bytes + 1)
                    status = response.status
                    content_type = response.headers.get('Content-Type', '')
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    retry = exc.headers.get('Retry-After', '') if exc.headers else ''
                    exc.close()
                    self.sleep(min(30, max(1, int(retry))) if retry.isdigit() else 2 ** (attempt + 1))
                    continue
                # openFDA uses a JSON 404 for an empty search, never for a failed schema.
                if exc.code == 404 and not sec:
                    raw = exc.read(self.max_bytes + 1)
                    exc.close()
                    status, content_type = 404, 'application/json'
                    break
                exc.close()
                raise CollectionError(f'HTTP {exc.code}. {url}') from exc
            except (urllib.error.URLError, OSError) as exc:
                raise CollectionError(f'Request failed. {url}. {exc}') from exc
        if len(raw) > self.max_bytes:
            raise CollectionError(f'Response exceeds {self.max_bytes} byte limit. {url}')
        digest = hashlib.sha256(raw).hexdigest()
        name = hashlib.sha256(url.encode()).hexdigest()[:16] + '-' + digest[:12] + '.response'
        self.cache.mkdir(parents=True, exist_ok=True)
        (self.cache / name).write_bytes(raw)
        record = dict(url=url, downloaded_at=datetime.now(timezone.utc).isoformat(),
                      status=status, content_type=content_type, bytes=len(raw), sha256=digest, file=name)
        with job_lock(self.cache / '.manifest.lock'):
            manifest = self.cache / 'manifest.json'
            self.records = json.loads(manifest.read_text()) if manifest.exists() else []
            self.records.append(record)
            temporary = self.cache / 'manifest.json.tmp'
            temporary.write_text(json.dumps(self.records, indent=2) + '\n')
            temporary.replace(manifest)
        return raw, dict(record, source=str((self.cache / name).resolve()))

    def json(self, url):
        raw, origin = self.get(url)
        try:
            return json.loads(raw), origin
        except (ValueError, UnicodeError) as exc:
            raise CollectionError('Invalid JSON response. ' + url) from exc
