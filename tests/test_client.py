"""Comprehensive tests for HolyEnergyClient."""

import base64
import json
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from pytest_httpx import HTTPXMock

from holy_energy_weekly_connection.client import (
    ACCOUNT_LOGIN_URL,
    ACCOUNT_URL,
    STORE_URL,
    HolyEnergyClient,
    _js_encode,
)
from holy_energy_weekly_connection.exceptions import (
    AuthenticationError,
)
from holy_energy_weekly_connection.models import Credentials

SAMPLE_AUTH_HTML = """
<!DOCTYPE html>
<html>
<head><title>Account - Holy</title></head>
<body>
<script>
  loyaltylion.init({
    token: "6e324c01a0c0fc74286ffcd8000b5912",
    customer: {
      id: "9876543210",
      email: "alex@example.com",
      date: "2026-09-27T10:00:00Z",
      auth: {
        token: "abcdef1234567890abcdef1234567890abcdef12"
      }
    }
  });
</script>
</body>
</html>
"""

SAMPLE_REAL_HOLY_HTML = """
<!DOCTYPE html>
<html>
<head><title>Mon Compte - Holy Energy</title></head>
<body>
<script>
      loyaltylion.init(
        {
          token: "6e324c01a0c0fc74286ffcd8000b5912",
          customer: {
            id: 79123456789,
            email: "Alexlimongi30+holy@gmail.com"
          },
          auth: {
            date: 1727440000,
            token: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4"
          }
        }
      );
</script>
</body>
</html>
"""

SAMPLE_UNAUTH_HTML = """
<!DOCTYPE html>
<html>
<head><title>Account login</title></head>
<body>
<form class="ds-loyalty-hero__form" action="/customer_authentication/login" method="get">
  <input type="email" name="login_hint" />
</form>
<script>
  loyaltylion.init({
    token: "6e324c01a0c0fc74286ffcd8000b5912"
  });
</script>
</body>
</html>
"""


def test_js_encode() -> None:
    obj = {"test": 123, "name": "holy"}
    encoded = _js_encode(obj)
    # decode base64 then unquote
    raw_str = urllib.parse.unquote(base64.b64decode(encoded).decode("utf-8"))
    assert json.loads(raw_str) == obj


def test_parse_loyaltylion_tokens_success(tmp_path: Path) -> None:
    creds = Credentials(
        shopify_cookie=SecretStr("valid_cookie"),
        cookie_file=tmp_path / "cookie.txt",
    )
    with patch("holy_energy_weekly_connection.client.ensure_dns_resolution"):
        client = HolyEnergyClient(creds)
        customer = client._parse_loyaltylion_tokens(SAMPLE_AUTH_HTML)
        assert customer is not None
        assert customer.customer_id == "9876543210"
        assert customer.email == "alex@example.com"
        assert customer.auth_date == "2026-09-27T10:00:00Z"
        assert customer.mac == "abcdef1234567890abcdef1234567890abcdef12"
        assert customer.shop_token == "6e324c01a0c0fc74286ffcd8000b5912"


def test_parse_loyaltylion_tokens_real_holy_layout(tmp_path: Path) -> None:
    creds = Credentials(
        shopify_cookie=SecretStr("valid_cookie"),
        cookie_file=tmp_path / "cookie.txt",
    )
    with patch("holy_energy_weekly_connection.client.ensure_dns_resolution"):
        client = HolyEnergyClient(creds)
        customer = client._parse_loyaltylion_tokens(SAMPLE_REAL_HOLY_HTML)
        assert customer is not None
        assert customer.customer_id == "79123456789"
        assert customer.email == "Alexlimongi30+holy@gmail.com"
        assert customer.auth_date == "1727440000"
        assert customer.mac == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4"
        assert customer.shop_token == "6e324c01a0c0fc74286ffcd8000b5912"


def test_parse_loyaltylion_tokens_unauth(tmp_path: Path) -> None:
    creds = Credentials(
        shopify_cookie=SecretStr("valid_cookie"),
        cookie_file=tmp_path / "cookie.txt",
    )
    with patch("holy_energy_weekly_connection.client.ensure_dns_resolution"):
        client = HolyEnergyClient(creds)
        customer = client._parse_loyaltylion_tokens(SAMPLE_UNAUTH_HTML)
        assert customer is None


