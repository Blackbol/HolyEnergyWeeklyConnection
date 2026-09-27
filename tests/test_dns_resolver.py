"""Tests for DNS resolver and ad-block bypass logic."""

from unittest.mock import patch

from holy_energy_weekly_connection.dns_resolver import (
    ensure_dns_resolution,
    is_blocked_ip,
    is_domain_blocked,
)


def test_is_blocked_ip() -> None:
    assert is_blocked_ip("0.0.0.0") is True
    assert is_blocked_ip("127.0.0.1") is True
    assert is_blocked_ip("::") is True
    assert is_blocked_ip("::1") is True
    assert is_blocked_ip("") is True
    assert is_blocked_ip("52.85.118.88") is False
    assert is_blocked_ip("1.1.1.1") is False


def test_is_domain_blocked_when_resolves_to_zero() -> None:
    with patch(
        "holy_energy_weekly_connection.dns_resolver._ORIG_GETADDRINFO",
        return_value=[(2, 1, 6, "", ("0.0.0.0", 443))],
    ):
        assert is_domain_blocked("sdk.loyaltylion.net") is True


def test_is_domain_blocked_when_normal() -> None:
    with patch(
        "holy_energy_weekly_connection.dns_resolver._ORIG_GETADDRINFO",
        return_value=[(2, 1, 6, "", ("52.85.118.88", 443))],
    ):
        assert is_domain_blocked("sdk.loyaltylion.net") is False


def test_ensure_dns_resolution_already_cached() -> None:
    with patch.dict(
        "holy_energy_weekly_connection.dns_resolver._RESOLVED_CACHE",
        {"sdk.loyaltylion.net": "52.85.118.88"},
    ):
        assert ensure_dns_resolution("sdk.loyaltylion.net") is True


def test_ensure_dns_resolution_doh_fallback() -> None:
    with (
        patch("holy_energy_weekly_connection.dns_resolver.is_domain_blocked", return_value=True),
        patch(
            "holy_energy_weekly_connection.dns_resolver.resolve_via_doh",
            return_value="52.85.118.99",
        ),
    ):
        assert ensure_dns_resolution("custom-domain.test") is True
