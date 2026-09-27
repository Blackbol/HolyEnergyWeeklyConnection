"""Tests for Pydantic data models."""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import SecretStr

from holy_energy_weekly_connection.models import (
    ConnectionResult,
    Credentials,
    CustomerInfo,
)


def test_credentials_defaults() -> None:
    creds = Credentials(shopify_cookie=SecretStr("secret_cookie_val"))
    assert creds.shopify_cookie.get_secret_value() == "secret_cookie_val"
    assert creds.email == ""
    assert creds.timeout == 30
    assert creds.cookie_file == Path("data/cookie.txt")
    assert creds.discord_webhook is None
    assert creds.telegram_bot_token is None
    assert creds.ntfy_topic is None


def test_credentials_secret_str_masking() -> None:
    creds = Credentials(
        shopify_cookie=SecretStr("super_secret"),
        discord_webhook=SecretStr("https://discord.com/api/webhooks/123/abc"),
    )
    assert "super_secret" not in repr(creds)
    assert "discord.com" not in repr(creds)
    assert creds.shopify_cookie.get_secret_value() == "super_secret"


def test_customer_info() -> None:
    info = CustomerInfo(
        customer_id="cust_123",
        email="test@example.com",
        auth_date="2026-09-27T12:00:00Z",
        mac="a" * 40,
        shop_token="shop_token_xyz",
    )
    assert info.customer_id == "cust_123"
    assert info.email == "test@example.com"
    assert info.mac == "a" * 40


def test_connection_result() -> None:
    now = datetime.now(tz=UTC)
    res = ConnectionResult(
        success=True,
        timestamp=now,
        points_credited=True,
        points_awarded=25,
        total_balance=350,
        message="25 points crédités",
        customer_id="cust_123",
        customer_email="test@example.com",
    )
    assert res.success is True
    assert res.points_credited is True
    assert res.points_awarded == 25
    assert res.total_balance == 350