def test_verify_session_success(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookie.txt"
    creds = Credentials(shopify_cookie=SecretStr("valid_cookie"), cookie_file=cookie_file)

    httpx_mock.add_response(
        url=STORE_URL,
        text=SAMPLE_AUTH_HTML,
        headers={"Set-Cookie": "_shopify_essential=rotated_new_cookie; Path=/; Domain=fr.holy.com"},
    )

    with (
        patch("holy_energy_weekly_connection.client.ensure_dns_resolution"),
        HolyEnergyClient(creds) as client,
    ):
        customer = client.verify_session()
        assert customer.customer_id == "9876543210"
        assert customer.email == "alex@example.com"

    # Verify that the rotated cookie was saved
    assert cookie_file.is_file()
    assert cookie_file.read_text(encoding="utf-8") == "rotated_new_cookie"


def test_verify_session_unauth_raises_error(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookie.txt"
    creds = Credentials(shopify_cookie=SecretStr("expired_cookie"), cookie_file=cookie_file)

    for u in [ACCOUNT_URL, STORE_URL, ACCOUNT_LOGIN_URL]:
        httpx_mock.add_response(
            url=u,
            text=SAMPLE_UNAUTH_HTML,
        )

    with (
        patch("holy_energy_weekly_connection.client.ensure_dns_resolution"),
        HolyEnergyClient(creds) as client,
        pytest.raises(AuthenticationError) as exc_info,
    ):
        client.verify_session()
    assert "_shopify_essential" in str(exc_info.value)

    # Ensure unauthenticated cookie was NOT saved
    assert not cookie_file.is_file()


def test_verify_session_fallback_from_cookie_file_to_env(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    cookie_file = tmp_path / "cookie.txt"
    cookie_file.write_text("old_stale_cookie", encoding="utf-8")

    creds = Credentials(
        shopify_cookie=SecretStr("fresh_env_cookie"),
        cookie_file=cookie_file,
    )

    # First request with old cookie returns unauth HTML across endpoints
    for u in [ACCOUNT_URL, STORE_URL, ACCOUNT_LOGIN_URL]:
        httpx_mock.add_response(
            url=u,
            text=SAMPLE_UNAUTH_HTML,
        )
    # Second request with fresh env cookie returns auth HTML on STORE_URL
    httpx_mock.add_response(
        url=STORE_URL,
        text=SAMPLE_AUTH_HTML,
        headers={"Set-Cookie": "_shopify_essential=new_rotated_cookie; Path=/; Domain=fr.holy.com"},
    )

    with (
        patch("holy_energy_weekly_connection.client.ensure_dns_resolution"),
        HolyEnergyClient(creds) as client,
    ):
        customer = client.verify_session()
        assert customer.customer_id == "9876543210"

    # Rolling cookie file was updated with the new cookie from the successful response
    assert cookie_file.read_text(encoding="utf-8") == "new_rotated_cookie"


def test_evaluate_loyaltylion_new_points_via_notifications(tmp_path: Path) -> None:
    creds = Credentials(shopify_cookie=SecretStr("dummy_cookie"), cookie_file=tmp_path / "c.txt")
    with patch("holy_energy_weekly_connection.client.ensure_dns_resolution"):
        client = HolyEnergyClient(creds)
        data = {
            "customer": {
                "pointsApproved": 375,
                "pendingNotifications": [{"text": "You earned 25 points"}],
            }
        }
        credited, msg, bal = client._evaluate_loyaltylion_response(data)
        assert credited is True
        assert bal == 375
        assert "25 HOLY Coins crédités" in msg


def test_evaluate_loyaltylion_already_credited_rule_context(tmp_path: Path) -> None:
    creds = Credentials(shopify_cookie=SecretStr("dummy_cookie"), cookie_file=tmp_path / "c.txt")
    with patch("holy_energy_weekly_connection.client.ensure_dns_resolution"):
        client = HolyEnergyClient(creds)
        data = {
            "customer": {
                "pointsApproved": 350,
                "actions": [{"ruleId": 42, "ruleKind": "pageview"}],
                "ruleContext": [{"id": 42, "limitReached": True}],
            }
        }
        credited, msg, bal = client._evaluate_loyaltylion_response(data)
        assert credited is False
        assert bal == 350
        assert "Points déjà crédités cette semaine" in msg


def test_connect_full_flow(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookie.txt"
    creds = Credentials(
        shopify_cookie=SecretStr("valid_cookie"),
        cookie_file=cookie_file,
        email="alex@example.com",
    )

    # 1. Verification request to fr.holy.com
    httpx_mock.add_response(
        url=STORE_URL,
        text=SAMPLE_AUTH_HTML,
    )

    # 2. POST to LoyaltyLion init endpoint
    httpx_mock.add_response(
        method="POST",
        url=None,  # match by host or any params
        text=json.dumps(
            {
                "customer": {
                    "pointsApproved": 425,
                    "pendingNotifications": [{"message": "25 points awarded"}],
                }
            }
        ),
    )

    with (
        patch("holy_energy_weekly_connection.client.ensure_dns_resolution"),
        HolyEnergyClient(creds) as client,
    ):
        result = client.connect()

    assert result.success is True
    assert result.points_credited is True
    assert result.points_awarded == 25
    assert result.total_balance == 425
    assert result.customer_id == "9876543210"
