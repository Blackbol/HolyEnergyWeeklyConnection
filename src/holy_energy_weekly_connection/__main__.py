"""Entry point: python -m holy_energy_weekly_connection"""

import logging
import os
import sys

from dotenv import load_dotenv

from holy_energy_weekly_connection.client import HolyEnergyClient
from holy_energy_weekly_connection.exceptions import (
    AuthenticationError,
    ConfigurationError,
    HolyEnergyError,
)
from holy_energy_weekly_connection.models import Credentials

PROD = 25
logging.addLevelName(PROD, "PROD")


def _setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    numeric = getattr(logging, level, None)
    if numeric is None:
        numeric = PROD if level == "PROD" else logging.INFO
    fmt = "%(message)s" if level == "PROD" else "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(format=fmt, level=numeric)


def _load_credentials() -> Credentials:
    email = os.getenv("HOLY_EMAIL", "").strip()
    password = os.getenv("HOLY_PASSWORD", "").strip()
    shopify_cookie = os.getenv("HOLY_SHOPIFY_COOKIE", "").strip()
    timeout_raw = os.getenv("HOLY_TIMEOUT", "30").strip()

    missing = [
        name
        for name, val in [
            ("HOLY_EMAIL", email),
            ("HOLY_PASSWORD", password),
            ("HOLY_SHOPIFY_COOKIE", shopify_cookie),
        ]
        if not val
    ]
    if missing:
        raise ConfigurationError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill in your credentials."
        )

    try:
        timeout = int(timeout_raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"HOLY_TIMEOUT must be an integer, got: {timeout_raw!r}"
        ) from exc

    return Credentials(
        email=email,
        password=password,
        shopify_cookie=shopify_cookie,
        timeout=timeout,
    )


def main() -> None:
    """Load credentials and perform the weekly connection."""
    load_dotenv()
    _setup_logging()

    logger = logging.getLogger(__name__)

    try:
        credentials = _load_credentials()
    except ConfigurationError as exc:
        logging.error("Configuration error: %s", exc)
        sys.exit(1)

    try:
        with HolyEnergyClient(credentials) as client:
            result = client.connect()
        logger.info(result.message)
    except AuthenticationError as exc:
        logger.error("Authentication failed: %s", exc)
        sys.exit(1)
    except HolyEnergyError as exc:
        logger.error("Connection failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
