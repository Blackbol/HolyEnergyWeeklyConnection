"""Tests for CLI interface."""

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holy_energy_weekly_connection.cli import (
    cmd_daemon,
    cmd_run,
    cmd_set_cookie,
    cmd_verify,
    load_credentials_from_env,
)
from holy_energy_weekly_connection.exceptions import (
    AuthenticationError,
    ConfigurationError,
)
from holy_energy_weekly_connection.models import ConnectionResult, CustomerInfo


def test_load_credentials_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HOLY_SHOPIFY_COOKIE", raising=False)
    monkeypatch.setenv("HOLY_COOKIE_FILE", str(tmp_path / "non_existent.txt"))
    with (
        patch("holy_energy_weekly_connection.cli.load_dotenv"),
        pytest.raises(ConfigurationError) as exc_info,
    ):
        load_credentials_from_env()
    assert "Aucun cookie de session trouvé" in str(exc_info.value)


def test_load_credentials_placeholder_cookie(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOLY_SHOPIFY_COOKIE", ":AZ...collez_votre_cookie_complet_ici...")
    monkeypatch.setenv("HOLY_COOKIE_FILE", str(tmp_path / "non_existent.txt"))
    with (
        patch("holy_energy_weekly_connection.cli.load_dotenv"),
        pytest.raises(ConfigurationError) as exc_info,
    ):
        load_credentials_from_env()
    assert "texte d'exemple" in str(exc_info.value) or "incomplet" in str(exc_info.value)


def test_load_credentials_ellipsis_cookie(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOLY_SHOPIFY_COOKIE", ":AZ123456789...rest_of_token:")
    monkeypatch.setenv("HOLY_COOKIE_FILE", str(tmp_path / "non_existent.txt"))
    with (
        patch("holy_energy_weekly_connection.cli.load_dotenv"),
        pytest.raises(ConfigurationError) as exc_info,
    ):
        load_credentials_from_env()
    assert "incomplet" in str(exc_info.value)


def test_load_credentials_short_cookie(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOLY_SHOPIFY_COOKIE", "short_cookie")
    monkeypatch.setenv("HOLY_COOKIE_FILE", str(tmp_path / "non_existent.txt"))
    with (
        patch("holy_energy_weekly_connection.cli.load_dotenv"),
        pytest.raises(ConfigurationError) as exc_info,
    ):
        load_credentials_from_env()
    assert "anormalement court" in str(exc_info.value)


def test_load_credentials_from_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookie.txt"
    cookie_file.write_text("cookie_from_disk_valid", encoding="utf-8")
    monkeypatch.delenv("HOLY_SHOPIFY_COOKIE", raising=False)
    monkeypatch.setenv("HOLY_COOKIE_FILE", str(cookie_file))
    with patch("holy_energy_weekly_connection.cli.load_dotenv"):
        creds = load_credentials_from_env()
    assert creds.shopify_cookie.get_secret_value() == "cookie_from_disk_valid"


def test_cmd_run_success() -> None:
    args = argparse.Namespace()
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.connect.return_value = MagicMock(spec=ConnectionResult)

    with (
        patch("holy_energy_weekly_connection.cli.load_credentials_from_env"),
        patch("holy_energy_weekly_connection.cli.HolyEnergyClient", return_value=mock_client),
    ):
        exit_code = cmd_run(args)
        assert exit_code == 0
        mock_client.connect.assert_called_once()


def test_cmd_run_auth_error() -> None:
    args = argparse.Namespace()
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.connect.side_effect = AuthenticationError("Cookie expired")

    with (
        patch("holy_energy_weekly_connection.cli.load_credentials_from_env"),
        patch("holy_energy_weekly_connection.cli.HolyEnergyClient", return_value=mock_client),
    ):
        exit_code = cmd_run(args)
        assert exit_code == 2


def test_cmd_verify_success() -> None:
    args = argparse.Namespace()
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.verify_session.return_value = CustomerInfo(
        customer_id="123",
        email="alex@test.com",
        auth_date="2026-09-27",
        mac="a" * 40,
        shop_token="tok",
    )

    with (
        patch("holy_energy_weekly_connection.cli.load_credentials_from_env"),
        patch("holy_energy_weekly_connection.cli.HolyEnergyClient", return_value=mock_client),
    ):
        exit_code = cmd_verify(args)
        assert exit_code == 0


def test_cmd_set_cookie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cookie_file = tmp_path / "cookie.txt"
    monkeypatch.setenv("HOLY_COOKIE_FILE", str(cookie_file))
    args = argparse.Namespace(cookie="new_cookie_content")

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.verify_session.return_value = CustomerInfo(
        customer_id="123",
        email="alex@test.com",
        auth_date="2026-09-27",
        mac="a" * 40,
        shop_token="tok",
    )

    with (
        patch("holy_energy_weekly_connection.cli.load_credentials_from_env"),
        patch("holy_energy_weekly_connection.cli.HolyEnergyClient", return_value=mock_client),
    ):
        exit_code = cmd_set_cookie(args)
        assert exit_code == 0
        assert cookie_file.read_text(encoding="utf-8") == "new_cookie_content"


def test_cmd_daemon_invalid_cookie_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HOLY_SHOPIFY_COOKIE", raising=False)
    monkeypatch.setenv("HOLY_COOKIE_FILE", str(tmp_path / "non_existent.txt"))
    with patch("holy_energy_weekly_connection.cli.load_dotenv"):
        exit_code = cmd_daemon(argparse.Namespace())
        assert exit_code == 1


def test_cmd_daemon_with_invalid_cron(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOLY_SHOPIFY_COOKIE", "some_valid_looking_cookie_of_good_length")
    with patch("holy_energy_weekly_connection.cli.load_dotenv"):
        args = argparse.Namespace(cron="bad cron expression", now=False)
        exit_code = cmd_daemon(args)
        assert exit_code == 1


def test_cmd_daemon_starts_and_stops_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOLY_SHOPIFY_COOKIE", "some_valid_looking_cookie_of_good_length")
    with (
        patch("holy_energy_weekly_connection.cli.load_dotenv"),
        patch("holy_energy_weekly_connection.scheduler.WeeklyScheduler.start") as mock_start,
    ):
        args = argparse.Namespace(cron="0 8 * * 1", now=False)
        exit_code = cmd_daemon(args)
        assert exit_code == 0
        mock_start.assert_called_once()
