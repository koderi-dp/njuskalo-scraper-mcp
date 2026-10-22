"""Fetch Njuskalo pages politely: browser TLS fingerprint, rate limit, cache.

Njuskalo sits behind Radware/ShieldSquare bot protection. A session that never
runs the site's JavaScript is allowed a few page views, then gets redirected to
an hCaptcha page on validate.perfdrive.com; datacenter and proxy IPs hit that
sooner, and a headless browser is challenged on its first page load there, so
there is no browser fallback. Once a session has been challenged every later
request from it is challenged too, so a challenged session is discarded.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import random
import time

from curl_cffi.requests import AsyncSession

from .parser import STATE_MARKER


class BlockedError(RuntimeError):
    """Njuskalo refused the request (bot protection, geo-block, or timeout)."""


BLOCK_HINT = (
    "Njuskalo's bot protection (Radware) answered with a captcha challenge. "
    "This happens after a few page views, sooner from datacenter or proxy IPs. "
    "Wait 10-15 minutes before searching again; for reliable use run the server "
    "on a home connection in Croatia or set NJUSKALO_PROXY to a residential proxy."
)


def looks_blocked(html: str, final_url: str = "") -> bool:
    if "validate.perfdrive" in final_url or "shieldsquare" in final_url.lower():
        return True
    if STATE_MARKER in html:
        return False  # the security script can be present on pages that loaded fine
    return any(m in html for m in ("validate.perfdrive", "hcaptcha.com", "_pxBlock", "px-captcha", "captcha-delivery"))


class Fetcher:
    def __init__(
        self,
        min_delay: float = float(os.getenv("NJUSKALO_MIN_DELAY", "1.5")),
        cache_ttl: float = float(os.getenv("NJUSKALO_CACHE_TTL", "3600")),
        proxy: str | None = os.getenv("NJUSKALO_PROXY") or None,
        timeout: float = 25.0,
    ) -> None:
        self.min_delay = min_delay
        self.cache_ttl = cache_ttl
        self.proxy = proxy
        self.timeout = timeout
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._session: AsyncSession | None = None

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            self._session = AsyncSession(
                impersonate="chrome",
                proxy=self.proxy,
                timeout=self.timeout,
                headers={"Accept-Language": "hr-HR,hr;q=0.9,en;q=0.8"},
            )
        return self._session

    async def get(self, url: str) -> str:
        cached = self._cache.get(url)
        if cached and time.monotonic() - cached[0] < self.cache_ttl:
            return cached[1]

        async with self._lock:  # one request at a time, spaced out
            wait = self.min_delay + random.uniform(0, 0.8) - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            session = await self._get_session()
            try:
                resp = await session.get(url)
            except Exception as exc:  # timeouts are how geo-blocks usually show up
                raise BlockedError(f"{BLOCK_HINT} ({type(exc).__name__}: {exc})") from exc
            finally:
                self._last_request = time.monotonic()

        html = resp.text
        if resp.status_code in (403, 429) or looks_blocked(html, str(resp.url)):
            await self._reset_session()  # the jar now holds challenge cookies; a fresh one may pass
            raise BlockedError(BLOCK_HINT)
        elif resp.status_code == 404:
            raise LookupError(f"Ad or page not found: {url}")
        elif resp.status_code >= 400:
            raise BlockedError(f"HTTP {resp.status_code} from Njuskalo for {url}")

        self._cache[url] = (time.monotonic(), html)
        return html

    async def _reset_session(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            with contextlib.suppress(Exception):  # closing a dead session must not mask the block
                await session.close()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
