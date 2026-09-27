"""Holy Energy Weekly Connection — automates weekly login to earn HOLY Coins."""

from holy_energy_weekly_connection.client import HolyEnergyClient
from holy_energy_weekly_connection.exceptions import (
    AuthenticationError,
    ConfigurationError,
    HolyEnergyError,
    LoyaltyLionError,
    NetworkError,
)
from holy_energy_weekly_connection.models import (
    ConnectionResult,
    Credentials,
    CustomerInfo,
)

__all__ = [
    "HolyEnergyClient",
    "HolyEnergyError",
    "AuthenticationError",
    "ConfigurationError",
    "NetworkError",
    "LoyaltyLionError",
    "ConnectionResult",
    "Credentials",
    "CustomerInfo",
]
