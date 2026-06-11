"""Geo-IP adapter — resolve a client IP to coarse geography for the public audience widget.

Privacy: this module is the *only* place an IP is handled, and it returns only country/region.
Nothing here (and nothing downstream) persists the raw IP. Lookups go to a free, no-key HTTPS
endpoint (`settings.geo_lookup_url`, default ipwho.is); private/loopback IPs short-circuit and
any failure degrades to None so the visit is still counted as "Unknown".
"""

from __future__ import annotations

import ipaddress
import logging
import time

import httpx

from ..config import settings

log = logging.getLogger(__name__)

# In-process cache so repeat lookups of the same IP don't re-hit the provider (and to stay well
# under free-tier rate limits). Visitors are de-duplicated by cookie upstream, so this mostly
# guards bursts; a short TTL is plenty.
_CACHE: dict[str, tuple[float, dict | None]] = {}
_TTL_SECONDS = 6 * 60 * 60


def _is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def lookup(ip: str | None, *, timeout: float = 4.0) -> dict | None:
    """Resolve an IP to ``{country_code, country_name, region}``, or None when it can't be
    resolved (private/invalid IP, provider error, or unknown location). Never raises."""
    if not ip or not _is_public(ip):
        return None

    cached = _CACHE.get(ip)
    if cached and (time.time() - cached[0]) < _TTL_SECONDS:
        return cached[1]

    result: dict | None = None
    try:
        resp = httpx.get(settings.geo_lookup_url.format(ip=ip), timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        # ipwho.is / ip-api both signal failure in-band rather than via HTTP status.
        if data.get("success") is False or data.get("status") == "fail":
            result = None
        else:
            code = data.get("country_code") or data.get("countryCode")
            name = data.get("country")
            region = data.get("region") or data.get("regionName")
            result = (
                {
                    "country_code": code or None,
                    "country_name": name or None,
                    "region": region or None,
                }
                if (code or name)
                else None
            )
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.debug("geo lookup failed for %s: %s", ip, exc)
        result = None

    _CACHE[ip] = (time.time(), result)
    return result
