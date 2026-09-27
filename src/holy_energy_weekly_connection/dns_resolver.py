"""Resilient DNS resolution with DNS-over-HTTPS fallback to bypass local ad-blockers."""

import json
import logging
import socket
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Primary domain that is commonly blocked by Pi-hole / AdGuard / local DNS
LOYALTYLION_HOST = "sdk.loyaltylion.net"

# Public DoH providers to query when local DNS is blocking or broken
DOH_ENDPOINTS = [
    "https://1.1.1.1/dns-query?name={domain}&type=A",
    "https://dns.google/resolve?name={domain}&type=A",
]

_ORIG_GETADDRINFO = socket.getaddrinfo
_PATCHED = False
_RESOLVED_CACHE: dict[str, str] = {}


def resolve_via_doh(domain: str) -> str | None:
    """Resolve an A record for domain using DNS-over-HTTPS (DoH)."""
    for endpoint in DOH_ENDPOINTS:
        url = endpoint.format(domain=domain)
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "accept": "application/dns-json",
                    "User-Agent": "holy-energy-weekly-connection/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for answer in data.get("Answer", []):
                    # type 1 is A record
                    if answer.get("type") == 1:
                        ip = str(answer.get("data", "")).strip()
                        if ip and not is_blocked_ip(ip):
                            return ip
        except Exception as exc:
            logger.debug("DoH query failed for %s on %s: %s", domain, url, exc)
    return None


def is_blocked_ip(ip: str) -> bool:
    """Return True if an IP is a known sinkhole/null route used by ad blockers."""
    return ip in ("0.0.0.0", "127.0.0.1", "::", "::1", "")


def is_domain_blocked(domain: str) -> bool:
    """Check if the system DNS resolves the domain to a sinkhole/blocked IP."""
    try:
        results = _ORIG_GETADDRINFO(domain, 443, socket.AF_INET, socket.SOCK_STREAM)
        for _, _, _, _, sockaddr in results:
            ip = str(sockaddr[0])
            if is_blocked_ip(ip):
                return True
        return False
    except socket.gaierror:
        # Cannot resolve via system DNS
        return True
    except Exception:
        return False


def ensure_dns_resolution(domain: str = LOYALTYLION_HOST) -> bool:
    """Ensure domain resolves correctly, patching socket.getaddrinfo if local DNS blocks it."""
    global _PATCHED

    if domain in _RESOLVED_CACHE:
        return True

    # Check if system DNS resolves it properly
    if not is_domain_blocked(domain):
        return True

    logger.warning(
        "Domain %s is blocked or unresolvable by local DNS (Pi-hole/AdGuard). Attempting DoH fallback...",
        domain,
    )
    fallback_ip = resolve_via_doh(domain)
    if not fallback_ip:
        logger.error("Failed to resolve %s via DNS-over-HTTPS fallback.", domain)
        return False

    _RESOLVED_CACHE[domain] = fallback_ip
    logger.info("Resolved %s -> %s via secure DoH fallback.", domain, fallback_ip)

    if not _PATCHED:

        def custom_getaddrinfo(
            host: Any,
            port: Any,
            family: int = 0,
            type: int = 0,
            proto: int = 0,
            flags: int = 0,
        ) -> Any:
            if isinstance(host, str) and host in _RESOLVED_CACHE:
                target_ip = _RESOLVED_CACHE[host]
                return _ORIG_GETADDRINFO(target_ip, port, family, type, proto, flags)
            return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)

        socket.getaddrinfo = custom_getaddrinfo
        _PATCHED = True

    return True
