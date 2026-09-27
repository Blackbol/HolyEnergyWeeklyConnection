"""Tests for notification dispatcher."""

from datetime import UTC, datetime

from pydantic import SecretStr
from pytest_httpx import HTTPXMock

from holy_energy_weekly_connection.models import ConnectionResult, Credentials
from holy_energy_weekly_connection.notifier import send_notification


def test_send_notification_no_channels(httpx_mock: HTTPXMock) -> None:
    creds = Credentials(shopify_cookie=SecretStr("test"))
    send_notification(creds, result=None, error=None)
    assert len(httpx_mock.get_requests()) == 0


def test_send_notification_discord_success(httpx_mock: HTTPXMock) -> None:
    webhook_url = "https://discord.com/api/webhooks/123/abc"
    httpx_mock.add_response(url=webhook_url, status_code=204)

    creds = Credentials(
        shopify_cookie=SecretStr("test"),
        discord_webhook=SecretStr(webhook_url),
        email="alex@example.com",
    )
    result = ConnectionResult(
        success=True,
        timestamp=datetime.now(tz=UTC),
        points_credited=True,
        points_awarded=25,
        total_balance=400,
        message="25 points crédités",
        customer_email="alex@example.com",
    )
    send_notification(creds, result=result)

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert requests[0].url == webhook_url


def test_send_notification_ntfy(httpx_mock: HTTPXMock) -> None:
    ntfy_url = "https://ntfy.sh/my-holy-topic"
    httpx_mock.add_response(url=ntfy_url, status_code=200)

    creds = Credentials(
        shopify_cookie=SecretStr("test"),
        ntfy_topic="my-holy-topic",
    )
    send_notification(creds, error=ValueError("Test error"))

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert str(requests[0].url) == ntfy_url
