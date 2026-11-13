"""Minimal rate-limited JSON HTTP client (stdlib only)."""
from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

USER_AGENT = "memecoin-desk/0.1"

# Requests per minute we allow ourselves per host (below each API's published limit).
HOST_RPM = {
    "api.dexscreener.com": 200,
    "api.geckoterminal.com": 24,
    "api.rugcheck.xyz": 40,
    "lite-api.jup.ag": 50,
    "api.mainnet-beta.solana.com": 100,
}
DEFAULT_RPM = 60


class HttpError(Exception):
    def __init__(self, url: str, status: int | None, msg: str):
        super().__init__(f"{status} {msg} <{url}>")
        self.url = url
        self.status = status


class _Limiter:
    """Simple spacing limiter: at most `rpm` requests per minute, evenly spaced."""

    def __init__(self, rpm: int):
        self.interval = 60.0 / rpm
        self.next_at = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            at = max(now, self.next_at)
            self.next_at = at + self.interval
        delay = at - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def penalize(self, seconds: float) -> None:
        with self.lock:
            self.next_at = max(self.next_at, time.monotonic() + seconds)


class Http:
    def __init__(self, timeout: float = 20.0, retries: int = 3):
        self.timeout = timeout
        self.retries = retries
        self._limiters: dict[str, _Limiter] = {}
        self._lock = threading.Lock()
        self.stats: dict[str, int] = defaultdict(int)

    def _limiter(self, host: str) -> _Limiter:
        with self._lock:
            if host not in self._limiters:
                self._limiters[host] = _Limiter(HOST_RPM.get(host, DEFAULT_RPM))
            return self._limiters[host]

    def get(self, url: str, params: dict | None = None):
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return self._request(url, None)

    def post(self, url: str, body: dict):
        return self._request(url, json.dumps(body).encode())

    def _request(self, url: str, data: bytes | None):
        host = urllib.parse.urlsplit(url).hostname or ""
        limiter = self._limiter(host)
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            limiter.wait()
            headers = {"accept": "application/json", "user-agent": USER_AGENT}
            if data is not None:
                headers["content-type"] = "application/json"
            req = urllib.request.Request(url, data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self.stats[host] += 1
                    payload = json.loads(resp.read() or b"null")
                    if isinstance(payload, dict) and payload.get("error") and "jsonrpc" in payload:
                        err = payload["error"]
                        if isinstance(err, dict) and err.get("code") == 429:
                            raise HttpError(url, 429, str(err))
                    return payload
            except urllib.error.HTTPError as e:
                self.stats[f"{host}:{e.code}"] += 1
                last_err = HttpError(url, e.code, e.reason)
                if e.code == 429 or e.code >= 500:
                    backoff = (2 ** attempt) * 2 + random.random()
                    limiter.penalize(backoff)
                    continue
                raise last_err from None
            except HttpError as e:
                last_err = e
                limiter.penalize((2 ** attempt) * 2 + random.random())
                continue
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
                self.stats[f"{host}:neterr"] += 1
                last_err = HttpError(url, None, repr(e))
                time.sleep(1 + attempt)
                continue
        assert last_err is not None
        raise last_err
