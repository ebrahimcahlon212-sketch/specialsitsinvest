"""Synthetic HTTP responses only: automated checks never contact SEC."""

from unittest.mock import MagicMock

import pytest
import requests

from app import constants, sec
from app.bridge import Bridge
from app.db import initialize

URL = 'https://www.sec.gov/Archives/edgar/data/2023554/000119312524264578/d835366d1012b.htm'
UA = 'InvestResearch Synthetic Test test@example.invalid'


def response(status=200, content=b'<p>Synthetic transport fixture.</p>', headers=None):
    result = MagicMock()
    result.__enter__.return_value = result
    result.status_code = status
    result.is_redirect = 300 <= status < 400
    result.headers = headers or {}
    result.iter_content.return_value = [content]
    return result


@pytest.fixture
def transport(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(sec.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(sec.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(sec, '_last_request', 0)
    return clock


def test_contact_header_rate_limit_and_timeout_are_used(monkeypatch, transport):
    calls = []

    def get(url, **kwargs):
        calls.append((transport[0], kwargs))
        return response()

    monkeypatch.setattr(sec.requests, 'get', get)
    sec.fetch(URL, UA)
    sec.fetch(URL, UA)
    assert calls[1][0] - calls[0][0] >= .5
    assert calls[0][1]['headers']['User-Agent'] == UA
    assert calls[0][1]['timeout'] == constants.SEC_TIMEOUT
    assert calls[0][1]['allow_redirects'] is False


@pytest.mark.parametrize('status', [429, 503])
def test_transient_http_failure_has_bounded_backoff(monkeypatch, transport, status):
    get = MagicMock(side_effect=lambda *args, **kwargs: response(status))
    monkeypatch.setattr(sec.requests, 'get', get)
    with pytest.raises(ValueError, match=f'HTTP {status}'):
        sec.fetch(URL, UA)
    assert get.call_count == 3
    assert transport[0] == 106


def test_timeout_has_bounded_retries(monkeypatch, transport):
    get = MagicMock(side_effect=requests.Timeout('Synthetic timeout'))
    monkeypatch.setattr(sec.requests, 'get', get)
    with pytest.raises(ValueError, match='Timeout'):
        sec.fetch(URL, UA)
    assert get.call_count == 3


@pytest.mark.parametrize('reply, message', [
    (response(403), '403'),
    (response(404), '404'),
    (response(302, headers={'Location': 'https://example.invalid/filing'}), 'HTTPS'),
    (response(headers={'Content-Length': str(constants.MAX_DOCUMENT_BYTES + 1)}), 'limit'),
    (response(content=b'<html>Your request originates from an undeclared automated tool</html>'), 'restriction'),
])
def test_permanent_failures_do_not_retry_or_save_content(monkeypatch, transport, reply, message):
    get = MagicMock(return_value=reply)
    monkeypatch.setattr(sec.requests, 'get', get)
    with pytest.raises(ValueError, match=message):
        sec.fetch(URL, UA)
    assert get.call_count == 1


def test_streamed_size_is_checked_even_without_content_length(monkeypatch, transport):
    monkeypatch.setattr(constants, 'MAX_DOCUMENT_BYTES', 20)
    monkeypatch.setattr(sec.requests, 'get', lambda *args, **kwargs: response(content=b'x' * 21))
    with pytest.raises(ValueError, match='limit'):
        sec.fetch(URL, UA)


@pytest.mark.parametrize('url', [
    'http://www.sec.gov/Archives/edgar/data/2023554/000119312524264578/a.htm',
    'https://www.sec.gov.example.invalid/Archives/edgar/data/2023554/000119312524264578/a.htm',
    'https://www.sec.gov@127.0.0.1/Archives/edgar/data/2023554/000119312524264578/a.htm',
    'https://www.sec.gov/Archives/edgar/data/2023554/000119312524264578/../x.htm',
    'https://www.sec.gov/Archives/edgar/data/2023554/000119312524264578/%2e%2e',
    URL + '?download=1',
])
def test_only_supported_sec_urls_are_accepted(url):
    with pytest.raises(ValueError):
        sec.resolve_url(url)


def test_contact_persists_and_bridge_rejects_paths_and_header_injection(tmp_path):
    initialize(tmp_path)
    bridge = Bridge(tmp_path)
    assert bridge.save_sec_contact({'name': 'Synthetic Tester', 'email': 'test@example.invalid'})['error'] is None
    assert Bridge(tmp_path).sec_contact({})['name'] == 'Synthetic Tester'
    assert bridge.save_sec_contact({'name': 'Bad\r\nHeader', 'email': 'test@example.invalid'})['error']
    assert bridge.sec_import({'case_id': 1, 'url': URL, 'path': 'arbitrary'})['error']
    assert bridge.sec_import_status({})['error']
