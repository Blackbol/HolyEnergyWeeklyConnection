"""Holy Energy Weekly Connection — automates weekly login to earn HOLY Coins."""

from holy_energy_weekly_connection.client import HolyEnergyClient
from holy_energy_weekly_connection.exceptions import (
    AuthenticationError,
    ConfigurationError,
    HolyEnergyError,
    NetworkError,
)
from holy_energy_weekly_connection.models import ConnectionResult, Credentials

__all__ = [
    "HolyEnergyClient",
    "HolyEnergyError",
    "AuthenticationError",
    "ConfigurationError",
    "NetworkError",
    "ConnectionResult",
    "Credentials",
]
